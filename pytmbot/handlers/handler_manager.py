#!/usr/bin/env python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from pytmbot.globals import settings
from pytmbot.handlers.auth_processing.qrcode_processing import handle_qr_code_message
from pytmbot.handlers.auth_processing.twofa_processing import (
    handle_twofa_message,
    handle_totp_code_verification,
)
from pytmbot.handlers.bot_handlers.about import handle_about_command
from pytmbot.handlers.bot_handlers.echo import handle_echo
from pytmbot.handlers.bot_handlers.inline.update import handle_update_info
from pytmbot.handlers.bot_handlers.navigation import handle_navigation
from pytmbot.handlers.bot_handlers.plugins import handle_plugins
from pytmbot.handlers.bot_handlers.start import handle_start
from pytmbot.handlers.bot_handlers.updates import handle_bot_updates
from pytmbot.handlers.docker_handlers.containers import handle_containers
from pytmbot.handlers.docker_handlers.docker import handle_docker
from pytmbot.handlers.docker_handlers.images import handle_images
from pytmbot.handlers.docker_handlers.inline.back import handle_back_to_containers
from pytmbot.handlers.docker_handlers.inline.container_info import (
    handle_containers_full_info,
)
from pytmbot.handlers.docker_handlers.inline.image_updates import handle_image_updates
from pytmbot.handlers.docker_handlers.inline.logs import handle_get_logs
from pytmbot.handlers.docker_handlers.inline.manage import handle_manage_container
from pytmbot.handlers.docker_handlers.inline.manage_action import (
    handle_manage_container_action,
    managing_action_fabric,
)
from pytmbot.handlers.server_handlers.filesystem import handle_file_system
from pytmbot.handlers.server_handlers.inline.swap import handle_swap_info
from pytmbot.handlers.server_handlers.load_average import handle_load_average
from pytmbot.handlers.server_handlers.memory import handle_memory
from pytmbot.handlers.server_handlers.network import handle_network
from pytmbot.handlers.server_handlers.process import handle_process
from pytmbot.handlers.server_handlers.sensors import handle_sensors
from pytmbot.handlers.server_handlers.server import handle_server
from pytmbot.handlers.server_handlers.uptime import handle_uptime
from pytmbot.models.handlers_model import HandlerManager

MessageType: TypeAlias = Any
CallbackQueryType: TypeAlias = Any
HandlerType: TypeAlias = dict[str, list[HandlerManager]]
FilterFunc: TypeAlias = Callable[[Any], bool]


@dataclass(frozen=True, slots=True)
class HandlerConfig:
    """Configuration for handler registration."""
    callback: Callable[..., Any]
    commands: list[str] | None = None
    regexp: str | None = None
    filter_func: FilterFunc | None = None

    def create_handler(self) -> HandlerManager:
        """Create a HandlerManager instance from the config."""
        kwargs = {}
        if self.commands:
            kwargs['commands'] = self.commands
        if self.regexp:
            kwargs['regexp'] = self.regexp
        if self.filter_func:
            kwargs['func'] = self.filter_func
        return HandlerManager(callback=self.callback, kwargs=kwargs)


def create_admin_filter(message: MessageType) -> bool:
    """Create a filter function for admin-only commands."""
    return message.from_user.id in settings.access_control.allowed_admins_ids


def handler_factory() -> HandlerType:
    """
    Returns a dictionary of HandlerManager objects for command handling.

    The factory uses HandlerConfig for cleaner handler creation and
    better type safety.
    """
    configs = {
        "authorization": [
            HandlerConfig(
                callback=handle_twofa_message,
                regexp="Enter 2FA code"
            )
        ],
        "code_verification": [
            HandlerConfig(
                callback=handle_totp_code_verification,
                regexp=r"[0-9]{6}$"
            )
        ],
        "start": [
            HandlerConfig(
                callback=handle_start,
                commands=["help", "start"]
            )
        ],
        "about": [
            HandlerConfig(
                callback=handle_about_command,
                regexp="About me"
            )
        ],
        "navigation": [
            HandlerConfig(
                callback=handle_navigation,
                regexp="Back to main menu"
            ),
            HandlerConfig(
                callback=handle_navigation,
                commands=["back"]
            )
        ],
        "updates": [
            HandlerConfig(
                callback=handle_bot_updates,
                commands=["check_bot_updates"]
            )
        ],
        "containers": [
            HandlerConfig(
                callback=handle_containers,
                commands=["containers"]
            ),
            HandlerConfig(
                callback=handle_containers,
                regexp="Containers"
            )
        ],
        "docker": [
            HandlerConfig(
                callback=handle_docker,
                commands=["docker"]
            ),
            HandlerConfig(
                callback=handle_docker,
                regexp="Docker"
            )
        ],
        "filesystem": [
            HandlerConfig(
                callback=handle_file_system,
                regexp="File system"
            )
        ],
        "images": [
            HandlerConfig(
                callback=handle_images,
                commands=["images"]
            ),
            HandlerConfig(
                callback=handle_images,
                regexp="Images"
            )
        ],
        "load_average": [
            HandlerConfig(
                callback=handle_load_average,
                regexp="Load average"
            )
        ],
        "memory": [
            HandlerConfig(
                callback=handle_memory,
                regexp="Memory"
            )
        ],
        "network": [
            HandlerConfig(
                callback=handle_network,
                regexp="Network"
            )
        ],
        "process": [
            HandlerConfig(
                callback=handle_process,
                regexp="Process"
            )
        ],
        "sensors": [
            HandlerConfig(
                callback=handle_sensors,
                regexp="Sensors"
            )
        ],
        "uptime": [
            HandlerConfig(
                callback=handle_uptime,
                regexp="Uptime"
            )
        ],
        "plugins": [
            HandlerConfig(
                callback=handle_plugins,
                commands=["plugins"]
            ),
            HandlerConfig(
                callback=handle_plugins,
                regexp="Plugins"
            )
        ],
        "server": [
            HandlerConfig(
                callback=handle_server,
                commands=["server"]
            ),
            HandlerConfig(
                callback=handle_server,
                regexp="Server"
            )
        ],
        "qrcode": [
            HandlerConfig(
                callback=handle_qr_code_message,
                regexp="Get QR-code for 2FA app",
                filter_func=create_admin_filter
            ),
            HandlerConfig(
                callback=handle_qr_code_message,
                commands=["qrcode"],
                filter_func=create_admin_filter
            )
        ]
    }

    return {
        category: [config.create_handler() for config in handlers]
        for category, handlers in configs.items()
    }


def inline_handler_factory() -> HandlerType:
    """
    Returns a dictionary of HandlerManager objects for inline query handling.

    The factory uses HandlerConfig for cleaner handler creation and
    better type safety.
    """
    configs = {
        "swap": [
            HandlerConfig(
                callback=handle_swap_info,
                filter_func=lambda call: call.data == "__swap_info__"
            )
        ],
        "update_info": [
            HandlerConfig(
                callback=handle_update_info,
                filter_func=lambda call: call.data == "__how_update__"
            )
        ],
        "get_logs": [
            HandlerConfig(
                callback=handle_get_logs,
                filter_func=lambda call: call.data.startswith("__get_logs__")
            )
        ],
        "containers_full_info": [
            HandlerConfig(
                callback=handle_containers_full_info,
                filter_func=lambda call: call.data.startswith("__get_full__")
            )
        ],
        "back_to_containers": [
            HandlerConfig(
                callback=handle_back_to_containers,
                filter_func=lambda call: call.data == "back_to_containers"
            )
        ],
        "manage": [
            HandlerConfig(
                callback=handle_manage_container,
                filter_func=lambda call: call.data.startswith("__manage__")
            )
        ],
        "manage_action": [
            HandlerConfig(
                callback=handle_manage_container_action,
                filter_func=managing_action_fabric
            )
        ],
        "image_updates": [
            HandlerConfig(
                callback=handle_image_updates,
                filter_func=lambda call: call.data == "__check_updates__"
            )
        ]
    }

    return {
        category: [config.create_handler() for config in handlers]
        for category, handlers in configs.items()
    }


def echo_handler_factory() -> HandlerType:
    """
    Returns a dictionary of HandlerManager objects for echo handling.

    This is always the last handler to be registered.
    """
    configs = {
        "echo": [
            HandlerConfig(
                callback=handle_echo,
                filter_func=lambda message: True
            )
        ]
    }

    return {
        category: [config.create_handler() for config in handlers]
        for category, handlers in configs.items()
    }
