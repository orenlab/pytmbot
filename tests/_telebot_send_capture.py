from __future__ import annotations

from typing import Any

import pytest
from telebot import TeleBot
from telebot.types import InputRichMessage

type PayloadScalar = str | int | float | bool | None
type PayloadValue = (
    PayloadScalar | list["PayloadValue"] | dict[str, "PayloadValue"] | Any
)
type PayloadDict = dict[str, PayloadValue]


def build_bot_capture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    include_reply_markup: bool = False,
) -> tuple[TeleBot, list[tuple[int, str]], list[PayloadDict]]:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    actions: list[tuple[int, str]] = []
    messages: list[PayloadDict] = []

    def _send_chat_action(
        chat_id: int | str,
        action: str,
        timeout: int | None = None,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> bool:
        del timeout, message_thread_id, business_connection_id
        actions.append((int(chat_id), action))
        return True

    def _append_message(
        *,
        chat_id: int | str,
        text: str | None = None,
        parse_mode: str | None = None,
        reply_markup: PayloadValue | None = None,
        rich_message: InputRichMessage | None = None,
        disable_notification: PayloadValue | None = None,
    ) -> PayloadDict:
        payload: PayloadDict = {
            "chat_id": int(chat_id),
            "parse_mode": parse_mode,
        }
        if text is not None:
            payload["text"] = text
        if rich_message is not None:
            payload["rich_message"] = rich_message
            payload["text"] = getattr(rich_message, "html", None) or text
        if include_reply_markup:
            payload["reply_markup"] = reply_markup
        if disable_notification is not None:
            payload["disable_notification"] = disable_notification
        messages.append(payload)
        return payload

    def _send_message(
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        reply_markup: PayloadValue | None = None,
        **kwargs: PayloadValue,
    ) -> PayloadDict:
        return _append_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_notification=kwargs.get("disable_notification"),
        )

    def _send_rich_message(
        chat_id: int | str,
        rich_message: InputRichMessage,
        reply_markup: PayloadValue | None = None,
        **kwargs: PayloadValue,
    ) -> PayloadDict:
        return _append_message(
            chat_id=chat_id,
            rich_message=rich_message,
            reply_markup=reply_markup,
            disable_notification=kwargs.get("disable_notification"),
        )

    monkeypatch.setattr(bot, "send_chat_action", _send_chat_action)
    monkeypatch.setattr(bot, "send_message", _send_message)
    monkeypatch.setattr(bot, "send_rich_message", _send_rich_message)
    return bot, actions, messages
