from __future__ import annotations

from typing import Any, Final

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InputRichMessage, Message

from pytmbot.handlers.handlers_util.utils import (
    NAV_KEYBOARD_SYNC_TEXT,
    send_bot_message,
)
from pytmbot.keyboards.keyboards import (
    NAV_DOCKER,
    NAV_MAIN,
    NAV_SERVER,
    ReplyMarkupType,
    build_nav_keyboard,
    resolve_reply_markup,
)

# Arguments accepted by TeleBot.send_rich_message (classic send_message kwargs
# like parse_mode / link_preview_options must not be forwarded).
_SEND_RICH_MESSAGE_KWARGS: Final[frozenset[str]] = frozenset(
    {
        "business_connection_id",
        "message_thread_id",
        "direct_messages_topic_id",
        "disable_notification",
        "protect_content",
        "allow_paid_broadcast",
        "message_effect_id",
        "suggested_post_parameters",
        "reply_parameters",
    }
)


def _filter_send_rich_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep only kwargs supported by ``TeleBot.send_rich_message``."""
    return {
        key: value
        for key, value in kwargs.items()
        if key in _SEND_RICH_MESSAGE_KWARGS and value is not None
    }


def build_rich_html_message(
    html: str,
    *,
    skip_entity_detection: bool = True,
) -> InputRichMessage:
    """
    Build an InputRichMessage from rich-HTML content.

    Entity auto-detection is skipped by default so metrics, paths, and IDs are
    not misread as URLs, phones, or mentions.
    """
    return InputRichMessage(
        html=html,
        skip_entity_detection=skip_entity_detection,
    )


def send_rich_bot_message(
    bot: TeleBot,
    chat_id: int,
    html: str,
    *,
    reply_markup: ReplyMarkupType | None = None,
    nav_keyboard: str | None = None,
    skip_entity_detection: bool = True,
    **kwargs: Any,
) -> Message:
    """
    Send a rich HTML message, optionally preserving the navigation reply keyboard.

    When both an inline keyboard and ``nav_keyboard`` are requested, the rich
    content message keeps the inline actions and a short follow-up re-attaches
    the section reply keyboard (notably for iOS clients).
    """
    rich_message = build_rich_html_message(
        html,
        skip_entity_detection=skip_entity_detection,
    )
    rich_kwargs = _filter_send_rich_kwargs(kwargs)

    if isinstance(reply_markup, InlineKeyboardMarkup) and nav_keyboard is not None:
        message = bot.send_rich_message(
            chat_id=chat_id,
            rich_message=rich_message,
            reply_markup=reply_markup,
            **rich_kwargs,
        )
        bot.send_message(
            chat_id=chat_id,
            text=NAV_KEYBOARD_SYNC_TEXT,
            reply_markup=build_nav_keyboard(nav_keyboard),
            disable_notification=True,
        )
        return message

    return bot.send_rich_message(
        chat_id=chat_id,
        rich_message=rich_message,
        reply_markup=resolve_reply_markup(reply_markup, nav_keyboard=nav_keyboard),
        **rich_kwargs,
    )


def send_rich_main_message(
    bot: TeleBot,
    chat_id: int,
    html: str,
    **kwargs: Any,
) -> Message:
    """Send a rich message while keeping the main menu reply keyboard visible."""
    return send_rich_bot_message(bot, chat_id, html, nav_keyboard=NAV_MAIN, **kwargs)


def send_rich_server_message(
    bot: TeleBot,
    chat_id: int,
    html: str,
    **kwargs: Any,
) -> Message:
    """Send a rich message while keeping the server section reply keyboard visible."""
    return send_rich_bot_message(bot, chat_id, html, nav_keyboard=NAV_SERVER, **kwargs)


def send_rich_docker_message(
    bot: TeleBot,
    chat_id: int,
    html: str,
    **kwargs: Any,
) -> Message:
    """Send a rich message while keeping the docker section reply keyboard visible."""
    return send_rich_bot_message(bot, chat_id, html, nav_keyboard=NAV_DOCKER, **kwargs)


__all__ = [
    "build_rich_html_message",
    "send_rich_bot_message",
    "send_rich_docker_message",
    "send_rich_main_message",
    "send_rich_server_message",
    # Re-export for callers that mix classic and rich sends.
    "send_bot_message",
]
