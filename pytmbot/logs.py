from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
from typing import Any, Callable, ClassVar, Generator, TypeVar
from weakref import WeakValueDictionary

from loguru import logger
from telebot.types import Update, Message, CallbackQuery, InlineQuery

from pytmbot.utils.utilities import parse_cli_args

T = TypeVar('T')


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
        "<yellow>{extra}</yellow>"
    )
    CUSTOM_LEVELS: ClassVar[dict[str, tuple[int, str]]] = {
        "DENIED": (39, "<red>"),
        "BLOCKED": (38, "<yellow>")
    }


class Logger:
    """
    Singleton logger class with context management and session tracking capabilities.
    Uses WeakValueDictionary for efficient memory management.
    """
    _instance = WeakValueDictionary()
    _initialized: bool = False

    def __new__(cls) -> Logger:
        if 'default' not in cls._instance:
            instance = super().__new__(cls)
            cls._instance['default'] = instance
        return cls._instance['default']

    def __init__(self) -> None:
        if not self._initialized:
            self._logger = logger
            self._configure_logger(parse_cli_args().log_level.upper())
            self.__class__._initialized = True

    def _configure_logger(self, log_level: str) -> None:
        """Configure logger with custom settings and levels."""
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

        for level_name, (level_no, color) in LogConfig.CUSTOM_LEVELS.items():
            self._logger.level(level_name, no=level_no, color=color)

    @staticmethod
    def _format_context(**kwargs: Any) -> str:
        """Cache formatted context strings for better performance."""
        return " ".join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None)

    @staticmethod
    def _extract_update_data(update: Update | Message | CallbackQuery | InlineQuery) -> dict[str, Any]:
        """Extract relevant data from Telegram update objects."""
        if isinstance(update, Update):
            obj = update.message or update.callback_query or update.inline_query
            if not obj:
                return {"update_type": "unknown", "update_id": update.update_id}
        else:
            obj = update

        update_type = type(obj).__name__.lower()

        return {
            "update_type": update_type,
            "update_id": getattr(update, "update_id", None),
            "chat_id": getattr(obj.chat, "id", None) if hasattr(obj, "chat") else None,
            "user_id": getattr(obj.from_user, "id", None) if hasattr(obj, "from_user") else None,
            "username": getattr(obj.from_user, "username", None) if hasattr(obj, "from_user") else None,
        }

    @contextmanager
    def context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        """Context manager for temporary logging context."""
        previous = getattr(self._logger, "_context", {}).copy()
        try:
            self._logger = self._logger.bind(
                **kwargs,
                context=self._format_context(**kwargs)
            )
            yield self
        finally:
            self._logger = logger.bind(**previous) if previous else logger.bind()

    def session_decorator(self, func: Callable[..., T] = None) -> Callable[..., T]:
        """Decorator for tracking session context in handlers."""

        def decorator(f: Callable[..., T]) -> Callable[..., T]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                telegram_object = next(
                    (arg for arg in args if isinstance(arg, (Update, Message, CallbackQuery))),
                    None
                )

                if not telegram_object:
                    raise ValueError(
                        "No Telegram Update, Message, or CallbackQuery object found in arguments"
                    )

                update_data = self._extract_update_data(telegram_object)

                with self.context(
                        component=f.__name__,
                        action=f.__name__,
                        **update_data
                ) as log:
                    try:
                        result = f(*args, **kwargs)
                        log.success(f"Handler {f.__name__} completed")
                        return result
                    except Exception as e:
                        log.exception(f"Handler {f.__name__} failed: {str(e)}")
                        raise

            return wrapper

        return decorator(func) if func else decorator

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


class BaseComponent:
    """Base component with integrated logging capabilities."""

    def __init__(self, component_name: str = ""):
        self._log = Logger()
        self.component_name = component_name if component_name else self.__class__.__name__
        with self._log.context(component=self.component_name) as log:
            self._log = log

    @contextmanager
    def log_context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        with self._log.context(**kwargs) as log:
            yield log


__all__ = ["Logger", "LogLevel", "BaseComponent"]
