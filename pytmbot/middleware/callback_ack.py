#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Final

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.handler_backends import BaseMiddleware

from pytmbot.logs import BaseComponent


class CallbackAcknowledger(BaseMiddleware, BaseComponent):
    """
    Answer callback queries that handlers left unanswered.

    Telegram clients keep a progress indicator on a pressed inline button until
    the bot calls ``answerCallbackQuery``. Handlers only answer when they have
    something to show (an alert or a toast), so this middleware silently
    acknowledges every other callback once its handler has finished.
    """

    SUPPORTED_UPDATES: Final[list[str]] = ["callback_query"]
    DEFAULT_MAX_TRACKED: Final[int] = 4096
    ERROR_TEXT: Final[str] = "Something went wrong. Please try again."

    def __init__(self, bot: TeleBot, *, max_tracked: int = DEFAULT_MAX_TRACKED) -> None:
        if max_tracked <= 0:
            raise ValueError("max_tracked must be positive")

        BaseComponent.__init__(self)

        self.bot = bot
        self.update_types = self.SUPPORTED_UPDATES
        self.max_tracked = max_tracked
        self._answered: OrderedDict[str, None] = OrderedDict()
        self._lock = Lock()
        self._answer: Callable[..., object] = bot.answer_callback_query
        # Record every answer given anywhere in the bot, so post_process only
        # acknowledges callbacks that are still waiting.
        answer_method_name = "answer_callback_query"
        setattr(bot, answer_method_name, self._tracked_answer)

    def _remember(self, callback_query_id: object) -> None:
        with self._lock:
            key = str(callback_query_id)
            self._answered[key] = None
            self._answered.move_to_end(key)
            while len(self._answered) > self.max_tracked:
                self._answered.popitem(last=False)

    def _was_answered(self, callback_query_id: object) -> bool:
        key = str(callback_query_id)
        with self._lock:
            if key not in self._answered:
                return False
            del self._answered[key]
            return True

    def _tracked_answer(self, *args: object, **kwargs: object) -> object:
        callback_query_id = kwargs.get("callback_query_id", args[0] if args else None)
        if callback_query_id is not None:
            self._remember(callback_query_id)
        return self._answer(*args, **kwargs)

    # codeclone: ignore[dead-code]
    def pre_process(self, update: object, data: object) -> None:
        del update, data

    # codeclone: ignore[dead-code]
    def post_process(
        self,
        update: object,
        data: object,
        exception: Exception | None,
    ) -> None:
        del data
        callback_query_id = getattr(update, "id", None)
        if callback_query_id is None or self._was_answered(callback_query_id):
            return

        try:
            self._answer(
                callback_query_id=callback_query_id,
                text=None if exception is None else self.ERROR_TEXT,
            )
        except ApiTelegramException:
            # The query may have expired while a slow handler was running.
            with self.log_context(operation="post_process") as logger:
                logger.debug("bot.middleware.callback.ack.expired.debug")
