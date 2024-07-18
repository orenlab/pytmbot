#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from functools import lru_cache
from typing import Dict


class KeyboardSettings:
    """
    KeyboardSettings base class. This class is used to store and retrieve keyboard settings.

    Attributes:
        main_keyboard (Dict[str, str]): The main keyboard settings.

    Methods:
        _get_main_keyboard(self)

    Returns:
        Dict[str, str]: The main keyboard settings.
    """

    def __init__(self) -> None:
        """
        Initializes the KeyboardSettings class with empty main and Docker keyboards.

        Args:
            self: The instance of the KeyboardSettings class.

        Returns:
            None
        """
        self.main_keyboard = {}
        self.docker_keyboard = {}

    @lru_cache
    def _get_main_keyboard(self) -> Dict[str, str]:
        """
        Retrieves the main keyboard settings.

        Returns:
            Dict[str, str]: The main keyboard settings.
        """
        main_keyboard_settings = {
            'low_battery': 'Load average',
            'pager': 'Memory load',
            'stopwatch': 'Sensors',
            'rocket': 'Process',
            'flying_saucer': 'Uptime',
            'floppy_disk': 'File system',
            'spouting_whale': 'Docker',
            'satellite': 'Network',
            'turtle': 'About me'
        }

        return main_keyboard_settings

    @lru_cache
    def _get_docker_keyboard(self) -> Dict[str, str]:
        """Retrieves the Docker keyboard settings.

        Returns:
            Dict[str, str]: The Docker keyboard settings.
        """
        # Define the Docker keyboard settings
        docker_keyboard = {
            'framed_picture': 'Images',
            'toolbox': 'Containers',
            'BACK_arrow': 'Back to main menu'
        }

        # Return the Docker keyboard settings
        return docker_keyboard
