#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import time
from collections import deque
from threading import RLock
from typing import Final, TypedDict

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import CallbackQuery, Message

from pytmbot.logs import BaseComponent

type DedupKey = str
type MonotonicSeconds = float


class UpdateDedupStats(TypedDict):
    cache_size: int
    queue_size: int
    dropped_duplicates: int
    accepted_updates: int
    ttl_seconds: float
    max_entries: int


class UpdateDedup(BaseMiddleware, BaseComponent):
    """Drop duplicate updates/callbacks inside a small bounded TTL cache."""

    SUPPORTED_UPDATES: Final[list[str]] = ["message", "callback_query"]
    DEFAULT_TTL_SECONDS: Final[float] = 120.0
    DEFAULT_MAX_ENTRIES: Final[int] = 8192

    def __init__(
        self,
        bot: TeleBot,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")

        BaseComponent.__init__(self)

        self.bot = bot
        self.update_types = self.SUPPORTED_UPDATES
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

        self._entries: dict[DedupKey, MonotonicSeconds] = {}
        self._queue: deque[tuple[DedupKey, MonotonicSeconds]] = deque()
        self._state_lock = RLock()
        self._dropped_duplicates = 0
        self._accepted_updates = 0

        with self.log_context(
            operation="initialization",
            ttl_seconds=self.ttl_seconds,
            max_entries=self.max_entries,
            supported_updates=self.SUPPORTED_UPDATES,
        ) as logger:
            logger.info("bot.middleware.update.dedup.init")

    @staticmethod
    def _extract_update_id(update: object) -> int | None:
        update_id = getattr(update, "update_id", None)
        if isinstance(update_id, int) and update_id >= 0:
            return update_id
        return None

    @staticmethod
    def _extract_message_key(update: object) -> str | None:
        if not isinstance(update, Message):
            return None

        chat = getattr(update, "chat", None)
        chat_id = getattr(chat, "id", None)
        message_id = getattr(update, "message_id", None)
        if isinstance(chat_id, int) and isinstance(message_id, int):
            return f"msg:{chat_id}:{message_id}"
        return None

    @staticmethod
    def _extract_callback_key(update: object) -> str | None:
        if not isinstance(update, CallbackQuery):
            return None
        callback_id = update.id
        if not callback_id:
            return None
        return f"cb:{callback_id}"

    def _build_dedup_key(self, update: object) -> str | None:
        callback_key = self._extract_callback_key(update)
        if callback_key is not None:
            return callback_key

        update_id = self._extract_update_id(update)
        if update_id is not None:
            return f"upd:{update_id}"

        return self._extract_message_key(update)

    def _prune_locked(self, now: MonotonicSeconds) -> None:
        while self._queue:
            queued_key, queued_expiry = self._queue[0]
            current_expiry = self._entries.get(queued_key)

            is_stale_queue_entry = (
                current_expiry is None or current_expiry != queued_expiry
            )
            is_expired = (
                current_expiry is not None
                and current_expiry == queued_expiry
                and current_expiry <= now
            )
            is_over_capacity = len(self._entries) > self.max_entries

            if not (is_stale_queue_entry or is_expired or is_over_capacity):
                break

            self._queue.popleft()
            if is_expired or (is_over_capacity and current_expiry == queued_expiry):
                self._entries.pop(queued_key, None)

    def _check_and_register(self, key: DedupKey, now: MonotonicSeconds) -> bool:
        with self._state_lock:
            self._prune_locked(now)
            expires_at = self._entries.get(key)
            if expires_at is not None and expires_at > now:
                self._dropped_duplicates += 1
                return False

            ttl_expiry = now + self.ttl_seconds
            self._entries[key] = ttl_expiry
            self._queue.append((key, ttl_expiry))
            self._accepted_updates += 1
            self._prune_locked(now)
            return True

    @staticmethod
    def _now() -> MonotonicSeconds:
        return time.monotonic()

    # noqa: codeclone[dead-code]
    def pre_process(self, update: object, data: object) -> CancelUpdate | None:
        del data
        dedup_key = self._build_dedup_key(update)
        if dedup_key is None:
            return None

        now = self._now()
        if self._check_and_register(dedup_key, now):
            return None

        with self.log_context(
            operation="drop_duplicate",
            key_type=dedup_key.split(":", 1)[0],
            cache_size=len(self._entries),
            dropped_duplicates=self._dropped_duplicates,
        ) as logger:
            logger.debug("bot.middleware.update.dedup.drop")
        return CancelUpdate()

    # noqa: codeclone[dead-code]
    def post_process(
        self,
        update: object,
        data: dict[str, object],
        exception: Exception | None,
    ) -> None:
        del update
        if not exception or isinstance(exception, CancelUpdate):
            return

        with self.log_context(
            operation="post_process",
            exception_type=type(exception).__name__,
            has_data=bool(data),
            data_keys=list(data.keys()) if data else [],
        ) as logger:
            logger.error("bot.middleware.update.dedup.post.process.fail")

    def get_stats(self) -> UpdateDedupStats:
        with self._state_lock:
            return {
                "cache_size": len(self._entries),
                "queue_size": len(self._queue),
                "dropped_duplicates": self._dropped_duplicates,
                "accepted_updates": self._accepted_updates,
                "ttl_seconds": self.ttl_seconds,
                "max_entries": self.max_entries,
            }

    def cleanup(self) -> None:
        with self._state_lock:
            self._entries.clear()
            self._queue.clear()
