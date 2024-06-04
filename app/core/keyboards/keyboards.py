#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from functools import lru_cache

from telebot import types

from app.core.settings.keyboards import KeyboardSettings
from app.utilities.utilities import get_emoji


def keyboard_constructor(keyboard: dict) -> list[str]:
    """
    Constructs a keyboard from a dictionary of emoji and title pairs.

    Args:
        keyboard (dict): A dictionary where the keys are emoji strings and the values
                         are title strings.

    Returns:
        list[str]: A list of strings where each string is a combination of an emoji
                   and a title, separated by a space.
    """
    # Initialize an empty list to store the constructed keyboard
    keyboard_value = []

    # Iterate over each emoji and title pair in the keyboard dictionary
    for emoji, title in keyboard.items():
        # Combine the emoji and title with a space and append to the keyboard_value list
        keyboard_value.append(get_emoji(emoji) + ' ' + title)

    # Return the constructed keyboard
    return keyboard_value


class Keyboard:
    """
    Class for building keyboard objects (reply and inline keyboard).
    """

    def __init__(self):
        """
        Initialize the Keyboard class.

        This method initializes the Keyboard class and sets the `kb` attribute
        to an instance of the KeyboardSettings class.
        """
        self.kb = KeyboardSettings()

    @lru_cache
    def build_reply_keyboard(self) -> types.ReplyKeyboardMarkup:
        """
        Builds a reply keyboard using the main keyboard settings.

        Returns:
            types.ReplyKeyboardMarkup: The built reply keyboard.
        """
        # Create a new ReplyKeyboardMarkup object with resize_keyboard set to True
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

        # Construct the keyboard using the main keyboard settings
        keyboard = keyboard_constructor(self.kb.main_keyboard)

        # Add the constructed keyboard to the markup
        markup.add(*keyboard)

        # Return the built reply keyboard
        return markup

    @lru_cache
    def build_inline_keyboard(self, button_name: str, callback_data: str) -> types.InlineKeyboardMarkup:
        """
        Build an inline keyboard with a single button.
        Args:
            button_name (str): The text to display on the button.
            callback_data (str): The data to send when the button is clicked.
        Returns:
            types.InlineKeyboardMarkup: The built inline keyboard.
        """
        # Create a new InlineKeyboardMarkup object
        markup = types.InlineKeyboardMarkup()
        # Add a button to the markup with the specified name and callback data
        markup.add(types.InlineKeyboardButton(text=button_name, callback_data=callback_data))
        # Return the built inline keyboard
        return markup
