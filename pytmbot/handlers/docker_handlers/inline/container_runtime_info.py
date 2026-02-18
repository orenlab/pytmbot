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

from pytmbot.globals import ButtonDataType, get_keyboards
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    get_container_full_details,
    get_emojis,
    show_handler_info,
    validate_container_name,
)
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
keyboards = get_keyboards()

CONTAINER_EXTRA_CALLBACK_PREFIX: Final[str] = "__container_extra__"
CONTAINER_EXTRA_ACTION_VOLUMES: Final[str] = "volumes"
CONTAINER_EXTRA_ACTION_NETWORKS: Final[str] = "networks"
_MAX_RENDER_ITEMS: Final[int] = 20


@dataclass(frozen=True, slots=True)
class ParsedContainerExtraCallback:
    action: str
    container_name: str
    user_id: int


def parse_container_extra_callback_data(
    callback_data: str | None,
) -> ParsedContainerExtraCallback:
    """Parse callback payload in format '__container_extra__:<action>:<name>:<user_id>'."""
    if callback_data is None:
        raise ValueError("Missing callback payload")

    parts = callback_data.split(":")
    if len(parts) != 4 or parts[0] != CONTAINER_EXTRA_CALLBACK_PREFIX:
        raise ValueError("Invalid callback format")

    action = parts[1].strip().lower()
    if action not in (CONTAINER_EXTRA_ACTION_VOLUMES, CONTAINER_EXTRA_ACTION_NETWORKS):
        raise ValueError("Unsupported container extra action")

    container_name = parts[2].strip().lower()
    if not container_name:
        raise ValueError("Missing container name")

    try:
        user_id = int(parts[3])
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid callback user id") from exc
    if user_id <= 0:
        raise ValueError("Invalid callback user id")

    return ParsedContainerExtraCallback(
        action=action,
        container_name=container_name,
        user_id=user_id,
    )


def _safe_text(value: object, default: str = "N/A") -> str:
    """Normalize arbitrary value for safe text rendering."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text.replace("\n", " ").replace("\r", " ")


def _extract_container_attrs(container_details: object) -> dict[str, object]:
    attrs = getattr(container_details, "attrs", None)
    return attrs if isinstance(attrs, dict) else {}


def _extract_mounts(attrs: dict[str, object]) -> tuple[list[dict[str, str]], int]:
    mounts_raw = attrs.get("Mounts", [])
    if not isinstance(mounts_raw, list):
        return [], 0

    parsed_mounts: list[dict[str, str]] = []
    for mount in mounts_raw[:_MAX_RENDER_ITEMS]:
        if not isinstance(mount, dict):
            continue
        rw_flag = mount.get("RW")
        access = "rw" if rw_flag is True else "ro" if rw_flag is False else "n/a"
        parsed_mounts.append(
            {
                "source": _safe_text(mount.get("Source")),
                "destination": _safe_text(mount.get("Destination")),
                "mode": _safe_text(mount.get("Mode"), default="-"),
                "type": _safe_text(mount.get("Type"), default="bind"),
                "access": access,
            }
        )

    hidden_count = max(0, len(mounts_raw) - len(parsed_mounts))
    return parsed_mounts, hidden_count


def _extract_network_context(attrs: dict[str, object]) -> dict[str, object]:
    host_config = attrs.get("HostConfig", {})
    network_settings = attrs.get("NetworkSettings", {})
    if not isinstance(host_config, dict):
        host_config = {}
    if not isinstance(network_settings, dict):
        network_settings = {}

    ports_raw = network_settings.get("Ports", {})
    port_rows: list[str] = []
    if isinstance(ports_raw, dict):
        for container_port, bindings in list(ports_raw.items())[:_MAX_RENDER_ITEMS]:
            port_label = _safe_text(container_port)
            if isinstance(bindings, list) and bindings:
                for binding in bindings:
                    if not isinstance(binding, dict):
                        continue
                    host_ip = _safe_text(binding.get("HostIp"), default="0.0.0.0")
                    host_port = _safe_text(binding.get("HostPort"))
                    port_rows.append(f"{port_label} -> {host_ip}:{host_port}")
            else:
                port_rows.append(f"{port_label} -> unbound")
    hidden_ports_count = (
        max(0, len(ports_raw) - _MAX_RENDER_ITEMS) if isinstance(ports_raw, dict) else 0
    )

    networks_raw = network_settings.get("Networks", {})
    network_rows: list[dict[str, object]] = []
    if isinstance(networks_raw, dict):
        for network_name, config in list(networks_raw.items())[:_MAX_RENDER_ITEMS]:
            cfg = config if isinstance(config, dict) else {}
            aliases_raw = cfg.get("Aliases", [])
            aliases = (
                [
                    _safe_text(alias)
                    for alias in aliases_raw
                    if isinstance(alias, str) and alias.strip()
                ]
                if isinstance(aliases_raw, list)
                else []
            )
            network_rows.append(
                {
                    "name": _safe_text(network_name),
                    "ip_address": _safe_text(cfg.get("IPAddress")),
                    "gateway": _safe_text(cfg.get("Gateway")),
                    "mac_address": _safe_text(cfg.get("MacAddress")),
                    "aliases": aliases,
                }
            )
    hidden_networks_count = (
        max(0, len(networks_raw) - len(network_rows))
        if isinstance(networks_raw, dict)
        else 0
    )

    return {
        "network_mode": _safe_text(host_config.get("NetworkMode"), default="default"),
        "ports": port_rows,
        "ports_count": len(port_rows),
        "hidden_ports_count": hidden_ports_count,
        "networks": network_rows,
        "networks_count": len(network_rows),
        "hidden_networks_count": hidden_networks_count,
    }


def _build_back_keyboard(
    container_name: str,
    user_id: int,
    emojis: dict[str, str],
) -> InlineKeyboardMarkup:
    return keyboards.build_inline_keyboard(
        [
            button_data(
                text=f"{emojis.get('BACK_arrow', '⬅️')} Back to {container_name} info",
                callback_data=f"__get_full__:{container_name}:{user_id}",
            )
        ]
    )


@logger.catch()
@logger.session_decorator
@two_factor_auth_required
def handle_container_extra_info(call: CallbackQuery, bot: TeleBot) -> None:
    """Handle 2FA-protected volumes/networks details for container."""
    try:
        parsed = parse_container_extra_callback_data(call.data)
    except ValueError:
        show_handler_info(call, text="Invalid container details request", bot=bot)
        return None

    is_allowed, deny_reason = authorize_docker_callback_request(call, parsed.user_id)
    if not is_allowed:
        show_handler_info(call, text=f"Container details: {deny_reason}", bot=bot)
        return None

    if not validate_container_name(parsed.container_name):
        show_handler_info(call, text="Invalid container name format", bot=bot)
        return None

    container_details = get_container_full_details(parsed.container_name)
    if container_details is None:
        show_handler_info(
            call,
            text=f"{parsed.container_name}: Container not found",
            bot=bot,
        )
        return None

    callback_message = call.message
    if callback_message is None:
        show_handler_info(
            call,
            text="Cannot render container details in this context",
            bot=bot,
        )
        return None

    attrs = _extract_container_attrs(container_details)
    emojis = get_emojis()
    common_context = {
        "thought_balloon": emojis.get("thought_balloon", "💭"),
        "package_emoji": emojis.get("package", "📦"),
        "banjo": emojis.get("banjo", "🪕"),
        "container_name": parsed.container_name,
    }

    if parsed.action == CONTAINER_EXTRA_ACTION_VOLUMES:
        mounts, hidden_mounts_count = _extract_mounts(attrs)
        rendered = Compiler.quick_render(
            template_name="d_container_volumes_info.jinja2",
            luggage_emoji=emojis.get("luggage", "🧳"),
            mounts=mounts,
            mounts_count=len(mounts),
            hidden_mounts_count=hidden_mounts_count,
            **common_context,
        )
    else:
        network_context = _extract_network_context(attrs)
        rendered = Compiler.quick_render(
            template_name="d_container_networks_info.jinja2",
            globe_emoji=emojis.get("globe_with_meridians", "🌐"),
            chart_emoji=emojis.get("chart_increasing", "📈"),
            network_emoji=emojis.get("globe_with_meridians", "🌐"),
            **network_context,
            **common_context,
        )

    bot.edit_message_text(
        chat_id=callback_message.chat.id,
        message_id=callback_message.message_id,
        text=rendered,
        reply_markup=_build_back_keyboard(
            container_name=parsed.container_name,
            user_id=parsed.user_id,
            emojis=emojis,
        ),
        parse_mode="HTML",
    )
    return None
