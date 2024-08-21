#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
# Commands handlers:

from pytmbot.handlers.auth_processing.twofa_processing import handle_twofa_message
from pytmbot.handlers.bot_handlers.about import handle_about_command
from pytmbot.handlers.bot_handlers.echo import handle_echo  # allways last
from pytmbot.handlers.bot_handlers.inline.update import handle_update_info
from pytmbot.handlers.bot_handlers.navigation import handle_navigation
from pytmbot.handlers.bot_handlers.start import handle_start
from pytmbot.handlers.bot_handlers.updates import handle_bot_updates
from pytmbot.handlers.docker_handlers.containers import handle_containers
from pytmbot.handlers.docker_handlers.docker import handle_docker
from pytmbot.handlers.docker_handlers.images import handle_images
from pytmbot.handlers.server_handlers.filesystem import handle_file_system
from pytmbot.handlers.server_handlers.inline.swap import handle_swap_info
from pytmbot.handlers.server_handlers.load_average import handle_load_average
from pytmbot.handlers.server_handlers.memory import handle_memory
from pytmbot.handlers.server_handlers.network import handle_network
from pytmbot.handlers.server_handlers.process import handle_process
from pytmbot.handlers.server_handlers.sensors import handle_sensors
from pytmbot.handlers.server_handlers.uptime import handle_uptime


class HandlerManager:
    """Class for storing callback functions and keyword arguments."""

    def __init__(self, callback, **kwargs):
        self.callback = callback
        self.kwargs = kwargs


def handler_factory():
    """
    Returns a dictionary of HandlerManager objects.

    The dictionary keys represent command categories, and the values are lists
    of HandlerManager objects. Each HandlerManager object is initialized with
    a callback function and optional keyword arguments.

    Returns:
        dict: A dictionary of HandlerManager objects.
    """
    return {
        'authorization': [
            HandlerManager(callback=handle_twofa_message, regexp='Enter 2FA code')
        ],
        'start': [
            HandlerManager(callback=handle_start, commands=['help', 'start'])
        ],
        'about': [
            HandlerManager(callback=handle_about_command, regexp="About me")
        ],
        'navigation': [
            HandlerManager(callback=handle_navigation, regexp="Back to main menu"),
            HandlerManager(callback=handle_navigation, commands=['back'])
        ],
        'updates': [
            HandlerManager(callback=handle_bot_updates, commands=['check_bot_updates'])
        ],
        'containers': [
            HandlerManager(callback=handle_containers, commands=['containers']),
            HandlerManager(callback=handle_containers, regexp="Containers")
        ],
        'docker': [
            HandlerManager(callback=handle_docker, commands=['docker']),
            HandlerManager(callback=handle_docker, regexp="Docker")
        ],
        'filesystem': [
            HandlerManager(callback=handle_file_system, regexp="File system")
        ],
        'images': [
            HandlerManager(callback=handle_images, commands=['images']),
            HandlerManager(callback=handle_images, regexp="Images")
        ],
        'load_average': [
            HandlerManager(callback=handle_load_average, regexp="Load average")
        ],
        'memory': [
            HandlerManager(callback=handle_memory, regexp="Memory")
        ],
        'network': [
            HandlerManager(callback=handle_network, regexp="Network")
        ],
        'process': [
            HandlerManager(callback=handle_process, regexp="Process")
        ],
        'sensors': [
            HandlerManager(callback=handle_sensors, regexp="Sensors")
        ],
        'uptime': [
            HandlerManager(callback=handle_uptime, regexp="Uptime")
        ],
        # Echo handler. Always past in the end!
        'echo': [
            HandlerManager(callback=handle_echo, func=lambda message: True)
        ]
    }


def inline_handler_factory():
    """
    Returns a dictionary of HandlerManager objects.

    The dictionary keys represent command categories, and the values are lists
    of HandlerManager objects. Each HandlerManager object is initialized with
    a callback function and optional keyword arguments.

    Returns:
        dict: A dictionary of HandlerManager objects.
    """
    return {
        'swap': [
            HandlerManager(callback=handle_swap_info, func=lambda call: call.data == '__swap_info__')
        ],
        'update_info': [
            HandlerManager(callback=handle_update_info, func=lambda call: call.data == '__how_update__')
        ]
    }
