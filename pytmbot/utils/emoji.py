from functools import cached_property
from typing import Any


class EmojiConverter:
    @cached_property
    def emoji_library(self) -> Any:
        return __import__("emoji")

    def get_emoji(self, emoji_name: str) -> str:
        emoji_str = f":{emoji_name}:"
        return self.emoji_library.emojize(emoji_str)
