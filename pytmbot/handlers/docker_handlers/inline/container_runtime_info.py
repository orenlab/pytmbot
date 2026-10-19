#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.adapters.docker.containers_info import fetch_full_container_details
from pytmbot.exceptions import (
    DockerConnectionError,
    DockerOperationException,
    InvalidContainerReferenceError,
)
from pytmbot.globals import ButtonDataType, get_keyboards
from pytmbot.handlers.docker_handlers.callback_data import (
    CONTAINER_EXTRA_CALLBACK_PREFIX,
    container_short_id,
    is_valid_container_ref,
    parse_callback_user_id,
)
from pytmbot.handlers.docker_handlers.pagination import (
    build_container_full_info_callback_data,
)
from pytmbot.handlers.docker_handlers.user_messages import (
    CONTAINER_NOT_FOUND_TEXT,
    DOCKER_REQUEST_FAILED_TEXT,
    DOCKER_UNAVAILABLE_TEXT,
    INVALID_CONTAINER_REF_TEXT,
)
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    get_emojis,
    parse_container_runtime_info,
    show_handler_info,
    validate_container_name,
)
from pytmbot.handlers.handlers_util.rich_messages import build_rich_html_message
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import as_object_dict, to_int

logger = Logger()
button_data = ButtonDataType
keyboards = get_keyboards()

__all__ = ["CONTAINER_EXTRA_CALLBACK_PREFIX", "handle_container_extra_info"]

CONTAINER_EXTRA_ACTION_VOLUMES: Final[str] = "volumes"
CONTAINER_EXTRA_ACTION_NETWORKS: Final[str] = "networks"
CONTAINER_EXTRA_ACTION_RUNTIME: Final[str] = "runtime"
_MAX_RENDER_ITEMS: Final[int] = 20
_MAX_ALIAS_ITEMS: Final[int] = 8


@dataclass(frozen=True, slots=True)
class ParsedContainerExtraCallback:
    action: str
    container_ref: str
    user_id: int


def parse_container_extra_callback_data(
    callback_data: str | None,
) -> ParsedContainerExtraCallback:
    """Parse callback payload in format '__container_extra__:<action>:<ref>:<user_id>'.

    ``<ref>`` is the short container ID (names from older buttons are accepted
    as-is and resolved exactly; they are never case-folded).
    """
    if callback_data is None:
        raise ValueError("Missing callback payload")

    parts = callback_data.split(":")
    if len(parts) != 4 or parts[0] != CONTAINER_EXTRA_CALLBACK_PREFIX:
        raise ValueError("Invalid callback format")

    action = parts[1].strip().lower()
    if action not in (
        CONTAINER_EXTRA_ACTION_VOLUMES,
        CONTAINER_EXTRA_ACTION_NETWORKS,
        CONTAINER_EXTRA_ACTION_RUNTIME,
    ):
        raise ValueError("Unsupported container extra action")

    container_ref = parts[2]
    if not is_valid_container_ref(container_ref):
        raise ValueError("Invalid container reference")

    user_id = parse_callback_user_id(parts[3])
    if user_id is None:
        raise ValueError("Invalid callback user id")

    return ParsedContainerExtraCallback(
        action=action,
        container_ref=container_ref,
        user_id=user_id,
    )


def _safe_text(value: object, default: str = "N/A") -> str:
    """Normalize arbitrary value to one line of plain text.

    HTML escaping is left to the templates (autoescape plus ``|e``); escaping
    here as well showed users ``&amp;`` instead of ``&``.
    """
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text.replace("\n", " ").replace("\r", " ")


def _safe_bool(value: object) -> str:
    if value is None:
        return "N/A"
    return "yes" if bool(value) else "no"


def _safe_int(value: object, default: int = 0) -> int:
    return to_int(value, default)


def _dict_of_objects(value: object) -> dict[str, object]:
    return as_object_dict(value)


def _limited_strings(
    raw: object, *, limit: int = _MAX_RENDER_ITEMS
) -> tuple[list[str], int]:
    if isinstance(raw, dict):
        values = list(raw.keys())
    elif isinstance(raw, list):
        values = raw
    else:
        return [], 0

    cleaned = [_safe_text(item) for item in values if str(item).strip()]
    limited = cleaned[:limit]
    hidden = max(0, len(cleaned) - len(limited))
    return limited, hidden


def _short_identifier(value: object) -> str:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        return "-"
    return _safe_text(raw[:12], default="-")


def _collect_limited_entries(
    values: dict[str, object],
) -> dict[str, dict[str, object]]:
    collected: dict[str, dict[str, object]] = {}
    for name, raw in values.items():
        items, hidden = _limited_strings(raw)
        collected[name] = {
            "items": items,
            "count": len(items),
            "hidden": hidden,
        }
    return collected


def _extract_container_attrs(container_details: object) -> dict[str, object]:
    attrs = getattr(container_details, "attrs", None)
    return attrs if isinstance(attrs, dict) else {}


def _extract_volume_context(attrs: dict[str, object]) -> dict[str, object]:
    config = _dict_of_objects(attrs.get("Config"))
    host_config = _dict_of_objects(attrs.get("HostConfig"))

    mounts_raw = attrs.get("Mounts", [])
    parsed_mounts: list[dict[str, str]] = []
    mounts_total = len(mounts_raw) if isinstance(mounts_raw, list) else 0

    if isinstance(mounts_raw, list):
        for mount in mounts_raw[:_MAX_RENDER_ITEMS]:
            mount_data = _dict_of_objects(mount)
            if not mount_data:
                continue
            rw_flag = mount_data.get("RW")
            access = "rw" if rw_flag is True else "ro" if rw_flag is False else "n/a"
            parsed_mounts.append(
                {
                    "type": _safe_text(mount_data.get("Type"), default="bind"),
                    "name": _safe_text(mount_data.get("Name"), default="-"),
                    "source": _safe_text(mount_data.get("Source")),
                    "destination": _safe_text(mount_data.get("Destination")),
                    "driver": _safe_text(mount_data.get("Driver"), default="-"),
                    "mode": _safe_text(mount_data.get("Mode"), default="-"),
                    "access": access,
                    "propagation": _safe_text(
                        mount_data.get("Propagation"),
                        default="-",
                    ),
                }
            )

    volume_lists = _collect_limited_entries(
        {
            "declared_volumes": config.get("Volumes", {}),
            "tmpfs_mounts": host_config.get("Tmpfs"),
            "bind_specs": host_config.get("Binds"),
            "volumes_from": host_config.get("VolumesFrom"),
        }
    )

    return {
        "mounts": parsed_mounts,
        "mounts_count": len(parsed_mounts),
        "mounts_total": mounts_total,
        "hidden_mounts_count": max(0, mounts_total - len(parsed_mounts)),
        "declared_volumes": volume_lists["declared_volumes"]["items"],
        "declared_volumes_count": volume_lists["declared_volumes"]["count"],
        "hidden_declared_volumes_count": volume_lists["declared_volumes"]["hidden"],
        "tmpfs_mounts": volume_lists["tmpfs_mounts"]["items"],
        "tmpfs_mounts_count": volume_lists["tmpfs_mounts"]["count"],
        "hidden_tmpfs_mounts_count": volume_lists["tmpfs_mounts"]["hidden"],
        "bind_specs": volume_lists["bind_specs"]["items"],
        "bind_specs_count": volume_lists["bind_specs"]["count"],
        "hidden_bind_specs_count": volume_lists["bind_specs"]["hidden"],
        "volumes_from": volume_lists["volumes_from"]["items"],
        "volumes_from_count": volume_lists["volumes_from"]["count"],
        "hidden_volumes_from_count": volume_lists["volumes_from"]["hidden"],
    }


def _extract_network_context(attrs: dict[str, object]) -> dict[str, object]:
    host_config = _dict_of_objects(attrs.get("HostConfig"))
    network_settings = _dict_of_objects(attrs.get("NetworkSettings"))
    config = _dict_of_objects(attrs.get("Config"))

    ports_raw = network_settings.get("Ports", {})
    port_rows: list[dict[str, object]] = []
    if isinstance(ports_raw, dict):
        for container_port, bindings in list(ports_raw.items())[:_MAX_RENDER_ITEMS]:
            port_label = _safe_text(container_port)
            host_bindings: list[str] = []
            if isinstance(bindings, list):
                for binding in bindings[:_MAX_ALIAS_ITEMS]:
                    binding_data = _dict_of_objects(binding)
                    if not binding_data:
                        continue
                    host_ip = _safe_text(binding_data.get("HostIp"), default="0.0.0.0")
                    host_port = _safe_text(binding_data.get("HostPort"))
                    host_bindings.append(f"{host_ip}:{host_port}")
            port_rows.append(
                {
                    "container_port": port_label,
                    "host_bindings": host_bindings,
                    "is_published": bool(host_bindings),
                }
            )

    network_lists = _collect_limited_entries(
        {
            "exposed_ports": config.get("ExposedPorts", {}),
            "dns_servers": host_config.get("Dns"),
            "dns_search": host_config.get("DnsSearch"),
            "dns_options": host_config.get("DnsOptions"),
            "extra_hosts": host_config.get("ExtraHosts"),
            "links": host_config.get("Links"),
        }
    )

    network_rows: list[dict[str, object]] = []
    networks_raw = network_settings.get("Networks", {})
    if isinstance(networks_raw, dict):
        for network_name, config_data in list(networks_raw.items())[:_MAX_RENDER_ITEMS]:
            cfg = _dict_of_objects(config_data)
            aliases_raw = cfg.get("Aliases", [])
            aliases = (
                [
                    _safe_text(alias)
                    for alias in aliases_raw[:_MAX_ALIAS_ITEMS]
                    if isinstance(alias, str) and alias.strip()
                ]
                if isinstance(aliases_raw, list)
                else []
            )
            hidden_aliases_count = (
                max(0, len(aliases_raw) - len(aliases))
                if isinstance(aliases_raw, list)
                else 0
            )
            network_rows.append(
                {
                    "name": _safe_text(network_name),
                    "ip_address": _safe_text(cfg.get("IPAddress")),
                    "ip_prefix_len": _safe_text(cfg.get("IPPrefixLen")),
                    "global_ipv6_address": _safe_text(cfg.get("GlobalIPv6Address")),
                    "global_ipv6_prefix_len": _safe_text(
                        cfg.get("GlobalIPv6PrefixLen")
                    ),
                    "gateway": _safe_text(cfg.get("Gateway")),
                    "ipv6_gateway": _safe_text(cfg.get("IPv6Gateway")),
                    "mac_address": _safe_text(cfg.get("MacAddress")),
                    "endpoint_id": _short_identifier(cfg.get("EndpointID")),
                    "network_id": _short_identifier(cfg.get("NetworkID")),
                    "aliases": aliases,
                    "hidden_aliases_count": hidden_aliases_count,
                }
            )

    hidden_ports_count = (
        max(0, len(ports_raw) - len(port_rows)) if isinstance(ports_raw, dict) else 0
    )
    hidden_networks_count = (
        max(0, len(networks_raw) - len(network_rows))
        if isinstance(networks_raw, dict)
        else 0
    )
    sandbox_id_short = _short_identifier(network_settings.get("SandboxID"))
    global_ipv6_address = str(network_settings.get("GlobalIPv6Address") or "").strip()

    return {
        "network_mode": _safe_text(host_config.get("NetworkMode"), default="default"),
        "hostname": _safe_text(config.get("Hostname"), default="-"),
        "domainname": _safe_text(config.get("Domainname"), default="-"),
        "sandbox_id": sandbox_id_short,
        "bridge_name": _safe_text(network_settings.get("Bridge"), default="-"),
        "publish_all_ports": _safe_bool(host_config.get("PublishAllPorts")),
        "enable_ipv6": _safe_bool(bool(global_ipv6_address)),
        "ports": port_rows,
        "ports_count": len(port_rows),
        "hidden_ports_count": hidden_ports_count,
        "exposed_ports": network_lists["exposed_ports"]["items"],
        "exposed_ports_count": network_lists["exposed_ports"]["count"],
        "hidden_exposed_ports_count": network_lists["exposed_ports"]["hidden"],
        "dns_servers": network_lists["dns_servers"]["items"],
        "dns_servers_count": network_lists["dns_servers"]["count"],
        "hidden_dns_servers_count": network_lists["dns_servers"]["hidden"],
        "dns_search": network_lists["dns_search"]["items"],
        "dns_search_count": network_lists["dns_search"]["count"],
        "hidden_dns_search_count": network_lists["dns_search"]["hidden"],
        "dns_options": network_lists["dns_options"]["items"],
        "dns_options_count": network_lists["dns_options"]["count"],
        "hidden_dns_options_count": network_lists["dns_options"]["hidden"],
        "extra_hosts": network_lists["extra_hosts"]["items"],
        "extra_hosts_count": network_lists["extra_hosts"]["count"],
        "hidden_extra_hosts_count": network_lists["extra_hosts"]["hidden"],
        "links": network_lists["links"]["items"],
        "links_count": network_lists["links"]["count"],
        "hidden_links_count": network_lists["links"]["hidden"],
        "networks": network_rows,
        "networks_count": len(network_rows),
        "hidden_networks_count": hidden_networks_count,
    }


def _extract_runtime_context(attrs: dict[str, object]) -> dict[str, object]:
    raw_runtime = parse_container_runtime_info(attrs)
    security_opts, hidden_security_opts_count = _limited_strings(
        raw_runtime.get("security_opts")
    )
    cap_add, hidden_cap_add_count = _limited_strings(raw_runtime.get("cap_add"))
    cap_drop, hidden_cap_drop_count = _limited_strings(raw_runtime.get("cap_drop"))
    cap_add_text = "none"
    if cap_add:
        cap_add_text = ", ".join(cap_add)
        if hidden_cap_add_count > 0:
            cap_add_text = f"{cap_add_text} (+{hidden_cap_add_count} more)"

    cap_drop_text = "none"
    if cap_drop:
        cap_drop_text = ", ".join(cap_drop)
        if hidden_cap_drop_count > 0:
            cap_drop_text = f"{cap_drop_text} (+{hidden_cap_drop_count} more)"

    return {
        "created_at": _safe_text(raw_runtime.get("created_at")),
        "started_at": _safe_text(raw_runtime.get("started_at")),
        "finished_at": _safe_text(raw_runtime.get("finished_at")),
        "health_status": _safe_text(raw_runtime.get("health_status")),
        "health_badge": _safe_text(raw_runtime.get("health_badge")),
        "health_failing_streak": _safe_int(
            raw_runtime.get("health_failing_streak", 0), 0
        ),
        "health_last_checked_at": _safe_text(raw_runtime.get("health_last_checked_at")),
        "health_last_log": _safe_text(raw_runtime.get("health_last_log")),
        "pid": _safe_text(raw_runtime.get("pid"), default="-"),
        "exit_code": _safe_text(raw_runtime.get("exit_code"), default="-"),
        "state_error": _safe_text(raw_runtime.get("state_error"), default="none"),
        "oom_killed": _safe_bool(raw_runtime.get("oom_killed")),
        "dead": _safe_bool(raw_runtime.get("dead")),
        "privileged": _safe_bool(raw_runtime.get("privileged")),
        "read_only_rootfs": _safe_bool(raw_runtime.get("read_only_rootfs")),
        "oom_kill_disable": _safe_bool(raw_runtime.get("oom_kill_disable")),
        "no_new_privileges": _safe_bool(raw_runtime.get("no_new_privileges")),
        "init_process": _safe_bool(raw_runtime.get("init_process")),
        "stop_signal": _safe_text(raw_runtime.get("stop_signal"), default="SIGTERM"),
        "stop_timeout": _safe_text(raw_runtime.get("stop_timeout"), default="default"),
        "security_opts": security_opts,
        "security_opts_count": len(security_opts),
        "hidden_security_opts_count": hidden_security_opts_count,
        "cap_add": cap_add,
        "cap_add_count": len(cap_add),
        "hidden_cap_add_count": hidden_cap_add_count,
        "cap_add_text": cap_add_text,
        "cap_drop": cap_drop,
        "cap_drop_count": len(cap_drop),
        "hidden_cap_drop_count": hidden_cap_drop_count,
        "cap_drop_text": cap_drop_text,
    }


def _build_back_keyboard(
    container_name: str,
    container_ref: str,
    user_id: int,
    emojis: dict[str, str],
) -> InlineKeyboardMarkup:
    return keyboards.build_inline_keyboard(
        [
            button_data(
                text=f"{emojis.get('BACK_arrow', '⬅️')} {container_name}",
                callback_data=build_container_full_info_callback_data(
                    container_ref=container_ref, user_id=user_id
                ),
            )
        ]
    )


def _container_display_name(attrs: dict[str, object], fallback: str) -> str:
    """Return the container name as Docker reports it (without the slash)."""
    name = str(attrs.get("Name") or "").lstrip("/").strip()
    return name or fallback


def _load_container_details(
    call: CallbackQuery, bot: TeleBot, container_ref: str
) -> object | None:
    """Fetch container details or tell the user why they are unavailable."""
    if not validate_container_name(container_ref):
        show_handler_info(call, text=INVALID_CONTAINER_REF_TEXT, bot=bot)
        return None
    try:
        container_details: object | None = fetch_full_container_details(container_ref)
    except DockerConnectionError:
        logger.warning(
            "bot.handler.docker.container_runtime_info.docker.unavailable.warn"
        )
        show_handler_info(call, text=DOCKER_UNAVAILABLE_TEXT, bot=bot)
        return None
    except InvalidContainerReferenceError:
        show_handler_info(call, text=INVALID_CONTAINER_REF_TEXT, bot=bot)
        return None
    except DockerOperationException:
        show_handler_info(call, text=DOCKER_REQUEST_FAILED_TEXT, bot=bot)
        return None
    if container_details is None:
        show_handler_info(call, text=CONTAINER_NOT_FOUND_TEXT, bot=bot)
        return None
    if call.message is None:
        show_handler_info(
            call,
            text="This container details message can no longer be updated.",
            bot=bot,
        )
        return None
    return container_details


def _render_extra_view(
    action: str,
    common_context: dict[str, object],
    attrs: dict[str, object],
    emojis: dict[str, str],
) -> str:
    if action == CONTAINER_EXTRA_ACTION_VOLUMES:
        return Compiler.quick_render(
            template_name="d_container_volumes_info.jinja2",
            luggage_emoji=emojis.get("luggage", "🧳"),
            backpack_emoji=emojis.get("backpack", "🎒"),
            chart_emoji=emojis.get("chart_increasing", "📈"),
            **_extract_volume_context(attrs),
            **common_context,
        )
    if action == CONTAINER_EXTRA_ACTION_NETWORKS:
        return Compiler.quick_render(
            template_name="d_container_networks_info.jinja2",
            globe_emoji=emojis.get("globe_with_meridians", "🌐"),
            chart_emoji=emojis.get("chart_increasing", "📈"),
            network_emoji=emojis.get("globe_with_meridians", "🌐"),
            gear_emoji=emojis.get("gear", "⚙️"),
            **_extract_network_context(attrs),
            **common_context,
        )
    return Compiler.quick_render(
        template_name="d_container_runtime_info.jinja2",
        stethoscope_emoji=emojis.get("stethoscope", "🩺"),
        gear_emoji=emojis.get("gear", "⚙️"),
        chart_emoji=emojis.get("chart_increasing", "📈"),
        shield_emoji=emojis.get("shield", "🛡️"),
        **_extract_runtime_context(attrs),
        **common_context,
    )


@logger.catch()
@logger.session_decorator
@two_factor_auth_required
def handle_container_extra_info(call: CallbackQuery, bot: TeleBot) -> None:
    """Handle 2FA-protected runtime details for container."""
    try:
        parsed = parse_container_extra_callback_data(call.data)
    except ValueError:
        show_handler_info(
            call, text="This container details button is no longer valid.", bot=bot
        )
        return None

    is_allowed, deny_reason = authorize_docker_callback_request(call, parsed.user_id)
    if not is_allowed:
        show_handler_info(call, text=f"Container details: {deny_reason}", bot=bot)
        return None

    container_details = _load_container_details(call, bot, parsed.container_ref)
    if container_details is None:
        return None

    attrs = _extract_container_attrs(container_details)
    container_name = _container_display_name(attrs, parsed.container_ref)
    container_ref = container_short_id(attrs.get("Id")) or parsed.container_ref
    emojis = get_emojis()
    common_context: dict[str, object] = {
        "thought_balloon": emojis.get("thought_balloon", "💭"),
        "package_emoji": emojis.get("package", "📦"),
        "banjo": emojis.get("banjo", "🪕"),
        "container_name": container_name,
    }
    rendered = _render_extra_view(parsed.action, common_context, attrs, emojis)

    edit_callback_message_text(
        call=call,
        bot=bot,
        rich_message=build_rich_html_message(rendered),
        reply_markup=_build_back_keyboard(
            container_name=container_name,
            container_ref=container_ref,
            user_id=parsed.user_id,
            emojis=emojis,
        ),
        not_modified_text="Container details are already current.",
    )
    return None
