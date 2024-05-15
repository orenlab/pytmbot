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
    Creates keyboard from keyboard config
    @param keyboard: dictionary
    @return: list of key (emoji) and value (string)
    """
    keyboard_value = []
    for emoji, title in keyboard.items():
        keyboard_value.append(get_emoji(emoji) + ' ' + title)
    return keyboard_value


class Keyboard:
    """Class for build keyboard object (reply and inline keyboard)"""

    def __init__(self):
        self.kb = KeyboardSettings()

    @lru_cache
    def build_reply_keyboard(self) -> types.ReplyKeyboardMarkup:
        """Build reply (main) keyboard"""
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard = keyboard_constructor(self.kb.main_keyboard)
        markup.add(*keyboard)
        return markup

    @lru_cache
    def build_inline_keyboard(self, button_name: str, callback_data: str) -> types.InlineKeyboardMarkup:
        """Build inline keyboard"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text=button_name, callback_data=callback_data))
        return markup
