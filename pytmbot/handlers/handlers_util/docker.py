#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.containers_info import (
    fetch_container_logs,
    fetch_full_container_details,
)
from pytmbot.adapters.docker.utils import (
    command_executable,
    get_container_memory_stats,
    get_container_stats_snapshot,
    mask_entrypoint_and_cmd,
    mask_environment_variables,
    mask_free_text,
    parse_docker_timestamp,
    validate_container_reference,
)
from pytmbot.exceptions import InvalidContainerReferenceError
from pytmbot.globals import get_emoji_converter, settings
from pytmbot.handlers.auth_processing.auth_processing import is_private_chat
from pytmbot.handlers.handlers_util.callback_auth import authorize_callback_request
from pytmbot.logs import Logger
from pytmbot.utils import (
    as_object_dict,
    sanitize_logs,
    set_naturalsize,
    set_naturaltime,
    to_float,
    to_int,
)
from pytmbot.utils.telegram_utils import callback_query_id

logger = Logger()
em = get_emoji_converter()

# Delay between the two stats samples used to compute CPU% when the daemon's
# one-shot stats carry no previous CPU sample.
CPU_SAMPLE_INTERVAL_SECONDS: Final[float] = 0.5
MAX_DISPLAYED_ENV_VARS: Final[int] = 20
MAX_ENV_VALUE_LENGTH: Final[int] = 100
# Shown instead of a Cmd that only holds arguments (no executable of its own).
COMMAND_ARGUMENTS_HIDDEN_TEXT: Final[str] = "hidden"
COMMAND_ARGUMENTS_MASKED_NOTE: Final[str] = "Values that look like secrets are masked."
COMMAND_ARGUMENTS_ADMINS_ONLY_NOTE: Final[str] = "Arguments are visible to admins only."
COMMAND_ARGUMENTS_PRIVATE_CHAT_NOTE: Final[str] = (
    "Arguments are shown to admins in a private chat with the bot."
)
_STATUS_BADGES: Final[dict[str, str]] = {
    "running": "🟢 Running",
    "paused": "🟡 Paused",
    "restarting": "🔄 Restarting",
    "created": "⚪ Created",
    "removing": "🟠 Removing",
    "exited": "🔴 Stopped",
    "dead": "🔴 Dead",
}


def validate_container_name(name: str) -> bool:
    """Validate a container reference (exact name or ID) from callback data."""
    try:
        validate_container_reference(name)
    except InvalidContainerReferenceError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class AuthorizedContainerCallbackContext:
    """Parsed and authorized callback context for container handlers."""

    callback_data: str
    container_name: str
    user_id: int


def show_handler_info(call: CallbackQuery, text: str, bot: TeleBot) -> bool:
    """
    Handles the case when a container is not found.

    Args:
        call (CallbackQuery): The callback query object.
        text (str): The text to display in the alert.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    return bot.answer_callback_query(
        callback_query_id=callback_query_id(call), text=text, show_alert=True
    )


def get_required_callback_data(
    call: CallbackQuery,
    bot: TeleBot,
    *,
    missing_message_text: str,
    invalid_button_text: str,
    missing_user_text: str = "Couldn't verify who pressed this button.",
    alert_handler: Callable[[CallbackQuery, str, TeleBot], object] = show_handler_info,
) -> str | None:
    """Validate common callback prerequisites and return callback data."""
    checks = (
        (call.from_user is None, missing_user_text),
        (call.message is None, missing_message_text),
        (call.data is None, invalid_button_text),
    )
    for failed, text in checks:
        if failed:
            alert_handler(call, text, bot)
            return None

    callback_data = call.data
    if callback_data is None:
        return None
    return callback_data


def authorize_docker_callback_request(
    call: CallbackQuery,
    called_user_id: int | str,
    *,
    require_admin: bool = True,
    require_owner_match: bool = True,
    require_session: bool = True,
) -> tuple[bool, str]:
    """
    Centralized authorization guard for Docker callback handlers.

    Keeps defense-in-depth:
    - decorator-level checks (2FA/session middleware)
    - explicit runtime checks for direct module calls
    """
    if call.from_user is None:
        return False, "Missing user information"

    try:
        target_user_id = int(called_user_id)
    except (TypeError, ValueError):
        return False, "Invalid target user id"

    return authorize_callback_request(
        call,
        target_user_id=target_user_id,
        require_owner_match=require_owner_match,
        require_admin=require_admin,
        require_session=require_session,
    )


def _callback_field(callback_data: str, index: int) -> str:
    """Return a ``:``-separated callback field without changing its case."""
    fields = callback_data.split(":")
    if not 0 <= index < len(fields):
        raise IndexError("Callback field index out of range")
    return fields[index]


def get_authorized_container_callback_context(
    call: CallbackQuery,
    bot: TeleBot,
    *,
    operation_label: str,
    missing_user_event: str,
    denied_event: str,
) -> AuthorizedContainerCallbackContext | None:
    """
    Parse and authorize Docker container callback request.

    Returns parsed context on success, otherwise sends user-facing callback alert and returns None.
    """
    callback_data = call.data or ""
    # Keep the reference case: Docker names are case-sensitive.
    container_name = _callback_field(callback_data, 1)
    called_user_id = _callback_field(callback_data, 2)

    if call.from_user is None:
        logger.warning(missing_user_event, callback_data=call.data)
        show_handler_info(
            call=call,
            text=f"{operation_label} {container_name}: Missing user information",
            bot=bot,
        )
        return None

    is_allowed, deny_reason = authorize_docker_callback_request(call, called_user_id)
    if not is_allowed:
        logger.warning(
            denied_event,
            user_id=call.from_user.id,
            container_name=container_name,
            reason=deny_reason,
        )
        show_handler_info(
            call=call,
            text=f"{operation_label} {container_name}: {deny_reason}",
            bot=bot,
        )
        return None

    return AuthorizedContainerCallbackContext(
        callback_data=callback_data,
        container_name=container_name,
        user_id=call.from_user.id,
    )


def get_manage_container_callback_context(
    call: CallbackQuery,
    bot: TeleBot,
    *,
    missing_user_event: str,
    denied_event: str,
) -> AuthorizedContainerCallbackContext | None:
    """Return authorized context for container management callbacks."""
    return get_authorized_container_callback_context(
        call=call,
        bot=bot,
        operation_label="Managing",
        missing_user_event=missing_user_event,
        denied_event=denied_event,
    )


def _as_dict(value: object) -> dict[str, object]:
    return as_object_dict(value)


def _to_float(value: object, default: float = 0.0) -> float:
    return to_float(value, default)


def _to_int(value: object, default: int = 0) -> int:
    return to_int(value, default, allow_float_string=True)


def _extract_container_attrs(container_details: object) -> dict[str, object]:
    """Normalize container input to attrs dictionary once."""
    attrs = getattr(container_details, "attrs", None)
    if isinstance(attrs, dict):
        return attrs

    if isinstance(container_details, dict) and "attrs" in container_details:
        attrs = container_details.get("attrs")
        return attrs if isinstance(attrs, dict) else {}

    if isinstance(container_details, dict):
        return container_details

    return {}


def get_container_full_details(container_name: str) -> object | None:
    """
    Retrieve the Docker container object by exact name or short/full ID.

    The reference is passed through unchanged (never lowercased) and the
    adapter verifies that dockerd resolved it to the intended container.

    Returns:
        object | None: Docker container object, or None if not found.

    Raises:
        InvalidContainerReferenceError: If the reference is invalid.
        DockerConnectionError: If Docker is unavailable.
    """
    return fetch_full_container_details(container_name)


@lru_cache(maxsize=1)
def get_emojis() -> dict[str, str]:
    """
    Return a dictionary of emojis with keys representing emoji names and values as emoji characters.
    """
    emoji_names = [
        "thought_balloon",
        "luggage",
        "minus",
        "backhand_index_pointing_down",
        "banjo",
        "basket",
        "flag_in_hole",
        "railway_car",
        "radio",
        "puzzle_piece",
        "radioactive",
        "safety_pin",
        "sandwich",
        "package",
        "gear",
        "chart_increasing",
        "globe_with_meridians",
        "herb",
        "spiral_calendar",
        "bullseye",
        "stethoscope",
        "shield",
        "warning",
        "BACK_arrow",
    ]
    return {emoji_name: em.get_emoji(emoji_name) for emoji_name in emoji_names}


def get_sanitized_logs(
    container_name: str, call: CallbackQuery, token: str
) -> str | None:
    """
    Retrieve sanitized logs for a specific container.

    Returns:
        Sanitized logs, or None if the container does not exist.

    Raises:
        DockerConnectionError: If Docker is unavailable.
    """
    raw_logs = fetch_container_logs(container_name)
    if raw_logs is None:
        return None
    return sanitize_logs(raw_logs, call, token)


def _truncate_env_entry(entry: str) -> str:
    key, separator, value = entry.partition("=")
    if separator and len(value) > MAX_ENV_VALUE_LENGTH:
        return f"{key}={value[: MAX_ENV_VALUE_LENGTH - 3]}..."
    return entry


def sanitize_environment_variables(env_list: list[str]) -> list[str]:
    """
    Show environment variables as keys only.

    Keeps the ``KEY=VALUE`` shape but masks every value except a small
    allowlist of harmless keys; URL credentials are masked everywhere.
    """
    if not env_list:
        return []
    masked = mask_environment_variables(env_list[:MAX_DISPLAYED_ENV_VARS])
    return [_truncate_env_entry(entry) for entry in masked]


@dataclass(frozen=True, slots=True)
class CommandArgumentsView:
    """Whether a Docker view shows command arguments, and the note saying so."""

    visible: bool
    note: str


# The view for anyone who may not see arguments in a private chat.
WITHOUT_COMMAND_ARGUMENTS: Final[CommandArgumentsView] = CommandArgumentsView(
    visible=False, note=COMMAND_ARGUMENTS_ADMINS_ONLY_NOTE
)


def command_arguments_view(call: CallbackQuery) -> CommandArgumentsView:
    """
    Decide whether the view opened by ``call`` shows command arguments.

    Arguments can hold secrets that masking does not recognize, so they are
    shown (masked) only to an admin in a private chat with the bot; 2FA is not
    required. In a group every member would read them, admins included. The
    admin is the verified presser (``call.from_user``), never a user id taken
    from callback data; the chat is the one of the message being edited.
    """
    if not is_private_chat(getattr(call.message, "chat", None)):
        return CommandArgumentsView(
            visible=False, note=COMMAND_ARGUMENTS_PRIVATE_CHAT_NOTE
        )
    if (
        call.from_user is None
        or call.from_user.id not in settings.access_control.allowed_admins_ids
    ):
        return WITHOUT_COMMAND_ARGUMENTS
    return CommandArgumentsView(visible=True, note=COMMAND_ARGUMENTS_MASKED_NOTE)


def executable_only(arguments: object) -> list[str]:
    """
    Reduce a masked argv (Cmd, Entrypoint, Shell) to its executable.

    A Cmd that only passes arguments to the Entrypoint has no executable of
    its own and is shown as ``hidden``.
    """
    if not isinstance(arguments, list) or not arguments:
        return []
    items = [str(item) for item in arguments]
    return [command_executable(items) or COMMAND_ARGUMENTS_HIDDEN_TEXT]


def command_line_executables(
    entrypoint: object, cmd: object
) -> tuple[list[str], list[str]]:
    """
    Reduce masked Entrypoint and Cmd to their executables.

    With an Entrypoint, Cmd holds only its arguments and is hidden entirely;
    without one, Cmd keeps its executable.
    """
    entrypoint_view = executable_only(entrypoint)
    cmd_view = executable_only(cmd)
    if entrypoint_view and cmd_view:
        cmd_view = [COMMAND_ARGUMENTS_HIDDEN_TEXT]
    return entrypoint_view, cmd_view


def hide_command_arguments(container_details: dict[str, object]) -> dict[str, object]:
    """Return container details with Entrypoint and Cmd reduced to executables."""
    environment = container_details.get("environment")
    if not isinstance(environment, dict):
        return container_details
    return {
        **container_details,
        "environment": {
            **environment,
            "entrypoint": environment.get("entrypoint_executable", "N/A"),
            "command": environment.get("command_executable", "N/A"),
        },
    }


def _format_container_timestamp(raw_value: object) -> str:
    """Render ISO timestamp from Docker attrs to stable UTC string."""
    if not isinstance(raw_value, str):
        return "N/A"

    value = raw_value.strip()
    if not value or value == "0001-01-01T00:00:00Z":
        return "N/A"

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "N/A"

    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _truncate_text(value: object, limit: int = 160) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _normalize_string_list(raw_value: object, *, limit: int = 10) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    cleaned = [str(item).strip() for item in raw_value if str(item).strip()]
    return cleaned[:limit]


def _extract_health_summary(state: dict[str, object]) -> dict[str, object]:
    """Extract health check summary from Docker state attrs."""
    health_data = _as_dict(state.get("Health", {}))
    if not health_data:
        return {
            "health_status": "N/A",
            "health_failing_streak": 0,
            "health_last_checked_at": "N/A",
            "health_last_log": "N/A",
        }

    health_log = health_data.get("Log", [])
    health_last_checked_at = "N/A"
    health_last_log = "N/A"

    if isinstance(health_log, list) and health_log:
        last_record = health_log[-1]
        if isinstance(last_record, dict):
            health_last_checked_at = _format_container_timestamp(last_record.get("End"))
            # Probe output can echo credentials (``password=...``).
            output = mask_free_text(str(last_record.get("Output", ""))).strip()
            if output:
                first_line = output.splitlines()[0]
                health_last_log = _truncate_text(first_line)

    return {
        "health_status": str(health_data.get("Status", "N/A")),
        "health_failing_streak": _to_int(health_data.get("FailingStreak", 0), 0),
        "health_last_checked_at": health_last_checked_at,
        "health_last_log": health_last_log,
    }


def _format_state_error(state: dict[str, object]) -> str:
    """``State.Error`` (often a failed exec with its command line), masked."""
    return _truncate_text(mask_free_text(str(state.get("Error") or "none")))


def _format_health_badge(status: object) -> str:
    normalized = str(status).strip().lower()
    if normalized == "healthy":
        return "🟢 healthy"
    if normalized == "unhealthy":
        return "🔴 unhealthy"
    if normalized == "starting":
        return "🟡 starting"
    return str(status).strip() or "N/A"


def _has_no_new_privileges(security_options: list[str]) -> bool:
    return any(
        option.lower().startswith("no-new-privileges") for option in security_options
    )


def resolve_container_status(state: dict[str, object]) -> str:
    """
    Return the lifecycle status from ``State.Status``.

    ``State.Running`` is also true for paused and restarting containers, so the
    boolean flags are only a fallback for payloads without ``Status``.
    """
    status = str(state.get("Status") or "").strip().lower()
    if status:
        return status
    for flag, flag_status in (
        ("Paused", "paused"),
        ("Restarting", "restarting"),
        ("Running", "running"),
    ):
        if state.get(flag):
            return flag_status
    return "unknown"


def split_image_reference(reference: str) -> tuple[str, str]:
    """
    Split ``[registry[:port]/]repository[:tag][@digest]`` into (name, tag).

    The tag is the part after the last ``:`` of the last path component, so a
    registry port is never mistaken for a tag.
    """
    name, _, digest = reference.strip().partition("@")
    tag_separator = name.rfind(":")
    if tag_separator > name.rfind("/"):
        return name[:tag_separator], name[tag_separator + 1 :]
    if digest:
        return name, digest[:19]
    return name or "unknown", "latest"


def parse_container_basic_info(
    container_details: object, attrs: dict[str, object] | None = None
) -> dict[str, object]:
    """
    Extract basic container information from container details.

    Args:
        container_details: Container object or dictionary

    Returns:
        Dict with basic container info
    """
    try:
        resolved_attrs = (
            attrs if attrs is not None else _extract_container_attrs(container_details)
        )

        config = _as_dict(resolved_attrs.get("Config", {}))
        state = _as_dict(resolved_attrs.get("State", {}))
        health_summary = _extract_health_summary(state)
        health_summary_public = {
            "health_status": health_summary.get("health_status", "N/A"),
            "health_failing_streak": health_summary.get("health_failing_streak", 0),
            "health_last_checked_at": health_summary.get(
                "health_last_checked_at", "N/A"
            ),
            "health_badge": _format_health_badge(
                health_summary.get("health_status", "N/A")
            ),
        }

        current_status = resolve_container_status(state)
        image_name, image_tag = split_image_reference(
            str(config.get("Image", "unknown"))
        )

        started_at_raw = state.get("StartedAt", "")
        started_at_dt = parse_docker_timestamp(started_at_raw)
        uptime = set_naturaltime(started_at_dt) if started_at_dt else "N/A"

        return {
            "id": str(resolved_attrs.get("Id", ""))[:12],  # Short ID
            "name": str(resolved_attrs.get("Name", "")).lstrip("/"),
            "image_name": image_name,
            "image_tag": image_tag,
            "status": state.get("Status", "unknown"),
            "status_badge": _STATUS_BADGES.get(current_status, "🔴 Stopped"),
            "running": current_status == "running",
            "paused": current_status == "paused",
            "restarting": current_status == "restarting",
            "restart_count": state.get("RestartCount", 0),
            "exit_code": state.get("ExitCode", 0),
            "created": _format_container_timestamp(resolved_attrs.get("Created")),
            "started_at": _format_container_timestamp(started_at_raw),
            "finished_at": _format_container_timestamp(state.get("FinishedAt")),
            "pid": state.get("Pid") or "N/A",
            "oom_killed": bool(state.get("OOMKilled", False)),
            "dead": bool(state.get("Dead", False)),
            "state_error": _format_state_error(state),
            "uptime": uptime,
            **health_summary_public,
        }
    except Exception:
        logger.error("bot.handler.handlers_util.docker.parsing.container.fail")
        return {}


def parse_container_resources(
    container_details: object, attrs: dict[str, object] | None = None
) -> dict[str, object]:
    """
    Extract container resource configuration and limits.

    Args:
        container_details: Container object or dictionary

    Returns:
        Dict with resource information
    """
    try:
        resolved_attrs = (
            attrs if attrs is not None else _extract_container_attrs(container_details)
        )

        host_config = _as_dict(resolved_attrs.get("HostConfig", {}))

        restart_policy = _as_dict(host_config.get("RestartPolicy", {}))

        # Memory limits
        memory_limit = _to_int(host_config.get("Memory", 0), 0)
        memory_swap = _to_int(host_config.get("MemorySwap", 0), 0)
        memory_reservation = _to_int(host_config.get("MemoryReservation", 0), 0)
        pids_limit = host_config.get("PidsLimit", 0)

        # CPU limits
        cpu_shares = _to_int(host_config.get("CpuShares", 0), 0)
        cpu_quota = _to_int(host_config.get("CpuQuota", 0), 0)
        cpu_period = _to_int(host_config.get("CpuPeriod", 0), 0)
        cpuset_cpus = str(host_config.get("CpusetCpus", ""))
        nano_cpus = _to_int(host_config.get("NanoCpus", 0), 0)

        pids_limit_display = "Unlimited"
        if isinstance(pids_limit, int) and pids_limit > 0:
            pids_limit_display = str(pids_limit)
        elif isinstance(pids_limit, str) and pids_limit.strip():
            pids_limit_display = pids_limit.strip()

        return {
            "memory_limit": set_naturalsize(memory_limit)
            if memory_limit > 0
            else "No limit",
            "memory_swap": set_naturalsize(memory_swap)
            if memory_swap > 0
            else "No limit",
            "memory_reservation": set_naturalsize(memory_reservation)
            if memory_reservation > 0
            else "No reservation",
            "cpu_shares": cpu_shares if cpu_shares > 0 else "Default (1024)",
            "cpu_quota": f"{cpu_quota}/{cpu_period}"
            if cpu_quota > 0 and cpu_period > 0
            else "No limit",
            "cpus_limit": f"{nano_cpus / 1_000_000_000:.2f}"
            if nano_cpus > 0
            else "No limit",
            "cpuset_cpus": cpuset_cpus if cpuset_cpus else "All CPUs",
            "restart_policy": str(restart_policy.get("Name", "no")),
            "max_restart_count": _to_int(restart_policy.get("MaximumRetryCount", 0), 0),
            "pids_limit": pids_limit_display,
        }
    except Exception:
        logger.error("bot.handler.handlers_util.docker.parsing.container.fail")
        return {}


def parse_container_network_info(
    container_details: object, attrs: dict[str, object] | None = None
) -> dict[str, object]:
    """
    Extract container network configuration (safe subset).

    Args:
        container_details: Container object or dictionary

    Returns:
        Dict with network information
    """
    try:
        resolved_attrs = (
            attrs if attrs is not None else _extract_container_attrs(container_details)
        )

        network_settings = _as_dict(resolved_attrs.get("NetworkSettings", {}))
        host_config = _as_dict(resolved_attrs.get("HostConfig", {}))

        # Port mappings (public info)
        port_bindings = network_settings.get("Ports", {})
        if not isinstance(port_bindings, dict):
            port_bindings = host_config.get("PortBindings", {})
        if not port_bindings:
            host_port_bindings = host_config.get("PortBindings", {})
            if isinstance(host_port_bindings, dict):
                port_bindings = host_port_bindings
        if not isinstance(port_bindings, dict):
            port_bindings = {}

        ports = []
        bound_ports = 0
        for container_port, host_bindings in port_bindings.items():
            if host_bindings:
                for binding in host_bindings:
                    if not isinstance(binding, dict):
                        continue
                    host_port = str(binding.get("HostPort", "auto"))
                    host_ip = str(binding.get("HostIp", "0.0.0.0"))
                    ports.append(f"{host_ip}:{host_port}->{container_port}")
                    bound_ports += 1
            else:
                ports.append(container_port)

        # Network mode
        network_mode = str(host_config.get("NetworkMode", "default"))

        # Connected networks (names only, not IPs for security)
        networks_data = _as_dict(network_settings.get("Networks", {}))
        networks = [str(name) for name in networks_data]

        return {
            "network_mode": network_mode,
            "ports": ports[:10],  # Limit display
            "networks": networks[:5],  # Limit display
            "published_ports": bound_ports,
            "declared_ports": len(ports),
            "networks_count": len(networks),
        }
    except Exception:
        logger.error("bot.handler.handlers_util.docker.parsing.container.fail")
        return {}


def parse_container_environment(
    container_details: object, attrs: dict[str, object] | None = None
) -> dict[str, object]:
    """
    Extract and sanitize container environment information.

    Args:
        attrs: details attributes
        container_details: Container object or dictionary

    Returns:
        Dict with environment information
    """
    try:
        resolved_attrs = (
            attrs if attrs is not None else _extract_container_attrs(container_details)
        )

        config = _as_dict(resolved_attrs.get("Config", {}))

        # Environment variables (sanitized)
        env_vars_obj = config.get("Env", [])
        env_vars = (
            [str(item) for item in env_vars_obj]
            if isinstance(env_vars_obj, list)
            else []
        )
        safe_env_vars = sanitize_environment_variables(env_vars)

        # Working directory
        working_dir = str(config.get("WorkingDir", "/"))

        # User
        user = str(config.get("User", "root"))

        # Command and args, masked; the executables serve non-admin views.
        cmd_obj = config.get("Cmd", [])
        cmd = cmd_obj if isinstance(cmd_obj, list) else []
        entrypoint_obj = config.get("Entrypoint", [])
        entrypoint = entrypoint_obj if isinstance(entrypoint_obj, list) else []
        masked_entrypoint, masked_cmd = mask_entrypoint_and_cmd(entrypoint, cmd)
        entrypoint_view, cmd_view = command_line_executables(
            masked_entrypoint, masked_cmd
        )

        return {
            "environment_vars": safe_env_vars,
            "working_dir": working_dir,
            "user": user,
            "command": " ".join(masked_cmd) or "N/A",
            "entrypoint": " ".join(masked_entrypoint) or "N/A",
            "command_executable": " ".join(cmd_view) or "N/A",
            "entrypoint_executable": " ".join(entrypoint_view) or "N/A",
            "env_count": len(env_vars),
        }
    except Exception:
        logger.error("bot.handler.handlers_util.docker.parsing.container.fail")
        return {}


def parse_container_runtime_info(
    container_details: object, attrs: dict[str, object] | None = None
) -> dict[str, object]:
    """Extract runtime lifecycle and security metadata for container views."""
    try:
        resolved_attrs = (
            attrs if attrs is not None else _extract_container_attrs(container_details)
        )
        state = _as_dict(resolved_attrs.get("State", {}))
        host_config = _as_dict(resolved_attrs.get("HostConfig", {}))
        config = _as_dict(resolved_attrs.get("Config", {}))

        security_opts = _normalize_string_list(host_config.get("SecurityOpt"), limit=8)
        cap_add = _normalize_string_list(host_config.get("CapAdd"), limit=10)
        cap_drop = _normalize_string_list(host_config.get("CapDrop"), limit=10)

        health_summary = _extract_health_summary(state)

        stop_timeout_value = host_config.get("StopTimeout")
        stop_timeout = (
            f"{stop_timeout_value}s"
            if isinstance(stop_timeout_value, int) and stop_timeout_value >= 0
            else "default"
        )

        return {
            "created_at": _format_container_timestamp(resolved_attrs.get("Created")),
            "started_at": _format_container_timestamp(state.get("StartedAt")),
            "finished_at": _format_container_timestamp(state.get("FinishedAt")),
            "pid": state.get("Pid") or "N/A",
            "exit_code": state.get("ExitCode", "N/A"),
            "state_error": _format_state_error(state),
            "oom_killed": bool(state.get("OOMKilled", False)),
            "dead": bool(state.get("Dead", False)),
            "privileged": bool(host_config.get("Privileged", False)),
            "read_only_rootfs": bool(host_config.get("ReadonlyRootfs", False)),
            "oom_kill_disable": bool(host_config.get("OomKillDisable", False)),
            "init_process": bool(host_config.get("Init", False)),
            "no_new_privileges": _has_no_new_privileges(security_opts),
            "stop_signal": str(config.get("StopSignal", "SIGTERM")),
            "stop_timeout": stop_timeout,
            "security_opts": security_opts,
            "cap_add": cap_add,
            "cap_drop": cap_drop,
            **health_summary,
            "health_badge": _format_health_badge(health_summary.get("health_status")),
        }
    except Exception:
        logger.error("bot.handler.handlers_util.docker.parsing.container.fail")
        return {}


def _is_running(container_details: object) -> bool:
    return str(getattr(container_details, "status", "")).lower() == "running"


def has_cpu_baseline(container_stats: dict[str, object]) -> bool:
    """Return True when the stats carry a previous CPU sample (``precpu_stats``)."""
    precpu_stats = _as_dict(container_stats.get("precpu_stats", {}))
    return _to_float(precpu_stats.get("system_cpu_usage", 0), 0.0) > 0


def collect_container_runtime_stats(container_details: object) -> dict[str, object]:
    """
    Collect a runtime stats sample suitable for CPU% calculation.

    One-shot stats have zeroed ``precpu_stats``; in that case a second sample is
    taken and the first sample's ``cpu_stats`` becomes the baseline.
    """
    first_sample = get_container_stats_snapshot(container_details)
    if not first_sample or has_cpu_baseline(first_sample):
        return first_sample

    time.sleep(CPU_SAMPLE_INTERVAL_SECONDS)
    second_sample = get_container_stats_snapshot(container_details)
    if not second_sample:
        return first_sample
    return {**second_sample, "precpu_stats": first_sample.get("cpu_stats", {})}


def _resolve_memory_stats(
    container_details: object, stats: dict[str, object]
) -> dict[str, str | float]:
    """Prefer the runtime memory sample, fall back to static/fast providers."""
    runtime_memory_stats = parse_container_memory_stats(stats) if stats else {}
    if runtime_memory_stats or not _is_running(container_details):
        return runtime_memory_stats
    try:
        return normalize_memory_stats(get_container_memory_stats(container_details))
    except Exception:
        # Memory figures are optional enrichment of the details view.
        logger.debug("bot.handler.handlers_util.docker.could_not.get.debug")
        return {}


def _format_memory_headroom(stats: dict[str, object]) -> str:
    memory_snapshot = _as_dict(stats.get("memory_stats", {}))
    usage = memory_snapshot.get("usage", 0)
    limit = memory_snapshot.get("limit", 0)
    if (
        not isinstance(usage, (int, float))
        or not isinstance(limit, (int, float))
        or limit <= 0
    ):
        return "N/A"
    remaining = max(int(limit - usage), 0)
    remaining_percent = round((remaining / limit) * 100, 2)
    return f"{set_naturalsize(remaining)} ({remaining_percent}%)"


def get_comprehensive_container_details(
    container_name: str,
) -> dict[str, object] | None:
    """
    Get comprehensive container details for the container info view.

    Args:
        container_name: Exact container name or short/full container ID.

    Returns:
        Dict with all container details, or None if the container is not found.

    Raises:
        InvalidContainerReferenceError: If the reference is invalid.
        DockerConnectionError: If Docker is unavailable (never reported as None).
    """
    container_details = get_container_full_details(container_name)
    if not container_details:
        return None

    attrs = _extract_container_attrs(container_details)
    stats = (
        collect_container_runtime_stats(container_details)
        if _is_running(container_details) and hasattr(container_details, "stats")
        else {}
    )
    resources = parse_container_resources(container_details, attrs=attrs)
    resources["memory_headroom"] = _format_memory_headroom(stats)

    return {
        **parse_container_basic_info(container_details, attrs=attrs),
        "resources": resources,
        "network": parse_container_network_info(container_details, attrs=attrs),
        "environment": parse_container_environment(container_details, attrs=attrs),
        "runtime": parse_container_runtime_info(container_details, attrs=attrs),
        "stats": {
            "memory": _resolve_memory_stats(container_details, stats),
            "cpu": parse_container_cpu_stats(stats) if stats else {},
            "network": parse_container_network_stats(stats) if stats else {},
        },
    }


def normalize_memory_stats(
    raw_memory_stats: dict[str, object] | dict[str, str],
) -> dict[str, str | float]:
    """Normalize memory stats to template-compatible values."""
    if not raw_memory_stats:
        return {}

    mem_percent = raw_memory_stats.get("mem_percent", "N/A")
    if isinstance(mem_percent, str):
        mem_percent = mem_percent.strip()
        if mem_percent.endswith("%"):
            mem_percent = mem_percent[:-1].strip()
        if mem_percent.upper() != "N/A":
            try:
                mem_percent = float(mem_percent)
            except ValueError:
                mem_percent = "N/A"
    elif isinstance(mem_percent, (int, float)):
        mem_percent = round(float(mem_percent), 2)
    else:
        mem_percent = "N/A"

    return {
        "mem_usage": str(raw_memory_stats.get("mem_usage", "N/A")),
        "mem_limit": str(raw_memory_stats.get("mem_limit", "N/A")),
        "mem_percent": mem_percent,
    }


def parse_container_memory_stats(
    container_stats: dict[str, object],
) -> dict[str, str | float]:
    """
    Parse the memory statistics of a container with enhanced formatting.

    Args:
        container_stats (Dict): The dictionary containing memory statistics of a container.

    Returns:
        Dict: A dictionary with keys for 'mem_usage', 'mem_limit', and 'mem_percent'.
    """
    try:
        # Retrieve the memory statistics from the container_stats dictionary
        memory_stats = _as_dict(container_stats.get("memory_stats", {}))

        # Calculate the memory usage and limit
        usage = _to_int(memory_stats.get("usage", 0), 0)
        limit = _to_int(memory_stats.get("limit", 0), 0)

        if usage == 0 and limit == 0:
            return {}

        # Use enhanced formatting for better readability
        mem_usage = set_naturalsize(usage)
        mem_limit = set_naturalsize(limit)

        # Calculate the percentage of memory used by the container
        mem_percent = round(usage / limit * 100, 2) if limit > 0 else 0

        return {
            "mem_usage": mem_usage,
            "mem_limit": mem_limit,
            "mem_percent": mem_percent,
        }
    except Exception:
        logger.debug("bot.handler.handlers_util.docker.parsing.memory.fail")
        return {}


def _online_cpu_count(cpu_stats: dict[str, object]) -> int:
    """CPU count as the Docker CLI does: online_cpus, else len(percpu_usage)."""
    online_cpus = _to_int(cpu_stats.get("online_cpus", 0), 0)
    if online_cpus > 0:
        return online_cpus
    # percpu_usage is absent on cgroup v2.
    percpu_usage = _as_dict(cpu_stats.get("cpu_usage", {})).get("percpu_usage")
    if isinstance(percpu_usage, list) and percpu_usage:
        return len(percpu_usage)
    return 1


def calculate_cpu_percent(
    cpu_stats: dict[str, object], precpu_stats: dict[str, object]
) -> float:
    """
    CPU% between two samples, normalized like ``docker stats``.

    Returns 0.0 when there is no previous sample (one-shot stats report a
    zeroed ``precpu_stats``; dividing absolute counters would yield the
    since-boot average instead of the current load).
    """
    cpu_total = _to_float(_as_dict(cpu_stats.get("cpu_usage", {})).get("total_usage"))
    precpu_total = _to_float(
        _as_dict(precpu_stats.get("cpu_usage", {})).get("total_usage")
    )
    system_cpu = _to_float(cpu_stats.get("system_cpu_usage", 0), 0.0)
    pre_system_cpu = _to_float(precpu_stats.get("system_cpu_usage", 0), 0.0)

    system_delta = system_cpu - pre_system_cpu
    cpu_delta = cpu_total - precpu_total
    if pre_system_cpu <= 0 or system_delta <= 0 or cpu_delta <= 0:
        return 0.0
    return round(cpu_delta / system_delta * _online_cpu_count(cpu_stats) * 100.0, 2)


def parse_container_cpu_stats(
    container_stats: dict[str, object],
) -> dict[str, int | float]:
    """
    Parse the CPU statistics of a container.

    Args:
        container_stats: Stats with ``cpu_stats`` and ``precpu_stats`` samples.

    Returns:
        Dict: CPU usage percentage and throttling counters.
    """
    cpu_stats = _as_dict(container_stats.get("cpu_stats", {}))
    throttling_data = _as_dict(cpu_stats.get("throttling_data", {}))
    return {
        "periods": _to_int(throttling_data.get("periods", 0), 0),
        "throttled_periods": _to_int(throttling_data.get("throttled_periods", 0), 0),
        "throttling_data": _to_int(throttling_data.get("throttled_time", 0), 0),
        "cpu_percent": calculate_cpu_percent(
            cpu_stats, _as_dict(container_stats.get("precpu_stats", {}))
        ),
    }


def parse_container_network_stats(
    container_stats: dict[str, object],
) -> dict[str, int | str]:
    """
    Parse the network statistics of a container with enhanced formatting.

    Args:
        container_stats (Dict): The dictionary containing network statistics of a container.

    Returns:
        Dict: A dictionary with network statistics.
    """
    try:
        networks_raw = container_stats.get("networks", {})
        if isinstance(networks_raw, dict):
            networks = [
                net_info
                for net_info in networks_raw.values()
                if isinstance(net_info, dict)
            ]
        else:
            networks = []

        # Sum all network interfaces
        total_rx_bytes = sum(int(net.get("rx_bytes", 0) or 0) for net in networks)
        total_tx_bytes = sum(int(net.get("tx_bytes", 0) or 0) for net in networks)
        total_rx_dropped = sum(int(net.get("rx_dropped", 0) or 0) for net in networks)
        total_tx_dropped = sum(int(net.get("tx_dropped", 0) or 0) for net in networks)
        total_rx_errors = sum(int(net.get("rx_errors", 0) or 0) for net in networks)
        total_tx_errors = sum(int(net.get("tx_errors", 0) or 0) for net in networks)

        return {
            "rx_bytes": set_naturalsize(total_rx_bytes),
            "tx_bytes": set_naturalsize(total_tx_bytes),
            "rx_dropped": total_rx_dropped,
            "tx_dropped": total_tx_dropped,
            "rx_errors": total_rx_errors,
            "tx_errors": total_tx_errors,
        }
    except Exception:
        logger.error("bot.handler.handlers_util.docker.parsing.network.fail")
        zero_size = set_naturalsize(0)
        return {
            "rx_bytes": zero_size,
            "tx_bytes": zero_size,
            "rx_dropped": 0,
            "tx_dropped": 0,
            "rx_errors": 0,
            "tx_errors": 0,
        }
