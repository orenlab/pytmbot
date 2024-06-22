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
        Initializes the KeyboardSettings class.

        This method initializes the KeyboardSettings class and sets the `main_keyboard` attribute
        to an empty dictionary.

        Args:
            self: The instance of the KeyboardSettings class.

        Returns:
            None
        """
        self.main_keyboard = {}

    @lru_cache
    def _get_main_keyboard(self) -> Dict[str, str]:
        """
        Get the main keyboard.

        This function retrieves the main keyboard settings.

        Args:
            self: The instance of the KeyboardSettings class.

        Returns:
            Dict[str, str]: The main keyboard settings.
        """
        # Define the main keyboard settings
        self.main_keyboard = {
            'low_battery': 'Load average',
            'pager': 'Memory load',
            'stopwatch': 'Sensors',
            'rocket': 'Process',
            'flying_saucer': 'Uptime',
            'floppy_disk': 'File system',
            'luggage': 'Containers',
            'satellite': 'Network',
            'turtle': 'About me'
        }

        # Return the main keyboard settings
        return self.main_keyboard
