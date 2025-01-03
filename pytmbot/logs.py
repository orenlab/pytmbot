from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps, cache
from typing import Any, Callable, ClassVar, Self, Generator, Optional
from weakref import WeakValueDictionary

from loguru import logger
from telebot.types import Update, Message, CallbackQuery, InlineQuery

from pytmbot.utils.utilities import parse_cli_args


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


class LogContext:

    def __init__(self, logger_instance: Logger, **context: Any) -> None:
        self.logger = logger_instance
        self.context = context
        self.previous_context: Optional[dict[str, Any]] = None

    def __enter__(self) -> Logger:
        self.previous_context = getattr(self.logger.logger, "_context", {}).copy()

        new_context = {
            **self.previous_context,
            **self.context,
            "context_id": id(self)
        }

        self.logger._logger = self.logger.logger.bind(**new_context)
        return self.logger

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.previous_context is not None:
            self.logger._logger = logger.bind(**self.previous_context)
        else:
            self.logger._logger = logger.bind()


class Logger:
    _instances = WeakValueDictionary()
    _initialized: bool = False

    def __new__(cls) -> Self:
        if 'default' not in cls._instances:
            instance = super().__new__(cls)
            cls._instances['default'] = instance
        return cls._instances['default']

    def __init__(self) -> None:
        if not self._initialized:
            self._logger = logger
            self._log_level = LogLevel(parse_cli_args().log_level.upper())
            self._configure_logger()
            self.__class__._initialized = True

    def _configure_logger(self) -> None:
        logger.remove()
        logger.add(
            sys.stdout,
            format=LogConfig.FORMAT,
            level=str(self._log_level),
            colorize=True,
            backtrace=True,
            diagnose=True,
            catch=True,
        )

        for level_name, (level_no, color) in LogConfig.CUSTOM_LEVELS.items():
            logger.level(level_name, no=level_no, color=color)

    @contextmanager
    def context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        with LogContext(self, **kwargs) as log:
            yield log

    @staticmethod
    def _extract_update_data(update: Any) -> dict[str, Any]:
        if isinstance(update, Update):
            if update.message:
                obj = update.message
            elif update.callback_query:
                obj = update.callback_query
            elif update.inline_query:
                obj = update.inline_query
            else:
                return {"update_type": "unknown", "update_id": update.update_id}
            update_type = type(obj).__name__.lower()
        elif isinstance(update, (Message, CallbackQuery, InlineQuery)):
            obj = update
            update_type = type(obj).__name__.lower()
        else:
            raise ValueError("Unsupported type of update object")

        chat_id = getattr(obj.chat, "id", None) if hasattr(obj, "chat") else None
        user_id = getattr(obj.from_user, "id", None) if hasattr(obj, "from_user") else None
        username = getattr(obj.from_user, "username", None) if hasattr(obj, "from_user") else None
        return {
            "update_type": update_type,
            "update_id": getattr(update, "update_id", None),
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
        }

    @cache
    def _format_context(self, **kwargs: Any) -> str:
        return " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)

    def bind_context(self, **kwargs: Any) -> Self:
        return self._logger.bind(context=self._format_context(**kwargs))

    def session_decorator(self, func: Callable[..., Any] = None) -> Callable:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                telegram_object = next(
                    filter(lambda arg: isinstance(arg, (Update, Message, CallbackQuery)), args),
                    None
                )

                if telegram_object is None:
                    raise ValueError(
                        "No Telegram Update, Message, or CallbackQuery object found among arguments"
                    )

                update_data = self._extract_update_data(telegram_object)

                with self.context(
                        component=func.__name__,
                        action=func.__name__,
                        **update_data
                ) as log:
                    try:
                        result = func(*args, **kwargs)
                        log.success(f"Handler {func.__name__} executed successfully")
                        return result
                    except Exception as e:
                        log.exception(f"Error in handler {func.__name__}: {str(e)}")
                        raise

            return wrapper

        return decorator(func) if func else decorator

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)

    @property
    def logger(self):
        return self._logger


__all__ = ["Logger", "LogLevel", "LogContext"]
