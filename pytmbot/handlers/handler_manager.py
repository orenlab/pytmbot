#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from pytmbot.globals import settings
from pytmbot.handlers.auth_processing.qrcode_processing import handle_qr_code_message
from pytmbot.handlers.auth_processing.twofa_processing import (
    handle_twofa_message,
    handle_totp_code_verification,
)
from pytmbot.handlers.bot_handlers.about import handle_about_command
from pytmbot.handlers.bot_handlers.echo import handle_echo  # always last
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


def handler_factory() -> dict[str, list[HandlerManager]]:
    """
    Returns a dictionary of HandlerManager objects for command handling.

    The dictionary keys represent command categories, and the values are lists
    of HandlerManager objects. Each HandlerManager object is initialized with
    a callback function and optional keyword arguments.

    Returns:
        dict: A dictionary of HandlerManager objects.
    """
    return {
        "authorization": [
            HandlerManager(callback=handle_twofa_message, regexp="Enter 2FA code")
        ],
        "code_verification": [
            HandlerManager(callback=handle_totp_code_verification, regexp=r"[0-9]{6}$")
        ],
        "start": [HandlerManager(callback=handle_start, commands=["help", "start"])],
        "about": [HandlerManager(callback=handle_about_command, regexp="About me")],
        "navigation": [
            HandlerManager(callback=handle_navigation, regexp="Back to main menu"),
            HandlerManager(callback=handle_navigation, commands=["back"]),
        ],
        "updates": [
            HandlerManager(callback=handle_bot_updates, commands=["check_bot_updates"])
        ],
        "containers": [
            HandlerManager(callback=handle_containers, commands=["containers"]),
            HandlerManager(callback=handle_containers, regexp="Containers"),
        ],
        "docker": [
            HandlerManager(callback=handle_docker, commands=["docker"]),
            HandlerManager(callback=handle_docker, regexp="Docker"),
        ],
        "filesystem": [
            HandlerManager(callback=handle_file_system, regexp="File system")
        ],
        "images": [
            HandlerManager(callback=handle_images, commands=["images"]),
            HandlerManager(callback=handle_images, regexp="Images"),
        ],
        "load_average": [
            HandlerManager(callback=handle_load_average, regexp="Load average")
        ],
        "memory": [HandlerManager(callback=handle_memory, regexp="Memory")],
        "network": [HandlerManager(callback=handle_network, regexp="Network")],
        "process": [HandlerManager(callback=handle_process, regexp="Process")],
        "sensors": [HandlerManager(callback=handle_sensors, regexp="Sensors")],
        "uptime": [HandlerManager(callback=handle_uptime, regexp="Uptime")],
        "plugins": [
            HandlerManager(callback=handle_plugins, commands=["plugins"]),
            HandlerManager(callback=handle_plugins, regexp="Plugins"),
        ],
        "server": [
            HandlerManager(callback=handle_server, commands=["server"]),
            HandlerManager(callback=handle_server, regexp="Server"),
        ],
        "qrcode": [
            HandlerManager(
                callback=handle_qr_code_message,
                regexp="Get QR-code for 2FA app",
                func=lambda message: message.from_user.id
                                     in settings.access_control.allowed_admins_ids,
            ),
            HandlerManager(
                callback=handle_qr_code_message,
                commands=["qrcode"],
                func=lambda message: message.from_user.id
                                     in settings.access_control.allowed_admins_ids,
            ),
        ],
    }


def inline_handler_factory() -> dict[str, list[HandlerManager]]:
    """
    Returns a dictionary of HandlerManager objects for inline query handling.

    The dictionary keys represent command categories, and the values are lists
    of HandlerManager objects. Each HandlerManager object is initialized with
    a callback function and optional keyword arguments.

    Returns:
        dict: A dictionary of HandlerManager objects.
    """
    return {
        "swap": [
            HandlerManager(
                callback=handle_swap_info,
                func=lambda call: call.data == "__swap_info__",
            )
        ],
        "update_info": [
            HandlerManager(
                callback=handle_update_info,
                func=lambda call: call.data == "__how_update__",
            )
        ],
        "get_logs": [
            HandlerManager(
                callback=handle_get_logs,
                func=lambda call: call.data.startswith("__get_logs__"),
            )
        ],
        "containers_full_info": [
            HandlerManager(
                callback=handle_containers_full_info,
                func=lambda call: call.data.startswith("__get_full__"),
            )
        ],
        "back_to_containers": [
            HandlerManager(
                callback=handle_back_to_containers,
                func=lambda call: call.data == "back_to_containers",
            )
        ],
        "manage": [
            HandlerManager(
                callback=handle_manage_container,
                func=lambda call: call.data.startswith("__manage__"),
            )
        ],
        "manage_action": [
            HandlerManager(
                callback=handle_manage_container_action,
                func=lambda call: managing_action_fabric(call),
            )
        ],
    }


def echo_handler_factory() -> dict[str, list[HandlerManager]]:
    """
    Returns a dictionary of HandlerManager objects for echo handling.

    The dictionary keys represent command categories, and the values are lists
    of HandlerManager objects. Each HandlerManager object is initialized with
    a callback function and optional keyword arguments.

    Returns:
        dict: A dictionary of HandlerManager objects.
    """
    return {"echo": [HandlerManager(callback=handle_echo, func=lambda message: True)]}
