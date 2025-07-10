#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps, cache
from time import monotonic_ns
from typing import Any, Callable, ClassVar, Generator, TypeVar
from weakref import WeakValueDictionary

from loguru import logger
from telebot.types import Update, Message, CallbackQuery, InlineQuery

from pytmbot.utils.cli import parse_cli_args

T = TypeVar("T")


class LogLevel(StrEnum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    DENIED = "DENIED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class LogConfig:
    FORMAT: ClassVar[str] = (
        "<green>{time:YYYY-MM-DD}</green> "
        "[<cyan>{time:HH:mm:ss}</cyan>]"
        "[<level>{level: <8}</level>]"
        "[<magenta>{module: <16}</magenta>] › "
        "<level>{message}</level> › "
        "<fg #A9A9A9>{extra}</fg #A9A9A9>"
    )


class Logger:
    """
    Singleton logger class with context management and session tracking capabilities.
    Uses WeakValueDictionary for efficient memory management.
    """

    __slots__ = ("_logger", "__weakref__")
    _instance = WeakValueDictionary()
    _initialized: bool = False

    def __new__(cls) -> Logger:
        if "default" not in cls._instance:
            instance = super().__new__(cls)
            cls._instance["default"] = instance
        return cls._instance["default"]

    def __init__(self) -> None:
        if not self._initialized:
            self._logger = logger
            self._configure_logger(parse_cli_args().log_level.upper())
            self.__class__._initialized = True

    @cache
    def _configure_logger(self, log_level: str) -> None:
        self._logger.remove()
        self._logger.add(
            sys.stdout,
            format=LogConfig.FORMAT,
            level=log_level,
            colorize=True,
            backtrace=True,
            diagnose=True,
            catch=True,
        )
        self._logger.add(
            sys.stdout,
            format=LogConfig.FORMAT,
            level=log_level,
            colorize=True,
            backtrace=False,
            diagnose=False,
            catch=True,
            filter=lambda record: "sensitive_exception" in record["extra"],
        )

    @staticmethod
    def _extract_update_data(
            update: Update | Message | CallbackQuery | InlineQuery,
    ) -> dict[str, Any]:
        """Extract relevant data from Telegram update objects."""
        update_id = None
        obj = update

        if isinstance(update, Update):
            update_id = update.update_id
            obj = update.message or update.callback_query or update.inline_query

        update_type = type(obj).__name__.lower() if obj else "unknown"

        return {
            "update_type": update_type,
            "update_id": update_id,
            "chat_id": getattr(obj.chat, "id", None) if hasattr(obj, "chat") else None,
            "user_id": (
                getattr(obj.from_user, "id", None)
                if hasattr(obj, "from_user")
                else None
            ),
            "username": (
                getattr(obj.from_user, "username", None)
                if hasattr(obj, "from_user")
                else None
            ),
        }

    @contextmanager
    def context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        previous = getattr(self._logger, "_context", {}).copy()
        try:
            self._logger = self._logger.bind(**kwargs)
            yield self
        finally:
            self._logger = logger.bind(**previous) if previous else logger.bind()

    def session_decorator(self, func: Callable[..., T] = None) -> Callable[..., T]:
        def decorator(f: Callable[..., T]) -> Callable[..., T]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                telegram_object = next(
                    (
                        arg
                        for arg in args
                        if isinstance(
                        arg, (Message, Update, CallbackQuery, InlineQuery)
                    )
                    ),
                    None,
                )

                context = {
                    "component": f.__name__,
                    "action": f.__name__,
                }

                if telegram_object:
                    context.update(self._extract_update_data(telegram_object))
                    update_id = context.get("update_id")

                    job_id = f"u-{update_id}" if update_id is not None else f"job-{uuid.uuid4()}"
                    context["job_id"] = job_id
                else:
                    logger.warning(f"No Telegram object found in handler {f.__name__}")
                    job_id = str(uuid.uuid4())

                context["job_id"] = job_id

                with self.context(**context) as log:
                    log.info(f"Handler {f.__name__} started")
                    start_time = monotonic_ns()
                    try:
                        result = f(*args, **kwargs)
                        elapsed_time = (monotonic_ns() - start_time) / 1_000_000
                        log.success(
                            f"Handler {f.__name__} completed",
                            context={"execution_time": f"{elapsed_time:.2f}ms"},
                        )
                        return result
                    except Exception as e:
                        elapsed_time = (monotonic_ns() - start_time) / 1_000_000
                        log.exception(
                            f"Handler {f.__name__} failed after {elapsed_time:.2f}ms: {e}",
                            context={"execution_time": f"{elapsed_time:.2f}ms"},
                        )
                        raise

            return wrapper

        return decorator(func) if func else decorator

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


class BaseComponent:
    """Base component with integrated logging capabilities."""

    __slots__ = ("_log", "component_name")

    def __init__(self, component_name: str = ""):
        self.component_name = (
            component_name if component_name else self.__class__.__name__
        )
        self._log = Logger()

    @contextmanager
    def log_context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        with self._log.context(component=self.component_name, **kwargs) as log:
            yield log


__all__ = ["Logger", "LogLevel", "BaseComponent"]
