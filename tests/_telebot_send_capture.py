from __future__ import annotations

import pytest
from telebot import TeleBot

type PayloadScalar = str | int | float | bool | None
type PayloadValue = PayloadScalar | list["PayloadValue"] | dict[str, "PayloadValue"]
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

    def _send_message(
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        reply_markup: PayloadValue | None = None,
        **kwargs: PayloadValue,
    ) -> PayloadDict:
        del kwargs
        payload: PayloadDict = {
            "chat_id": int(chat_id),
            "text": text,
            "parse_mode": parse_mode,
        }
        if include_reply_markup:
            payload["reply_markup"] = reply_markup
        messages.append(payload)
        return payload

    monkeypatch.setattr(bot, "send_chat_action", _send_chat_action)
    monkeypatch.setattr(bot, "send_message", _send_message)
    return bot, actions, messages
