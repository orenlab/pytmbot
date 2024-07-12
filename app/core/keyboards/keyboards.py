#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from functools import lru_cache
from typing import Dict, List, Optional

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.core.settings.keyboards import KeyboardSettings
from app.utilities.utilities import EmojiConverter


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

    def __init__(self) -> None:
        """
        Initializes the Keyboard class.

        This method initializes the Keyboard class and sets up the EmojiConverter attribute.

        Args:
            self (Keyboard): The instance of the Keyboard class.

        Returns:
            None
        """
        # Call the superclass initialization method
        super().__init__()

        # Initialize the emojis attribute with an instance of EmojiConverter
        self.emojis: EmojiConverter = EmojiConverter()

    def __construct_keyboard(self, keyboard_data: Dict[str, str]) -> List[str]:
        """
        Constructs a keyboard from a dictionary of emoji-title pairs.

        Args:
            keyboard_data (Dict[str, str]): A dictionary where the keys are emojis and the values are titles.

        Returns:
            List[str]: A list of strings representing the constructed keyboard.
        """
        constructed_keyboard = [f"{self.emojis.get_emoji(emoji)} {title}" for emoji, title in keyboard_data.items()]
        return constructed_keyboard

    @lru_cache
    def build_reply_keyboard(self) -> ReplyKeyboardMarkup:
        """
        Constructs a ReplyKeyboardMarkup object with the main keyboard settings.

        Args:
            self: The instance of the Keyboard class.

        Returns:
            types.ReplyKeyboardMarkup: The constructed reply keyboard markup.
        """
        # Create a new ReplyKeyboardMarkup object with resize_keyboard set to True
        reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)

        # Construct the keyboard using the main keyboard settings
        keyboard_buttons = self.__construct_keyboard(self._get_main_keyboard())

        # Add the constructed keyboard to the reply keyboard
        reply_keyboard.add(*keyboard_buttons)

        return reply_keyboard

    @lru_cache
    def build_inline_keyboard(self, *button_texts: str,
                              callback_data: Optional[str] = None) -> InlineKeyboardMarkup:
        """
        Constructs an inline keyboard using the provided button texts and callback data.

        Args:
            button_texts (List[str]): List of button texts.
            callback_data (Optional[str], optional): The callback data to be associated with the buttons.
            Defaults to None.

        Returns:
            InlineKeyboardMarkup: The constructed inline keyboard markup.
        """
        buttons = [
            InlineKeyboardButton(
                text=text,
                callback_data=callback_data or text.lower().replace(' ', '_')
            )
            for text in button_texts
        ]

        return InlineKeyboardMarkup([buttons])
