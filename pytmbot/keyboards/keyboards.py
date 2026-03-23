#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Final

from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)

from pytmbot.exceptions import KeyboardError
from pytmbot.logs import Logger
from pytmbot.settings import KeyboardSettings, keyboard_settings
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

    def __post_init__(self) -> None:
        """Validate button data after initialization."""
        if not self.text or not isinstance(self.text, str):
            raise ValueError("Button text must be a non-empty string")
        if not self.callback_data or not isinstance(self.callback_data, str):
            raise ValueError("Callback data must be a non-empty string")


def _resolve_keyboard_settings() -> KeyboardSettings:
    """Resolve lazily loaded keyboard settings with strict typing."""
    current_settings = keyboard_settings
    if not isinstance(current_settings, KeyboardSettings):
        raise KeyboardError("Keyboard settings are not initialized")
    return current_settings


def _new_inline_keyboard_markup(
    *, row_width: int | None = None
) -> InlineKeyboardMarkup:
    """Create InlineKeyboardMarkup via typed wrapper around telebot factory."""
    factory: Callable[..., InlineKeyboardMarkup] = InlineKeyboardMarkup
    if row_width is None:
        return factory()
    return factory(row_width=row_width)


class Keyboards:
    """A class for managing keyboard layouts and generation in the Telegram bot."""

    # Constants for magic numbers
    MAX_CALLBACK_DATA_LENGTH: Final[int] = 64
    DEFAULT_ROW_WIDTH: Final[int] = 3
    INLINE_ROW_WIDTH: Final[int] = 2
    CACHE_SIZE: Final[int] = 32
    BACK_BUTTON_TEXT: Final[str] = "⬅️ Back to main menu"
    RETURN_BUTTON_EMOJI: Final[str] = "🦈"

    __slots__ = ("_emojis", "_logger")

    def __init__(self) -> None:
        """Initialize the Keyboards class with an EmojiConverter instance."""
        self._emojis: EmojiConverter = EmojiConverter()
        self._logger: Logger = Logger()

    def build_referer_main_keyboard(
        self, main_keyboard_data: str
    ) -> ReplyKeyboardMarkup:
        """Construct a ReplyKeyboardMarkup object for the main keyboard.

        Args:
            main_keyboard_data: The text for the main keyboard button

        Returns:
            ReplyKeyboardMarkup: Configured main keyboard

        Raises:
            KeyboardError: If main_keyboard_data is invalid
        """
        if not main_keyboard_data or not isinstance(main_keyboard_data, str):
            raise KeyboardError("Main keyboard data must be a non-empty string")

        with self._logger.context(
            operation=KeyboardOperation.BUILD_MAIN, data=main_keyboard_data
        ):
            keyboard = ReplyKeyboardMarkup(
                resize_keyboard=True, one_time_keyboard=True, selective=True
            )
            keyboard.add(main_keyboard_data)
            return keyboard

    def build_referer_inline_keyboard(self, data: str) -> InlineKeyboardMarkup:
        """Construct an InlineKeyboardMarkup object for the inline keyboard.

        Args:
            data: The callback data for the button

        Returns:
            InlineKeyboardMarkup: Configured inline keyboard

        Raises:
            KeyboardError: If data is invalid
        """
        if not data or not isinstance(data, str):
            raise KeyboardError("Inline keyboard data must be a non-empty string")

        with self._logger.context(
            operation=KeyboardOperation.BUILD_INLINE, data=data
        ) as log:
            button_text = split_string_into_octets(data)
            log.debug("bot.keyboards.split.string.debug", result=button_text)

            button = InlineKeyboardButton(
                text=f"{self.RETURN_BUTTON_EMOJI} Return to {button_text}",
                callback_data=data[: self.MAX_CALLBACK_DATA_LENGTH],
            )

            keyboard = _new_inline_keyboard_markup()
            keyboard.add(button)
            return keyboard

    def build_reply_keyboard(
        self,
        keyboard_type: str | None = None,
        plugin_keyboard_data: dict[str, str] | None = None,
    ) -> ReplyKeyboardMarkup:
        """Construct a ReplyKeyboardMarkup object with the specified keyboard settings.

        Args:
            keyboard_type: Type of keyboard to build
            plugin_keyboard_data: Custom keyboard data for plugins

        Returns:
            ReplyKeyboardMarkup: Configured reply keyboard

        Raises:
            KeyboardError: If keyboard configuration is invalid
        """
        with self._logger.context(
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
                raise KeyboardError("Empty keyboard buttons configuration")

            # Add back button for non-back keyboards
            if keyboard_type and keyboard_type != "back_keyboard":
                keyboard_buttons.append(self.BACK_BUTTON_TEXT)

            reply_keyboard = ReplyKeyboardMarkup(
                resize_keyboard=True,
                row_width=self.DEFAULT_ROW_WIDTH,
                one_time_keyboard=False,
            )

            # Build rows with proper chunking
            for i in range(0, len(keyboard_buttons), self.DEFAULT_ROW_WIDTH):
                reply_keyboard.row(*keyboard_buttons[i : i + self.DEFAULT_ROW_WIDTH])

            log.trace(
                "bot.keyboards.reply.keyboard.debug",
                total_buttons=len(keyboard_buttons),
            )
            return reply_keyboard

    @staticmethod
    @lru_cache(maxsize=CACHE_SIZE)
    def _get_keyboard_data(keyboard_type: str | None) -> dict[str, str]:
        """Retrieve keyboard data based on the specified keyboard type.

        Args:
            keyboard_type: Type of keyboard to retrieve data for

        Returns:
            dict[str, str]: Keyboard configuration data

        Raises:
            KeyboardError: If keyboard type is invalid
        """
        logger = Logger()
        with logger.context(
            operation=KeyboardOperation.GET_DATA, keyboard_type=keyboard_type or "main"
        ) as log:
            settings_data = _resolve_keyboard_settings()
            keyboard_map: dict[str, dict[str, str]] = {
                "main_keyboard": settings_data.main_keyboard,
                "server_keyboard": settings_data.server_keyboard,
                "docker_keyboard": settings_data.docker_keyboard,
                "auth_keyboard": settings_data.auth_keyboard,
                "auth_processing_keyboard": settings_data.auth_processing_keyboard,
                "back_keyboard": settings_data.back_keyboard,
            }

            if keyboard_type is None:
                return keyboard_map["main_keyboard"]

            valid_keyboards = set(keyboard_map)

            if keyboard_type not in valid_keyboards:
                log.error(
                    "bot.keyboards.invalid.keyboard.fail",
                    code="KEYBOARD_INVALID_TYPE",
                    requested_type=keyboard_type,
                    valid_types=list(valid_keyboards),
                )
                raise KeyboardError(
                    f"Invalid keyboard type '{keyboard_type}'. "
                    f"Valid types: {', '.join(sorted(valid_keyboards))}"
                )

            return keyboard_map[keyboard_type]

    def _construct_keyboard(self, keyboard_data: dict[str, str]) -> list[str]:
        """Construct a keyboard with emojis and titles.

        Args:
            keyboard_data: Dictionary mapping emoji keys to button titles

        Returns:
            list[str]: List of formatted button texts

        Raises:
            KeyboardError: If keyboard data format is invalid
        """
        if not isinstance(keyboard_data, dict):
            raise KeyboardError("Keyboard data must be a dictionary")

        if not keyboard_data:
            raise KeyboardError("Keyboard data cannot be empty")

        with self._logger.context(
            operation=KeyboardOperation.CONSTRUCT, button_count=len(keyboard_data)
        ) as log:
            buttons = [
                f"{self._emojis.get_emoji(emoji)} {title}"
                for emoji, title in keyboard_data.items()
                if emoji and title  # Skip empty entries
            ]

            log.trace("bot.keyboards.keyboard.buttons.debug", total=len(buttons))
            return buttons

    def build_inline_keyboard(
        self, buttons_data: list[ButtonData] | ButtonData
    ) -> InlineKeyboardMarkup:
        """Construct an InlineKeyboardMarkup with the provided button data.

        Args:
            buttons_data: Button data for inline keyboard

        Returns:
            InlineKeyboardMarkup: Configured inline keyboard

        Raises:
            KeyboardError: If button data is invalid
        """
        # Normalize input to list
        if isinstance(buttons_data, ButtonData):
            buttons_data = [buttons_data]

        if not buttons_data:
            raise KeyboardError("Button data cannot be empty")

        with self._logger.context(
            operation=KeyboardOperation.BUILD_INLINE,
            buttons_count=len(buttons_data),
        ) as log:
            # Validate all buttons are ButtonData instances
            if not all(isinstance(btn, ButtonData) for btn in buttons_data):
                log.error(
                    "bot.keyboards.invalid.button.fail", code="INVALID_BUTTON_DATA"
                )
                raise KeyboardError("All buttons must be ButtonData instances")

            keyboard = _new_inline_keyboard_markup(row_width=self.INLINE_ROW_WIDTH)
            buttons = [
                InlineKeyboardButton(
                    text=btn.text,
                    callback_data=btn.callback_data[: self.MAX_CALLBACK_DATA_LENGTH],
                )
                for btn in buttons_data
            ]
            keyboard.add(*buttons)

            log.trace("bot.keyboards.inline.keyboard.debug", total_buttons=len(buttons))
            return keyboard
