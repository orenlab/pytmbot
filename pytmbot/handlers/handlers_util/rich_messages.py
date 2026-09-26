from __future__ import annotations

from typing import Any, Final

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InputRichMessage, Message

from pytmbot.handlers.handlers_util.utils import (
    NAV_KEYBOARD_SYNC_TEXT,
    send_bot_message,
    truncate_telegram_text,
)
from pytmbot.keyboards.keyboards import (
    NAV_DOCKER,
    NAV_MAIN,
    NAV_SERVER,
    ReplyMarkupType,
    build_nav_keyboard,
    resolve_reply_markup,
)
from pytmbot.logs import Logger
from pytmbot.utils.rich_html import (
    fit_rich_html,
    measure_rich_html,
    rich_html_to_plain_text,
    rich_paragraphs,
)

logger = Logger()

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
# Classic send_message accepts these too, so they survive a plain-text fallback.
_CLASSIC_FALLBACK_KWARGS: Final[frozenset[str]] = frozenset(
    {
        "business_connection_id",
        "message_thread_id",
        "disable_notification",
        "protect_content",
        "reply_parameters",
    }
)


def _filter_kwargs(kwargs: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    return {
        key: value
        for key, value in kwargs.items()
        if key in allowed and value is not None
    }


def _filter_send_rich_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep only kwargs supported by ``TeleBot.send_rich_message``."""
    return _filter_kwargs(kwargs, _SEND_RICH_MESSAGE_KWARGS)


def build_rich_html_message(
    html: str,
    *,
    skip_entity_detection: bool = True,
) -> InputRichMessage:
    """
    Build an InputRichMessage from rich-HTML content.

    Plain text without markup is wrapped into escaped paragraphs. Content that
    exceeds Telegram rich-message limits (text length, blocks, nesting, table
    width) is trimmed at a structural boundary with a notice. Entity
    auto-detection is skipped by default so metrics, paths, and IDs are not
    misread as URLs, phones, or mentions.
    """
    if "<" not in html:
        html = rich_paragraphs(html) or "<p>…</p>"
    fitted_html = fit_rich_html(html)
    if fitted_html is not html:
        metrics = measure_rich_html(html)
        logger.warning(
            "bot.handler.handlers_util.rich_messages.truncated.warn",
            text_length=metrics.text_length,
            blocks=metrics.blocks,
            max_depth=metrics.max_depth,
            max_table_columns=metrics.max_table_columns,
        )
    return InputRichMessage(
        html=fitted_html,
        skip_entity_detection=skip_entity_detection,
    )


# 400 errors that a plain-text retry cannot fix (target or markup problems).
_NON_CONTENT_ERROR_MARKERS: Final[tuple[str, ...]] = (
    "chat not found",
    "thread not found",
    "button",
    "reply markup",
    "not enough rights",
)


def _is_rich_content_rejection(error: ApiTelegramException) -> bool:
    """Return True for Telegram 400 errors caused by the rich payload itself."""
    if getattr(error, "error_code", None) != 400:
        return False
    description = str(getattr(error, "description", error)).lower()
    return not any(marker in description for marker in _NON_CONTENT_ERROR_MARKERS)


def _send_plain_text_fallback(
    bot: TeleBot,
    chat_id: int,
    html: str,
    *,
    reply_markup: ReplyMarkupType | None,
    nav_keyboard: str | None,
    kwargs: dict[str, Any],
) -> Message:
    return send_bot_message(
        bot,
        chat_id,
        truncate_telegram_text(rich_html_to_plain_text(html) or "…"),
        reply_markup=reply_markup,
        nav_keyboard=nav_keyboard,
        **_filter_kwargs(kwargs, _CLASSIC_FALLBACK_KWARGS),
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

    If Telegram rejects the rich payload (HTTP 400), the same content is sent
    once more as a classic plain-text message so the user still gets an answer.
    """
    rich_message = build_rich_html_message(
        html,
        skip_entity_detection=skip_entity_detection,
    )
    rich_kwargs = _filter_send_rich_kwargs(kwargs)
    sync_nav_keyboard = (
        isinstance(reply_markup, InlineKeyboardMarkup) and nav_keyboard is not None
    )

    try:
        if sync_nav_keyboard:
            message = bot.send_rich_message(
                chat_id=chat_id,
                rich_message=rich_message,
                reply_markup=reply_markup,
                **rich_kwargs,
            )
        else:
            message = bot.send_rich_message(
                chat_id=chat_id,
                rich_message=rich_message,
                reply_markup=resolve_reply_markup(
                    reply_markup, nav_keyboard=nav_keyboard
                ),
                **rich_kwargs,
            )
    except ApiTelegramException as error:
        if not _is_rich_content_rejection(error):
            raise
        logger.warning(
            "bot.handler.handlers_util.rich_messages.rejected.warn",
            error=str(getattr(error, "description", error)),
        )
        return _send_plain_text_fallback(
            bot,
            chat_id,
            rich_message.html or html,
            reply_markup=reply_markup,
            nav_keyboard=nav_keyboard,
            kwargs=kwargs,
        )

    if sync_nav_keyboard and nav_keyboard is not None:
        bot.send_message(
            chat_id=chat_id,
            text=NAV_KEYBOARD_SYNC_TEXT,
            reply_markup=build_nav_keyboard(nav_keyboard),
            disable_notification=True,
        )
    return message


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
