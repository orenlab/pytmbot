#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from functools import lru_cache
from typing import Dict, List, Optional, Union, NamedTuple

from telebot.types import InlineKeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup

from pytmbot.logs import bot_logger
from pytmbot.settings import BotSettings
from pytmbot.utils.utilities import EmojiConverter, split_string_into_octets

config = BotSettings()


class Keyboards:
    """
    A class for managing keyboard settings.
    """

    def __init__(self) -> None:
        """
        Initializes the Keyboard class.
        """
        # Initialize the emojis attribute with an instance of EmojiConverter
        self.emojis: EmojiConverter = EmojiConverter()

    @staticmethod
    def build_referer_main_keyboard(main_keyboard_data: str) -> ReplyKeyboardMarkup:
        """
        Constructs a ReplyKeyboardMarkup object with the main keyboard settings.

        Args:
            main_keyboard_data (str): The keyboard data for the main keyboard.

        Returns:
            ReplyKeyboardMarkup: The constructed reply keyboard markup.
        """
        bot_logger.debug(f'Constructing referer main keyboard with data: {main_keyboard_data}...')
        main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        main_keyboard.add(main_keyboard_data)

        return main_keyboard

    @staticmethod
    def build_referer_inline_keyboard(data: str) -> InlineKeyboardMarkup:
        """
        Constructs an InlineKeyboardMarkup object with the inline keyboard settings.

        Args:
            data (str): The keyboard data for the inline keyboard.

        Returns:
            InlineKeyboardMarkup: The constructed inline keyboard markup.
        """
        button_text = split_string_into_octets(data)

        bot_logger.debug(f'Constructing inline keyboard with data: {data}...')
        button = InlineKeyboardButton(text=f"🦈 Return to {button_text}",
                                      callback_data=data)

        keyboard = InlineKeyboardMarkup()
        keyboard.add(button)

        return keyboard

    @lru_cache(maxsize=None)
    def build_reply_keyboard(self, keyboard_type: Optional[str] = None) -> ReplyKeyboardMarkup:
        """
        Constructs a ReplyKeyboardMarkup object with the specified keyboard settings.

        Args:
            self: The instance of the Keyboard class.
            keyboard_type (Optional[str], optional): The type of keyboard to be constructed. Defaults to None.

        Returns:
            ReplyKeyboardMarkup: The constructed reply keyboard markup.
        """
        bot_logger.debug(f'Constructing reply keyboard whit type: {keyboard_type if keyboard_type else "main"}...')

        # Get the keyboard data based on the specified keyboard type
        keyboard_data = self._get_keyboard_data(keyboard_type)

        bot_logger.debug(f'Keyboard data: {keyboard_data}')

        keyboard_buttons = self._construct_keyboard(keyboard_data)

        if not keyboard_buttons:
            raise ValueError("Empty keyboard buttons")

        reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
        reply_keyboard.add(*keyboard_buttons)

        bot_logger.debug(f'Reply keyboard building Done!. Added {len(keyboard_buttons)} buttons to the keyboard')
        bot_logger.debug(f'Added {keyboard_type if keyboard_type else "main"} keyboard into cache...')

        # Return the constructed reply keyboard
        return reply_keyboard

    @staticmethod
    @lru_cache(maxsize=None)
    def _get_keyboard_data(keyboard_type: Optional[str]) -> Dict[str, str]:
        """
        Get keyboard data based on the specified keyboard type.

        Args:
            keyboard_type (Optional[str]): The type of keyboard to retrieve. If None, the main keyboard is returned.

        Returns:
            Dict[str, str]: The keyboard data as a dictionary.

        Raises:
            AttributeError: If an invalid keyboard type is specified.
        """
        # If no keyboard type is specified, return the main keyboard
        if keyboard_type is None:
            return config.main_keyboard

        # Get a list of valid keyboard attributes from the config module
        valid_keyboards = {attr for attr in dir(config) if attr.endswith('_keyboard')}

        # Check if the specified keyboard type is valid
        if keyboard_type not in valid_keyboards:
            raise AttributeError(f"Invalid keyboard type: {keyboard_type}")

        # Get the keyboard data from the config module using the specified keyboard type
        return getattr(config, keyboard_type)

    def _construct_keyboard(self, keyboard_data: Dict[str, str]) -> List[str]:
        """
        Constructs a keyboard with emojis and titles.

        Args:
            keyboard_data (Dict[str, str]): A dictionary containing emojis as keys and titles as values.

        Returns:
            List[str]: A list of strings representing the constructed keyboard.
        """
        # Iterate over the items in the keyboard_data dictionary
        return [
            # Format each item with the corresponding emoji and title
            f"{self.emojis.get_emoji(emoji)} {title}"
            for emoji, title in keyboard_data.items()
        ]

    class ButtonData(NamedTuple):
        """
        NamedTuple for storing button data.

        Args:
            text: str
            callback_data: str
        """
        text: str
        callback_data: str

    def build_inline_keyboard(self, buttons_data: Union[List[ButtonData], ButtonData]) -> InlineKeyboardMarkup:
        """
        Build an inline keyboard with the given button data.

        Args:
            buttons_data (Union[List[ButtonData], ButtonData]): The button data. Can be a single ButtonData or a list of
             ButtonData.

        Returns:
            InlineKeyboardMarkup: The inline keyboard.

        Raises:
            ValueError: If the button data is not in the correct format.
        """
        # If the input is a single ButtonData, convert it to a list
        if isinstance(buttons_data, self.ButtonData):
            buttons_data = [buttons_data]

        # Create a list of InlineKeyboardButton objects from the button data
        buttons = []
        for button_data in buttons_data:
            if not isinstance(button_data, self.ButtonData):
                raise ValueError("Each button data must be an instance of ButtonData.")

            button = InlineKeyboardButton(text=button_data.text, callback_data=button_data.callback_data)
            buttons.append(button)

        # Create an InlineKeyboardMarkup object and add the buttons to it
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(*buttons)

        return keyboard
