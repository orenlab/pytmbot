#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from telebot.types import CallbackQuery, Message

from pytmbot.globals import settings
from pytmbot.models.handlers_model import HandlerManager

from .auth_processing.qrcode_processing import handle_qr_code_message
from .auth_processing.twofa_processing import (
    handle_totp_code_verification,
    handle_twofa_message,
)
from .bot_handlers.about import handle_about_command
from .bot_handlers.getmyid import handle_getmyid
from .bot_handlers.inline.update import handle_update_info
from .bot_handlers.navigation import handle_navigation
from .bot_handlers.plugins import handle_plugins
from .bot_handlers.start import handle_start
from .bot_handlers.updates import handle_bot_updates
from .docker_handlers.containers import handle_containers
from .docker_handlers.docker import handle_docker
from .docker_handlers.images import handle_images
from .docker_handlers.inline.back import handle_back_to_containers
from .docker_handlers.inline.container_info import (
    handle_containers_full_info,
)
from .docker_handlers.inline.image_updates import handle_image_updates
from .docker_handlers.inline.images_page import handle_images_page
from .docker_handlers.inline.logs import handle_get_logs
from .docker_handlers.inline.manage import handle_manage_container
from .docker_handlers.inline.manage_action import (
    handle_manage_container_action,
    managing_action_fabric,
)
from .server_handlers.filesystem import handle_file_system
from .server_handlers.inline.swap import handle_swap_info
from .server_handlers.inline.top_process import handle_process_info
from .server_handlers.load_average import handle_load_average
from .server_handlers.memory import handle_memory
from .server_handlers.network import handle_network
from .server_handlers.process import handle_process
from .server_handlers.quickview import handle_quick_view
from .server_handlers.sensors import handle_sensors
from .server_handlers.server import handle_server
from .server_handlers.services import handle_services_status
from .server_handlers.uptime import handle_uptime

# Modern type aliases
type MessageType = Message
type CallbackQueryType = CallbackQuery
type HandlerType = dict[str, list[HandlerManager]]
type FilterFunc = Callable[[Message | CallbackQuery], bool]
type HandlerCallback = Callable[..., Any]

# Constants
TOTP_CODE_PATTERN: Final[str] = r"^/?[0-9]{6}$"


@dataclass(frozen=True, slots=True)
class HandlerConfig:
    """Configuration for handler registration with improved type safety."""

    callback: HandlerCallback
    commands: list[str] | None = None
    regexp: str | None = None
    filter_func: FilterFunc | None = None

    def create_handler(self) -> HandlerManager:
        """Create a HandlerManager instance from the config."""
        kwargs: dict[str, Any] = {}
        if self.commands:
            kwargs["commands"] = self.commands
        if self.regexp:
            kwargs["regexp"] = self.regexp
        if self.filter_func:
            kwargs["func"] = self.filter_func
        return HandlerManager(callback=self.callback, kwargs=kwargs)


class AdminFilter:
    """Filter for admin-only commands with caching."""

    @staticmethod
    @cache
    def _get_admin_ids() -> frozenset[int]:
        """Get admin IDs with caching."""
        return frozenset(settings.access_control.allowed_admins_ids)

    @classmethod
    def is_admin(cls, message: MessageType) -> bool:
        """Check if user is admin."""
        if not message.from_user:
            return False
        return message.from_user.id in cls._get_admin_ids()


class InlineFilters:
    """Collection of inline callback filters."""

    @staticmethod
    def swap_info(call: CallbackQueryType) -> bool:
        """Filter for swap info callback."""
        return call.data == "__swap_info__"

    @staticmethod
    def process_info(call: CallbackQueryType) -> bool:
        """Filter for process info callback."""
        return call.data == "__process_info__"

    @staticmethod
    def update_info(call: CallbackQueryType) -> bool:
        """Filter for update info callback."""
        return call.data == "__how_update__"

    @staticmethod
    def get_logs(call: CallbackQueryType) -> bool:
        """Filter for get logs callback."""
        return call.data.startswith("__get_logs__")

    @staticmethod
    def containers_full_info(call: CallbackQueryType) -> bool:
        """Filter for containers full info callback."""
        return call.data.startswith("__get_full__")

    @staticmethod
    def back_to_containers(call: CallbackQueryType) -> bool:
        """Filter for back to containers callback."""
        if call.data is None:
            return False
        return call.data == "back_to_containers" or call.data.startswith(
            "__containers_page__"
        )

    @staticmethod
    def manage_container(call: CallbackQueryType) -> bool:
        """Filter for manage container callback."""
        return call.data.startswith("__manage__")

    @staticmethod
    def image_updates(call: CallbackQueryType) -> bool:
        """Filter for image updates callback."""
        return call.data == "__check_updates__"

    @staticmethod
    def images_page(call: CallbackQueryType) -> bool:
        """Filter for images pagination callback."""
        if call.data is None:
            return False
        return call.data.startswith("__images_page__")


@cache
def _get_message_handler_configs() -> dict[str, list[HandlerConfig]]:
    """Build and cache message handler configurations dictionary."""
    return {
        "authorization": [
            HandlerConfig(callback=handle_twofa_message, regexp="Enter 2FA code")
        ],
        "quick_view": [
            HandlerConfig(callback=handle_quick_view, regexp="Quick view")
        ],
        "code_verification": [
            HandlerConfig(callback=handle_totp_code_verification, regexp=TOTP_CODE_PATTERN)
        ],
        "start": [
            HandlerConfig(callback=handle_start, commands=["help", "start"])
        ],
        "about": [
            HandlerConfig(callback=handle_about_command, regexp="About me")
        ],
        "getmyid": [
            HandlerConfig(callback=handle_getmyid, commands=["getmyid"])
        ],
        "navigation": [
            HandlerConfig(callback=handle_navigation, regexp="Back to main menu"),
            HandlerConfig(callback=handle_navigation, commands=["back"]),
        ],
        "updates": [
            HandlerConfig(callback=handle_bot_updates, commands=["check_bot_updates"])
        ],
        "containers": [
            HandlerConfig(callback=handle_containers, commands=["containers"]),
            HandlerConfig(callback=handle_containers, regexp="Containers"),
        ],
        "docker": [
            HandlerConfig(callback=handle_docker, commands=["docker"]),
            HandlerConfig(callback=handle_docker, regexp="Docker"),
        ],
        "filesystem": [
            HandlerConfig(callback=handle_file_system, regexp="File system")
        ],
        "images": [
            HandlerConfig(callback=handle_images, commands=["images"]),
            HandlerConfig(callback=handle_images, regexp="Images"),
        ],
        "load_average": [
            HandlerConfig(callback=handle_load_average, regexp="Load average")
        ],
        "memory": [
            HandlerConfig(callback=handle_memory, regexp="Memory load")
        ],
        "network": [
            HandlerConfig(callback=handle_network, regexp="Network")
        ],
        "process": [
            HandlerConfig(callback=handle_process, regexp="Process")
        ],
        "sensors": [
            HandlerConfig(callback=handle_sensors, regexp="Sensors")
        ],
        "uptime": [
            HandlerConfig(callback=handle_uptime, regexp="Uptime")
        ],
        "plugins": [
            HandlerConfig(callback=handle_plugins, commands=["plugins"]),
            HandlerConfig(callback=handle_plugins, regexp="Plugins"),
        ],
        "server": [
            HandlerConfig(callback=handle_server, commands=["server"]),
            HandlerConfig(callback=handle_server, regexp="Server"),
        ],
        "services": [
            HandlerConfig(callback=handle_services_status, regexp="Services")
        ],
        "qrcode": [
            HandlerConfig(
                callback=handle_qr_code_message,
                regexp="Get QR-code for 2FA app",
                filter_func=AdminFilter.is_admin,
            ),
            HandlerConfig(
                callback=handle_qr_code_message,
                commands=["qrcode"],
                filter_func=AdminFilter.is_admin,
            ),
        ],
    }


@cache
def _get_inline_handler_configs() -> dict[str, list[HandlerConfig]]:
    """Build and cache inline handler configurations dictionary."""
    return {
        "swap": [
            HandlerConfig(callback=handle_swap_info, filter_func=InlineFilters.swap_info)
        ],
        "process_info": [
            HandlerConfig(callback=handle_process_info, filter_func=InlineFilters.process_info)
        ],
        "update_info": [
            HandlerConfig(callback=handle_update_info, filter_func=InlineFilters.update_info)
        ],
        "get_logs": [
            HandlerConfig(callback=handle_get_logs, filter_func=InlineFilters.get_logs)
        ],
        "containers_full_info": [
            HandlerConfig(
                callback=handle_containers_full_info,
                filter_func=InlineFilters.containers_full_info
            )
        ],
        "back_to_containers": [
            HandlerConfig(
                callback=handle_back_to_containers,
                filter_func=InlineFilters.back_to_containers
            )
        ],
        "manage": [
            HandlerConfig(callback=handle_manage_container, filter_func=InlineFilters.manage_container)
        ],
        "manage_action": [
            HandlerConfig(
                callback=handle_manage_container_action,
                filter_func=managing_action_fabric,
            )
        ],
        "image_updates": [
            HandlerConfig(callback=handle_image_updates, filter_func=InlineFilters.image_updates)
        ],
        "images_page": [
            HandlerConfig(callback=handle_images_page, filter_func=InlineFilters.images_page)
        ],
    }


def _create_handlers_from_configs(configs: dict[str, list[HandlerConfig]]) -> HandlerType:
    """Create handlers from configuration dictionary."""
    return {
        category: [config.create_handler() for config in handlers]
        for category, handlers in configs.items()
    }


@cache
def handler_factory() -> HandlerType:
    """
    Returns a cached dictionary of HandlerManager objects for command handling.

    The factory uses HandlerConfig for cleaner handler creation and
    better type safety. Results are cached for performance.
    """
    configs = _get_message_handler_configs()
    return _create_handlers_from_configs(configs)


@cache
def inline_handler_factory() -> HandlerType:
    """
    Returns a cached dictionary of HandlerManager objects for inline query handling.

    The factory uses HandlerConfig for cleaner handler creation and
    better type safety. Results are cached for performance.
    """
    configs = _get_inline_handler_configs()
    return _create_handlers_from_configs(configs)

# Future echo handler implementation
# @cache
# def echo_handler_factory() -> HandlerType:
#     """
#     Returns a dictionary of HandlerManager objects for echo handling.
#
#     This is always the last handler to be registered.
#     """
#     configs = {
#         "echo": [
#             HandlerConfig(
#                 callback=handle_echo,
#                 filter_func=lambda message: True
#             )
#         ]
#     }
#     return _create_handlers_from_configs(configs)
