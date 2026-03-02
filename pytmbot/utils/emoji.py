#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from functools import cached_property
from importlib import import_module
from typing import Protocol, runtime_checkable


@runtime_checkable
class _EmojiModule(Protocol):
    def emojize(self, text: str) -> str: ...


class EmojiConverter:
    @cached_property
    def emoji_library(self) -> _EmojiModule:
        library = import_module("emoji")
        if not isinstance(library, _EmojiModule):
            raise TypeError("emoji module does not expose emojize(str) -> str")
        return library

    def get_emoji(self, emoji_name: str) -> str:
        emoji_str = f":{emoji_name}:"
        return str(self.emoji_library.emojize(emoji_str))
