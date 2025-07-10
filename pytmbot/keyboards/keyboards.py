#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
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
    """A class for managing keyboard layouts and generation in the Telegram bot."""

    logger = Logger()

    def __init__(self) -> None:
        """Initialize the Keyboards class with an EmojiConverter instance."""
        self._emojis: EmojiConverter = EmojiConverter()

    def build_referer_main_keyboard(self, main_keyboard_data: str) -> ReplyKeyboardMarkup:
        """Construct a ReplyKeyboardMarkup object for the main keyboard."""
        if not main_keyboard_data or not isinstance(main_keyboard_data, str):
            raise ValueError("Invalid main keyboard data")

        with self.logger.context(operation=KeyboardOperation.BUILD_MAIN, data=main_keyboard_data):
            keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, selective=True)
            keyboard.add(main_keyboard_data)
            return keyboard

    def build_referer_inline_keyboard(self, data: str) -> InlineKeyboardMarkup:
        """Construct an InlineKeyboardMarkup object for the inline keyboard."""
        if not data or not isinstance(data, str):
            raise ValueError("Invalid inline keyboard data")

        with self.logger.context(operation=KeyboardOperation.BUILD_INLINE, data=data) as log:
            button_text = split_string_into_octets(data)
            log.debug("Split string into octets", result=button_text)

            button = InlineKeyboardButton(
                text=f"🦈 Return to {button_text}",
                callback_data=data[:64],
            )

            keyboard = InlineKeyboardMarkup()
            keyboard.add(button)
            return keyboard

    def build_reply_keyboard(
            self,
            keyboard_type: Optional[str] = None,
            plugin_keyboard_data: Optional[Dict[str, str]] = None,
    ) -> ReplyKeyboardMarkup:
        """Construct a ReplyKeyboardMarkup object with the specified keyboard settings."""
        with self.logger.context(
                operation=KeyboardOperation.BUILD_REPLY,
                keyboard_type=keyboard_type,
                has_plugin_data=bool(plugin_keyboard_data),
        ) as log:
            keyboard_data = (
                plugin_keyboard_data
                if plugin_keyboard_data
                else self._get_keyboard_data(keyboard_type)
            )

            keyboard_buttons = self._construct_keyboard(keyboard_data)
            if not keyboard_buttons:
                raise ValueError("Empty keyboard buttons configuration")

            if keyboard_type and keyboard_type != "back_keyboard":
                keyboard_buttons.append("⬅️ Back to main menu")

            reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
            for i in range(0, len(keyboard_buttons), 3):
                reply_keyboard.row(*keyboard_buttons[i:i + 3])

            log.debug("Reply keyboard constructed", total_buttons=len(keyboard_buttons))
            return reply_keyboard

    @staticmethod
    @lru_cache(maxsize=32)
    def _get_keyboard_data(keyboard_type: Optional[str]) -> Dict[str, str]:
        """Retrieve keyboard data based on the specified keyboard type."""
        logger = Logger()
        with logger.context(operation=KeyboardOperation.GET_DATA, keyboard_type=keyboard_type or "main") as log:
            if keyboard_type is None:
                return keyboard_settings.main_keyboard

            valid_keyboards = {
                attr for attr in dir(keyboard_settings)
                if attr.endswith("_keyboard") and not attr.startswith("_")
            }

            if keyboard_type not in valid_keyboards:
                log.error("Invalid keyboard type requested", code="KEYBOARD_INVALID_TYPE")
                raise AttributeError(f"Invalid keyboard type: {keyboard_type}")

            return getattr(keyboard_settings, keyboard_type)

    def _construct_keyboard(self, keyboard_data: Dict[str, str]) -> List[str]:
        """Construct a keyboard with emojis and titles."""
        if not isinstance(keyboard_data, dict):
            raise ValueError("Invalid keyboard data format")

        with self.logger.context(operation=KeyboardOperation.CONSTRUCT, button_count=len(keyboard_data)) as log:
            buttons = [
                f"{self._emojis.get_emoji(emoji)} {title}"
                for emoji, title in keyboard_data.items()
            ]
            log.debug("Keyboard buttons constructed", total=len(buttons))
            return buttons

    def build_inline_keyboard(self, buttons_data: Union[List[ButtonData], ButtonData]) -> InlineKeyboardMarkup:
        """Construct an InlineKeyboardMarkup with the provided button data."""
        with self.logger.context(
                operation=KeyboardOperation.BUILD_INLINE,
                buttons_count=1 if isinstance(buttons_data, ButtonData) else len(buttons_data),
        ) as log:
            if isinstance(buttons_data, ButtonData):
                buttons_data = [buttons_data]

            if not all(isinstance(btn, ButtonData) for btn in buttons_data):
                log.error("Invalid button data provided", code="INVALID_BUTTON_DATA")
                raise ValueError("All buttons must be ButtonData instances")

            keyboard = InlineKeyboardMarkup(row_width=2)
            buttons = [
                InlineKeyboardButton(text=btn.text, callback_data=btn.callback_data[:64])
                for btn in buttons_data
            ]
            keyboard.add(*buttons)

            log.debug("Inline keyboard built", total_buttons=len(buttons))
            return keyboard
