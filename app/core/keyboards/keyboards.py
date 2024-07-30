#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from functools import lru_cache
from typing import Dict, List, Optional

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app import bot_logger, config
from app.utilities.utilities import EmojiConverter


class Keyboard:
    """
    A class for managing keyboard settings.
    """

    def __init__(self) -> None:
        """
        Initializes the Keyboard class.
        """
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
    def build_reply_keyboard(self, keyboard_type: Optional[str] = None) -> ReplyKeyboardMarkup:
        """
        Constructs a ReplyKeyboardMarkup object with the main keyboard settings.

        Args:
            self: The instance of the Keyboard class.
            keyboard_type (Optional[str], optional): The type of keyboard to be constructed. Defaults to None.

        Returns:
            types.ReplyKeyboardMarkup: The constructed reply keyboard markup.
        """
        # Create a new ReplyKeyboardMarkup object with resize_keyboard set to True
        reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)

        # Check the keyboard type to determine which keyboard to construct
        if keyboard_type == 'docker_keyboard':
            # Construct the keyboard based on the docker settings
            keyboard_buttons = self.__construct_keyboard(config.docker_keyboard)
        else:
            # Construct the keyboard based on the main settings
            keyboard_buttons = self.__construct_keyboard(config.main_keyboard)

        # Add the constructed keyboard buttons to the reply keyboard
        reply_keyboard.add(*keyboard_buttons)

        return reply_keyboard

    @lru_cache
    def build_inline_keyboard(self, *button_texts: List[str] | str,
                              callback_data_prefix: Optional[str] = None,
                              callback_data: Optional[str] = None,
                              text_prefix: Optional[str] = None) -> InlineKeyboardMarkup:
        """
        Constructs an inline keyboard.

        Args:
            self: The instance of the Keyboard class.
            *button_texts: The text for the buttons in the inline keyboard.
            callback_data_prefix (Optional[str], optional): The prefix for the callback data. Defaults to None.
            callback_data (Optional[str], optional): The callback data. Defaults to None.
            text_prefix (Optional[str], optional): The prefix for the button text. Defaults to None.

        Returns:
            InlineKeyboardMarkup: The constructed inline keyboard.

        Raises:
            None

        Examples:
            >>> k = Keyboard()
            >>> k.build_inline_keyboard('Button 1', 'Button 2', callback_data='data', callback_data_prefix='p_')
            >>> # Returns an inline keyboard with two buttons and their respective callback data and text prefixes.
        """

        # Set the callback data prefix and callback data
        callback_data_prefix = callback_data_prefix or ''
        callback_data = callback_data or ''
        text_prefix = text_prefix or ''

        # Create a list of InlineKeyboardButton objects
        buttons = [
            InlineKeyboardButton(
                text=f"{text_prefix} {text}",
                callback_data=f'{callback_data_prefix}{callback_data or text.replace(" ", "_").lower()}'
            )
            for text in button_texts
        ]

        # Log the construction of the inline keyboard
        bot_logger.debug('Trying to build an inline keyboard...')
        bot_logger.debug(f'callback_data_prefix: "{callback_data_prefix}"')
        bot_logger.debug(f'callback_data: "{callback_data}"')
        bot_logger.debug(f'text_prefix: "{text_prefix}"')
        bot_logger.debug(f'button_texts: "{button_texts}"')
        bot_logger.debug('Building inline keyboard Done!')

        # Build the inline keyboard
        return InlineKeyboardMarkup([buttons])
