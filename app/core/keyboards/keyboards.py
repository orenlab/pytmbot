#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from functools import lru_cache
from typing import Dict, List

from telebot import types

from app.core.settings.keyboards import KeyboardSettings
from app.utilities.utilities import get_emoji


def construct_keyboard(keyboard_data: Dict[str, str]) -> List[str]:
    """
    Constructs a keyboard from a dictionary of emoji-title pairs.

    Args:
        keyboard_data (Dict[str, str]): A dictionary where the keys are emojis and the values are titles.

    Returns:
        List[str]: A list of strings representing the constructed keyboard.
    """
    constructed_keyboard = [f"{get_emoji(emoji)} {title}" for emoji, title in keyboard_data.items()]
    return constructed_keyboard


class Keyboard(KeyboardSettings):
    """
    A class for managing keyboard settings.

    Attributes:
        main_keyboard (Dict[str, str]): A dictionary of emoji-title pairs representing the main keyboard.

    Methods:
        build_reply_keyboard(self)
        build_inline_keyboard(self, button_text: str, callback_data: str)

    Example:
        keyboard = Keyboard()
        reply_keyboard = keyboard.build_reply_keyboard()

    Returns:
        types.ReplyKeyboardMarkup: The constructed reply keyboard.
    """

    def build_reply_keyboard(self) -> types.ReplyKeyboardMarkup:
        """
        Constructs a ReplyKeyboardMarkup object with the main keyboard settings.

        Args:
            self: The instance of the Keyboard class.

        Returns:
            types.ReplyKeyboardMarkup: The constructed reply keyboard markup.
        """
        # Create a new ReplyKeyboardMarkup object with resize_keyboard set to True
        reply_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)

        # Construct the keyboard using the main keyboard settings
        keyboard_buttons = construct_keyboard(self._get_main_keyboard())

        # Add the constructed keyboard to the reply keyboard
        reply_keyboard.add(*keyboard_buttons)

        return reply_keyboard

    @lru_cache
    def build_inline_keyboard(self, button_text: str, callback_data: str) -> types.InlineKeyboardMarkup:
        """
        Build an inline keyboard with a single button.

        Args:
            button_text (str): The text to display on the button.
            callback_data (str): The data to send when the button is clicked.

        Returns:
            types.InlineKeyboardMarkup: The built inline keyboard.
        """
        # Create a new InlineKeyboardMarkup object
        keyboard = types.InlineKeyboardMarkup()

        # Create a new InlineKeyboardButton object with the specified button text and callback data
        button = types.InlineKeyboardButton(text=button_text, callback_data=callback_data)

        # Add the button to the keyboard
        keyboard.add(button)

        # Return the built keyboard
        return keyboard
