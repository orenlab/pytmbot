#!/usr/bin/env python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Dict, List, Optional, Union

from telebot.types import (
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
)

from pytmbot.logs import Logger
from pytmbot.settings import keyboard_settings
from pytmbot.utils import EmojiConverter, split_string_into_octets


class KeyboardOperation(StrEnum):
    BUILD_MAIN = "build_main_keyboard"
    BUILD_INLINE = "build_inline_keyboard"
    BUILD_REPLY = "build_reply_keyboard"
    GET_DATA = "get_keyboard_data"
    CONSTRUCT = "construct_keyboard"


@dataclass(frozen=True, slots=True)
class ButtonData:
    """Immutable data class for storing button information with memory optimization."""
    text: str
    callback_data: str


class Keyboards:
    """
    A class for managing keyboard layouts and generation in the Telegram bot.
    Thread-safe implementation with immutable state.
    """
    logger = Logger()

    def __init__(self) -> None:
        """Initialize the Keyboards class with an EmojiConverter instance."""
        self._emojis: EmojiConverter = EmojiConverter()

    def build_referer_main_keyboard(self, main_keyboard_data: str) -> ReplyKeyboardMarkup:
        """
        Construct a ReplyKeyboardMarkup object for the main keyboard.

        Args:
            main_keyboard_data (str): Data for the main keyboard.

        Returns:
            ReplyKeyboardMarkup: The constructed reply keyboard markup.

        Raises:
            ValueError: If main_keyboard_data is empty or invalid.
        """
        if not main_keyboard_data or not isinstance(main_keyboard_data, str):
            raise ValueError("Invalid main keyboard data")

        with self.logger.context(
                operation=KeyboardOperation.BUILD_MAIN,
                data=main_keyboard_data
        ):
            keyboard = ReplyKeyboardMarkup(
                resize_keyboard=True,
                one_time_keyboard=True,
                selective=True
            )
            keyboard.add(main_keyboard_data)
            self.logger.debug("Main keyboard constructed successfully")
            return keyboard

    def build_referer_inline_keyboard(self, data: str) -> InlineKeyboardMarkup:
        """
        Construct an InlineKeyboardMarkup object for the inline keyboard.

        Args:
            data (str): Data for the inline keyboard.

        Returns:
            InlineKeyboardMarkup: The constructed inline keyboard markup.

        Raises:
            ValueError: If data is empty or invalid.
        """
        if not data or not isinstance(data, str):
            raise ValueError("Invalid inline keyboard data")

        with self.logger.context(
                operation=KeyboardOperation.BUILD_INLINE,
                data=data
        ) as log:
            button_text = split_string_into_octets(data)
            log.debug(f"Formatted button text: {button_text}")

            button = InlineKeyboardButton(
                text=f"🦈 Return to {button_text}",
                callback_data=data[:64]  # Telegram limit
            )

            keyboard = InlineKeyboardMarkup()
            keyboard.add(button)
            return keyboard

    def build_reply_keyboard(
            self,
            keyboard_type: Optional[str] = None,
            plugin_keyboard_data: Optional[Dict[str, str]] = None,
    ) -> ReplyKeyboardMarkup:
        """
        Construct a ReplyKeyboardMarkup object with the specified keyboard settings.

        Args:
            keyboard_type: The type of keyboard to construct.
            plugin_keyboard_data: Optional custom keyboard data.

        Returns:
            ReplyKeyboardMarkup: The constructed reply keyboard markup.

        Raises:
            ValueError: If keyboard configuration is invalid.
        """
        with self.logger.context(
                operation=KeyboardOperation.BUILD_REPLY,
                keyboard_type=keyboard_type,
                has_plugin_data=bool(plugin_keyboard_data)
        ) as log:
            keyboard_data = (
                plugin_keyboard_data
                if plugin_keyboard_data
                else self._get_keyboard_data(keyboard_type)
            )
            log.debug(f"Loaded keyboard data: {keyboard_data}")

            keyboard_buttons = self._construct_keyboard(keyboard_data)
            if not keyboard_buttons:
                raise ValueError("Empty keyboard buttons configuration")

            if keyboard_type and keyboard_type != "back_keyboard":
                keyboard_buttons.append("⬅️ Back to main menu")

            reply_keyboard = ReplyKeyboardMarkup(
                resize_keyboard=True,
                row_width=3
            )

            # Group buttons into pairs for better layout
            for i in range(0, len(keyboard_buttons), 3):
                buttons_row = keyboard_buttons[i:i + 3]
                reply_keyboard.row(*buttons_row)

            log.debug(f"Reply keyboard constructed with {len(keyboard_buttons)} buttons")
            return reply_keyboard

    @staticmethod
    @lru_cache(maxsize=32)
    def _get_keyboard_data(keyboard_type: Optional[str]) -> Dict[str, str]:
        """
        Retrieve keyboard data based on the specified keyboard type.

        Args:
            keyboard_type: The type of keyboard to retrieve.

        Returns:
            Dict[str, str]: The keyboard configuration data.

        Raises:
            AttributeError: If the keyboard type is invalid.
        """
        logger = Logger()
        with logger.context(
                operation=KeyboardOperation.GET_DATA,
                keyboard_type=keyboard_type or "main"
        ) as log:
            if keyboard_type is None:
                return keyboard_settings.main_keyboard

            valid_keyboards = {
                attr for attr in dir(keyboard_settings)
                if attr.endswith("_keyboard") and not attr.startswith("_")
            }

            if keyboard_type not in valid_keyboards:
                log.error(f"Invalid keyboard type requested: {keyboard_type}")
                raise AttributeError(f"Invalid keyboard type: {keyboard_type}")

            return getattr(keyboard_settings, keyboard_type)

    def _construct_keyboard(self, keyboard_data: Dict[str, str]) -> List[str]:
        """
        Construct a keyboard with emojis and titles.

        Args:
            keyboard_data: Dictionary containing emojis and titles.

        Returns:
            List[str]: List of constructed keyboard button texts.

        Raises:
            ValueError: If keyboard_data is invalid.
        """
        if not isinstance(keyboard_data, dict):
            raise ValueError("Invalid keyboard data format")

        with self.logger.context(
                operation=KeyboardOperation.CONSTRUCT,
                button_count=len(keyboard_data)
        ) as log:
            buttons = [
                f"{self._emojis.get_emoji(emoji)} {title}"
                for emoji, title in keyboard_data.items()
            ]
            log.debug(f"Constructed {len(buttons)} keyboard buttons")
            return buttons

    def build_inline_keyboard(
            self,
            buttons_data: Union[List[ButtonData], ButtonData]
    ) -> InlineKeyboardMarkup:
        """
        Construct an InlineKeyboardMarkup with the provided button data.

        Args:
            buttons_data: Single ButtonData or list of ButtonData objects.

        Returns:
            InlineKeyboardMarkup: The constructed inline keyboard markup.

        Raises:
            ValueError: If button data is invalid.
        """
        with self.logger.context(
                operation=KeyboardOperation.BUILD_INLINE,
                buttons_count=1 if isinstance(buttons_data, ButtonData) else len(buttons_data)
        ) as log:
            if isinstance(buttons_data, ButtonData):
                buttons_data = [buttons_data]

            if not all(isinstance(btn, ButtonData) for btn in buttons_data):
                log.error("Invalid button data provided")
                raise ValueError("All buttons must be ButtonData instances")

            keyboard = InlineKeyboardMarkup(row_width=2)
            buttons = [
                InlineKeyboardButton(
                    text=btn.text,
                    callback_data=btn.callback_data[:64]
                )
                for btn in buttons_data
            ]
            keyboard.add(*buttons)

            log.debug(f"Inline keyboard constructed with {len(buttons)} buttons")
            return keyboard
