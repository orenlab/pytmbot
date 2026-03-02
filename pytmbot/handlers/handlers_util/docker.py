#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import re
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
    get_container_memory_stats,
    get_container_stats_snapshot,
)
from pytmbot.globals import get_emoji_converter
from pytmbot.handlers.handlers_util.callback_auth import authorize_callback_request
from pytmbot.logs import Logger
from pytmbot.settings import CONTAINER_NAME_PATTERN, MAX_CONTAINER_NAME_LENGTH
from pytmbot.utils import (
    as_object_dict,
    sanitize_logs,
    set_naturalsize,
    set_naturaltime,
    split_string_into_octets,
    to_float,
    to_int,
)

logger = Logger()
em = get_emoji_converter()

_SENSITIVE_ENV_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*key.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*auth.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*api.*key.*", re.IGNORECASE),
    re.compile(r".*database.*url.*", re.IGNORECASE),
    re.compile(r".*db.*password.*", re.IGNORECASE),
    re.compile(r".*private.*", re.IGNORECASE),
    re.compile(r".*ssl.*cert.*", re.IGNORECASE),
    re.compile(r".*ssl.*key.*", re.IGNORECASE),
    re.compile(r".*jwt.*", re.IGNORECASE),
)


def validate_container_name(name: str) -> bool:
    """Validate container name for callback-driven operations."""
    if not name or not isinstance(name, str):
        return False

    if len(name) > MAX_CONTAINER_NAME_LENGTH:
        return False

    if not CONTAINER_NAME_PATTERN.match(name):
        return False

    dangerous_patterns = [
        "..",
        "/",
        "\\",
        "$",
        "`",
        ";",
        "|",
        "&",
        "\n",
        "\r",
        "\t",
        "\0",
    ]

    return not any(pattern in name for pattern in dangerous_patterns)


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
        callback_query_id=call.id, text=text, show_alert=True
    )


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
    container_name = split_string_into_octets(callback_data)
    called_user_id = split_string_into_octets(callback_data, octet_index=2)

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
    Retrieve the full details of a container.

    Args:
        container_name (str): The name of the container.

    Returns:
        object | None: Docker container object or None.
    """
    # Use a local variable to store the lowercased container name
    lower_container_name = container_name.lower()
    container_details = fetch_full_container_details(lower_container_name)
    return container_details


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


def get_sanitized_logs(container_name: str, call: CallbackQuery, token: str) -> str:
    """
    Retrieve sanitized logs for a specific container.

    Args:
        container_name (str): The name of the container.
        call (CallbackQuery): The callback query object.
        token (str): The bot token.

    Returns:
        str: Sanitized logs for the container.
    """
    # Fetch raw logs for the container
    raw_logs = fetch_container_logs(container_name)
    # Sanitize the logs for privacy
    sanitized_logs = sanitize_logs(raw_logs, call, token)
    return sanitized_logs


def sanitize_environment_variables(env_list: list[str]) -> list[str]:
    """
    Filter out sensitive environment variables for display.

    Args:
        env_list: List of environment variables in "KEY=VALUE" format

    Returns:
        List[str]: Filtered environment variables
    """
    if not env_list:
        return []

    filtered_vars = []
    for var in env_list:
        var_name = var.split("=", 1)[0] if "=" in var else var

        # Check if variable name matches any sensitive pattern
        is_sensitive = any(
            pattern.match(var_name) for pattern in _SENSITIVE_ENV_PATTERNS
        )

        if is_sensitive:
            filtered_vars.append(f"{var_name}=<HIDDEN>")
        else:
            # Limit value length for display
            if "=" in var:
                key, value = var.split("=", 1)
                if len(value) > 100:
                    value = value[:97] + "..."
                filtered_vars.append(f"{key}={value}")
            else:
                filtered_vars.append(var)

    return filtered_vars[:20]  # Limit to first 20 variables


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
            output = str(last_record.get("Output", "")).strip()
            if output:
                first_line = output.splitlines()[0]
                health_last_log = _truncate_text(first_line)

    return {
        "health_status": str(health_data.get("Status", "N/A")),
        "health_failing_streak": _to_int(health_data.get("FailingStreak", 0), 0),
        "health_last_checked_at": health_last_checked_at,
        "health_last_log": health_last_log,
    }


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

        running = bool(state.get("Running", False))
        paused = bool(state.get("Paused", False))
        restarting = bool(state.get("Restarting", False))

        # Image info (safe to display)
        image_info = str(config.get("Image", "unknown"))
        image_parts = image_info.split(":")
        image_name = image_parts[0] if image_parts else "unknown"
        image_tag = image_parts[1] if len(image_parts) > 1 else "latest"

        # Calculate uptime
        started_at_raw = state.get("StartedAt", "")
        uptime = "N/A"
        if isinstance(started_at_raw, str) and started_at_raw:
            try:
                if started_at_raw != "0001-01-01T00:00:00Z":
                    started_at_dt = datetime.fromisoformat(
                        started_at_raw.replace("Z", "+00:00")
                    )
                    uptime = set_naturaltime(started_at_dt)
            except ValueError:
                uptime = "N/A"

        return {
            "id": str(resolved_attrs.get("Id", ""))[:12],  # Short ID
            "name": str(resolved_attrs.get("Name", "")).lstrip("/"),
            "image_name": image_name,
            "image_tag": image_tag,
            "status": state.get("Status", "unknown"),
            "status_badge": (
                "🟢 Running"
                if running
                else "🟡 Paused"
                if paused
                else "🔄 Restarting"
                if restarting
                else "🔴 Stopped"
            ),
            "running": running,
            "paused": paused,
            "restarting": restarting,
            "restart_count": state.get("RestartCount", 0),
            "exit_code": state.get("ExitCode", 0),
            "created": _format_container_timestamp(resolved_attrs.get("Created")),
            "started_at": _format_container_timestamp(started_at_raw),
            "finished_at": _format_container_timestamp(state.get("FinishedAt")),
            "pid": state.get("Pid") or "N/A",
            "oom_killed": bool(state.get("OOMKilled", False)),
            "dead": bool(state.get("Dead", False)),
            "state_error": _truncate_text(state.get("Error", "none") or "none"),
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

        # Command and args (safe to display)
        cmd_obj = config.get("Cmd", [])
        cmd = [str(item) for item in cmd_obj] if isinstance(cmd_obj, list) else []
        entrypoint_obj = config.get("Entrypoint", [])
        entrypoint = (
            [str(item) for item in entrypoint_obj]
            if isinstance(entrypoint_obj, list)
            else []
        )

        return {
            "environment_vars": safe_env_vars,
            "working_dir": working_dir,
            "user": user,
            "command": " ".join(cmd) if cmd else "N/A",
            "entrypoint": " ".join(entrypoint) if entrypoint else "N/A",
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
            "state_error": _truncate_text(state.get("Error", "none") or "none"),
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


def get_comprehensive_container_details(
    container_name: str,
) -> dict[str, object] | None:
    """
    Get comprehensive container details with enhanced parsing and security.

    This function now handles both the improved data structure from containers_info
    and maintains compatibility with existing handler expectations.

    Args:
        container_name: Name of the container

    Returns:
        Dict with all container details or None if container not found
    """
    try:
        # Get raw container details (this returns the actual Container object)
        container_details = get_container_full_details(container_name)

        if not container_details:
            return None

        attrs = _extract_container_attrs(container_details)

        # Parse different aspects of container data
        basic_info = parse_container_basic_info(container_details, attrs=attrs)
        resources = parse_container_resources(container_details, attrs=attrs)
        network_info = parse_container_network_info(container_details, attrs=attrs)
        environment = parse_container_environment(container_details, attrs=attrs)
        runtime_info = parse_container_runtime_info(container_details, attrs=attrs)

        # Initialize runtime/stat fields
        stats: dict[str, object] = {}
        memory_stats: dict[str, str | float] = {}
        is_running = (
            hasattr(container_details, "status")
            and str(container_details.status).lower() == "running"
        )

        # Handle stats for Container object
        if hasattr(container_details, "stats") and is_running:
            try:
                # Request a single-shot runtime sample (faster than default stats mode)
                stats = get_container_stats_snapshot(container_details)
            except Exception:
                logger.warning("bot.handler.handlers_util.docker.could_not.get.warn")
                stats = {}

        # Prefer runtime memory snapshot when available, fallback to static/fast providers.
        runtime_memory_stats = parse_container_memory_stats(stats) if stats else {}
        if runtime_memory_stats:
            memory_stats = runtime_memory_stats
        elif is_running:
            try:
                memory_stats = normalize_memory_stats(
                    get_container_memory_stats(container_details)
                )
            except Exception:
                logger.debug("bot.handler.handlers_util.docker.could_not.get.debug")

        cpu_stats = parse_container_cpu_stats(stats) if stats else {}
        network_stats = parse_container_network_stats(stats) if stats else {}
        memory_headroom = "N/A"
        if stats:
            memory_snapshot = stats.get("memory_stats", {})
            if isinstance(memory_snapshot, dict):
                usage = memory_snapshot.get("usage", 0)
                limit = memory_snapshot.get("limit", 0)
                if (
                    isinstance(usage, (int, float))
                    and isinstance(limit, (int, float))
                    and limit > 0
                ):
                    remaining = max(int(limit - usage), 0)
                    remaining_percent = round((remaining / limit) * 100, 2)
                    memory_headroom = (
                        f"{set_naturalsize(remaining)} ({remaining_percent}%)"
                    )
        resources["memory_headroom"] = memory_headroom

        # Combine all data
        comprehensive_details = {
            **basic_info,
            "resources": resources,
            "network": network_info,
            "environment": environment,
            "runtime": runtime_info,
            "stats": {
                "memory": memory_stats,
                "cpu": cpu_stats,
                "network": network_stats,
            },
        }

        return comprehensive_details

    except Exception:
        logger.error("bot.handler.handlers_util.docker.getting.comprehensive.fail")
        return None


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


def parse_container_cpu_stats(
    container_stats: dict[str, object],
) -> dict[str, int | float]:
    """
    Parse the CPU statistics of a container with enhanced calculations.

    Args:
        container_stats: The dictionary containing CPU statistics of a container.

    Returns:
        Dict: A dictionary with CPU usage statistics.
    """
    try:
        cpu_stats = _as_dict(container_stats.get("cpu_stats", {}))
        precpu_stats = _as_dict(container_stats.get("precpu_stats", {}))

        # Get throttling data
        throttling_data = _as_dict(cpu_stats.get("throttling_data", {}))

        # Calculate CPU percentage
        cpu_usage = _as_dict(cpu_stats.get("cpu_usage", {}))
        precpu_usage = _as_dict(precpu_stats.get("cpu_usage", {}))

        cpu_total = _to_float(cpu_usage.get("total_usage", 0), 0.0)
        precpu_total = _to_float(precpu_usage.get("total_usage", 0), 0.0)

        system_cpu = _to_float(cpu_stats.get("system_cpu_usage", 0), 0.0)
        pre_system_cpu = _to_float(precpu_stats.get("system_cpu_usage", 0), 0.0)

        cpu_percent = 0.0
        if system_cpu > pre_system_cpu and cpu_total > precpu_total:
            cpu_delta = cpu_total - precpu_total
            system_delta = system_cpu - pre_system_cpu
            percpu_usage = cpu_usage.get("percpu_usage", [1])
            num_cpus = len(percpu_usage) if isinstance(percpu_usage, list) else 1
            if num_cpus < 1:
                num_cpus = 1
            cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0

        return {
            "periods": _to_int(throttling_data.get("periods", 0), 0),
            "throttled_periods": _to_int(
                throttling_data.get("throttled_periods", 0), 0
            ),
            "throttling_data": _to_int(throttling_data.get("throttled_time", 0), 0),
            "cpu_percent": round(cpu_percent, 2),
        }
    except Exception:
        logger.error("bot.handler.handlers_util.docker.parsing.cpu.fail")
        return {
            "periods": 0,
            "throttled_periods": 0,
            "throttling_data": 0,
            "cpu_percent": 0.0,
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
