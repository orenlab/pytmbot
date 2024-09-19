#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from functools import lru_cache
from typing import Dict, List, Optional, Union, NamedTuple

from telebot.types import (
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
)

from pytmbot.logs import bot_logger
from pytmbot.settings import keyboard_settings
from pytmbot.utils.utilities import EmojiConverter, split_string_into_octets


class Keyboards:
    """
    A class for managing keyboard settings.
    """

    def __init__(self) -> None:
        """
        Initializes the Keyboards class with an EmojiConverter instance.
        """
        self.emojis: EmojiConverter = EmojiConverter()

    @staticmethod
    def build_referer_main_keyboard(main_keyboard_data: str) -> ReplyKeyboardMarkup:
        """
        Constructs a ReplyKeyboardMarkup object for the main keyboard.

        Args:
            main_keyboard_data (str): Data for the main keyboard.

        Returns:
            ReplyKeyboardMarkup: The constructed reply keyboard markup.
        """
        bot_logger.debug(
            f"Building referer main keyboard with data: {main_keyboard_data}"
        )

        main_keyboard = ReplyKeyboardMarkup(
            resize_keyboard=True, one_time_keyboard=True
        )
        main_keyboard.add(main_keyboard_data)

        bot_logger.info("Referer main keyboard constructed successfully.")
        return main_keyboard

    @staticmethod
    def build_referer_inline_keyboard(data: str) -> InlineKeyboardMarkup:
        """
        Constructs an InlineKeyboardMarkup object for the inline keyboard.

        Args:
            data (str): Data for the inline keyboard.

        Returns:
            InlineKeyboardMarkup: The constructed inline keyboard markup.
        """
        bot_logger.debug(f"Building inline keyboard with raw data: {data}")

        button_text = split_string_into_octets(data)
        bot_logger.debug(f"Formatted button text: {button_text}")

        button = InlineKeyboardButton(
            text=f"🦈 Return to {button_text}", callback_data=data
        )

        keyboard = InlineKeyboardMarkup()
        keyboard.add(button)

        bot_logger.info(
            f"Inline keyboard for '{button_text}' constructed successfully."
        )
        return keyboard

    def build_reply_keyboard(
        self,
        keyboard_type: Optional[str] = None,
        plugin_keyboard_data: Optional[dict[str, str]] = None,
    ) -> ReplyKeyboardMarkup:
        """
        Constructs a ReplyKeyboardMarkup object with the specified keyboard settings.

        Args:
            keyboard_type (Optional[str]): The type of keyboard to construct. Defaults to None.
            plugin_keyboard_data (Optional[dict[str, str]]): Data for the keyboard. Defaults to None.

        Returns:
            ReplyKeyboardMarkup: The constructed reply keyboard markup.

        Raises:
            ValueError: If the keyboard buttons are empty.
        """
        bot_logger.debug(
            f"Building reply keyboard. Keyboard type: {keyboard_type if keyboard_type else 'main'}"
        )

        keyboard_data = (
            plugin_keyboard_data
            if plugin_keyboard_data
            else self._get_keyboard_data(keyboard_type)
        )
        bot_logger.debug(f"Keyboard data loaded: {keyboard_data}")

        keyboard_buttons = self._construct_keyboard(keyboard_data)

        if not keyboard_buttons:
            bot_logger.error(
                "Reply keyboard construction failed: Empty keyboard buttons"
            )
            raise ValueError("Empty keyboard buttons")

        reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
        reply_keyboard.add(*keyboard_buttons)

        bot_logger.info(
            f"Reply keyboard with {len(keyboard_buttons)} buttons constructed successfully."
        )
        return reply_keyboard

    @staticmethod
    @lru_cache(maxsize=None)
    def _get_keyboard_data(keyboard_type: Optional[str]) -> Dict[str, str]:
        """
        Retrieves keyboard data based on the specified keyboard type.

        Args:
            keyboard_type (Optional[str]): The type of keyboard. If None, returns the main keyboard.

        Returns:
            Dict[str, str]: The keyboard data.

        Raises:
            AttributeError: If the keyboard type is invalid.
        """
        bot_logger.debug(
            f"Fetching keyboard data for type: {keyboard_type if keyboard_type else 'main'}"
        )
        match keyboard_type:
            case None:
                return keyboard_settings.main_keyboard
            case _ if keyboard_type in {
                attr for attr in dir(keyboard_settings) if attr.endswith("_keyboard")
            }:
                bot_logger.debug(f"Valid keyboard type '{keyboard_type}' found.")
                return getattr(keyboard_settings, keyboard_type)
            case _:
                bot_logger.error(f"Invalid keyboard type: {keyboard_type}")
                raise AttributeError(f"Invalid keyboard type: {keyboard_type}")

    def _construct_keyboard(self, keyboard_data: Dict[str, str]) -> List[str]:
        """
        Constructs a keyboard with emojis and titles.

        Args:
            keyboard_data (Dict[str, str]): Data containing emojis and titles.

        Returns:
            List[str]: A list of strings representing the constructed keyboard.
        """
        bot_logger.debug(f"Constructing keyboard with data: {keyboard_data}")
        constructed_keyboard = [
            f"{self.emojis.get_emoji(emoji)} {title}"
            for emoji, title in keyboard_data.items()
        ]
        bot_logger.info(
            f"Constructed keyboard with {len(constructed_keyboard)} buttons."
        )
        return constructed_keyboard

    class ButtonData(NamedTuple):
        """
        NamedTuple for storing button data.

        Args:
            text (str): Button text.
            callback_data (str): Data associated with the button callback.
        """

        text: str
        callback_data: str

    def build_inline_keyboard(
        self, buttons_data: Union[List[ButtonData], ButtonData]
    ) -> InlineKeyboardMarkup:
        """
        Constructs an InlineKeyboardMarkup object for the inline keyboard.

        Args:
            buttons_data (Union[List[ButtonData], ButtonData]): Data for the inline keyboard buttons.

        Returns:
            InlineKeyboardMarkup: The constructed inline keyboard markup.

        Raises:
            ValueError: If the button data is not an instance of ButtonData.
        """
        bot_logger.debug(f"Building inline keyboard with buttons: {buttons_data}")

        try:
            if isinstance(buttons_data, self.ButtonData):
                buttons_data = [buttons_data]

            buttons = []
            for button_data in buttons_data:
                if not isinstance(button_data, self.ButtonData):
                    bot_logger.error(f"Invalid button data type: {type(button_data)}")
                    raise ValueError(
                        "Each button data must be an instance of ButtonData."
                    )

                button = InlineKeyboardButton(
                    text=button_data.text, callback_data=button_data.callback_data
                )
                buttons.append(button)

            keyboard = InlineKeyboardMarkup(row_width=2)
            keyboard.add(*buttons)

            bot_logger.info(
                f"Inline keyboard with {len(buttons)} buttons constructed successfully."
            )
            return keyboard

        except Exception as e:
            bot_logger.error(f"Error occurred while building inline keyboard: {e}")
            raise
