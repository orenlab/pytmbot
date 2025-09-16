#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import re
import sys
from collections import OrderedDict
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps, lru_cache
from threading import RLock
from time import monotonic_ns
from typing import (
    Any,
    Callable,
    ClassVar,
    TypeVar,
    Final,
    TYPE_CHECKING,
    TypeAlias,
    Protocol,
    runtime_checkable,
)

from loguru import logger
from telebot.types import Update, Message, CallbackQuery, InlineQuery

if TYPE_CHECKING:
    from pytmbot.utils.cli import parse_cli_args

T = TypeVar("T")
TelegramObject: TypeAlias = Update | Message | CallbackQuery | InlineQuery


class LogLevel(StrEnum):
    """Log levels enumeration."""

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
    """Configuration for log formatting."""

    FORMAT: ClassVar[str] = (
        "<green>{time:YYYY-MM-DD}</green> "
        "[<cyan>{time:HH:mm:ss}</cyan>]"
        "[<level>{level: <8}</level>]"
        "[<magenta>{module: <16}</magenta>] › "
        "<level>{message}</level> › "
        "<fg #A9A9A9>{extra}</fg #A9A9A9>"
    )


@dataclass(slots=True)
class MaskingConfig:
    """Configuration for data masking."""

    visible_chars: int = 4
    visible_username_chars: int = 3
    visible_id_chars: int = 3
    cache_size_limit: int = 1000
    pattern_cache_size: int = 256
    min_secret_length: int = 8
    min_mask_length: int = 4


@runtime_checkable
class Maskable(Protocol):
    """Protocol for objects that can provide maskable data."""

    @property
    def id(self) -> int | None: ...

    @property
    def username(self) -> str | None: ...


class PatternRegistry:
    """Registry for compiled regex patterns."""

    __slots__ = ("_secret_patterns", "_exclude_patterns", "_initialized")

    def __init__(self) -> None:
        self._secret_patterns: tuple[re.Pattern[str], ...] = ()
        self._exclude_patterns: tuple[re.Pattern[str], ...] = ()
        self._initialized = False
        self._initialize()

    def _initialize(self) -> None:
        """Initialize and compile all patterns."""
        if self._initialized:
            return

        secret_patterns = [
            # Telegram bot tokens (more precise pattern)
            r"\b\d{8,12}:[A-Za-z0-9_-]{35}\b",
            # Base64 encoded secrets (stricter - only very long ones)
            r"\b[A-Za-z0-9+/]{80,}={0,2}\b",
            # Common user IDs in logs
            r"\b(?:user_id|user-id|userid)[\s:=]+(\d{6,})\b",
            # Chat ID patterns
            r"\b(?:chat_id|chat-id|chatid)[\s:=]+(-?\d{6,})\b",
            # Username patterns in logs
            r"\b(?:username|user)[\s:=]+@?([a-zA-Z0-9_]{3,})\b",
            # General long numeric IDs
            r"\b\d{9,}\b",
        ]

        exclude_patterns = [
            r"^/[a-zA-Z0-9_/.-]+$",  # File paths
            r"^\d{1,4}-\d{1,2}-\d{1,2}$",  # Dates
            r"^\d{1,2}:\d{2}:\d{2}$",  # Time
            r"^(19|20)\d{2}$",  # Years
            r"^[0-9]{1,8}$",  # Short numbers (ports, etc.)
        ]

        self._secret_patterns = tuple(
            re.compile(pattern, re.IGNORECASE) for pattern in secret_patterns
        )
        self._exclude_patterns = tuple(
            re.compile(pattern) for pattern in exclude_patterns
        )
        self._initialized = True

    @property
    def secret_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Get secret detection patterns."""
        return self._secret_patterns

    @property
    def exclude_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Get exclusion patterns."""
        return self._exclude_patterns


class DataMasker:
    """Optimized utility for data masking with improved performance."""

    __slots__ = (
        "_config",
        "_known_secrets",
        "_known_usernames",
        "_known_user_ids",
        "_known_chat_ids",
        "_sanitization_cache",
        "_lock",
        "_pattern_registry",
    )

    def __init__(self, config: MaskingConfig | None = None) -> None:
        self._config = config or MaskingConfig()
        self._pattern_registry = PatternRegistry()

        # Use sets for faster lookups
        self._known_secrets: set[str] = set()
        self._known_usernames: set[str] = set()
        self._known_user_ids: set[int] = set()
        self._known_chat_ids: set[int] = set()

        # LRU cache implementation
        self._sanitization_cache: OrderedDict[str, str] = OrderedDict()

        # Thread safety
        self._lock = RLock()

    def add_secret(self, secret: str) -> None:
        """Add a known secret to the masking list."""
        if not secret or len(secret.strip()) < self._config.min_secret_length:
            return

        with self._lock:
            self._known_secrets.add(secret.strip())
            self._invalidate_cache()

    def add_username(self, username: str) -> None:
        """Add a known username to the masking list."""
        if not username or not (clean_username := username.strip()):
            return

        with self._lock:
            self._known_usernames.add(clean_username)
            self._invalidate_cache()

    def add_user_id(self, user_id: int | None) -> None:
        """Add a known user ID to the masking list."""
        if user_id is None:
            return

        with self._lock:
            self._known_user_ids.add(user_id)
            self._invalidate_cache()

    def add_chat_id(self, chat_id: int | None) -> None:
        """Add a known chat ID to the masking list."""
        if chat_id is None:
            return

        with self._lock:
            self._known_chat_ids.add(chat_id)
            self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        """Clear the sanitization cache."""
        self._sanitization_cache.clear()

    @lru_cache(maxsize=256)
    def mask_token(self, token: str) -> str:
        """Mask a token while preserving readability."""
        if not token:
            return token

        token_len = len(token)
        visible_chars = self._config.visible_chars

        # Complete masking for very short tokens
        if token_len < self._config.min_mask_length:
            return "*" * token_len

        # Complete masking if visible chars would show too much
        if token_len <= visible_chars * 2:
            return "*" * token_len

        mask_len = token_len - visible_chars * 2
        return f"{token[:visible_chars]}{'*' * mask_len}{token[-visible_chars:]}"

    @lru_cache(maxsize=256)
    def mask_username(self, username: str) -> str:
        """Mask a username leaving some characters visible."""
        if not username or not (clean_username := username.strip()):
            return "[MASKED_USER]"

        # Remove @ symbol if present
        username = clean_username.removeprefix("@")
        username_len = len(username)
        visible = self._config.visible_username_chars

        # Complete masking for very short names
        if username_len <= 4 or username_len <= visible * 2:
            return "[MASKED_USER]"

        # Ensure at least 3 characters are masked
        safe_visible = min(visible, (username_len - 3) // 2)

        if safe_visible <= 0:
            return "[MASKED_USER]"

        mask_len = username_len - safe_visible * 2
        return f"{username[:safe_visible]}{'*' * mask_len}{username[-safe_visible:]}"

    @lru_cache(maxsize=256)
    def mask_user_id(self, user_id: int | None) -> str:
        """Mask a user ID preserving some digits."""
        if user_id is None:
            return "[MASKED_ID]"

        user_id_str = str(abs(user_id))
        return self._mask_numeric_id(user_id_str, "[MASKED_ID]")

    @lru_cache(maxsize=256)
    def mask_chat_id(self, chat_id: int | None) -> str:
        """Mask a chat ID preserving some digits."""
        if chat_id is None:
            return "[MASKED_CHAT]"

        is_negative = chat_id < 0
        chat_id_str = str(abs(chat_id))
        masked = self._mask_numeric_id(chat_id_str, "[MASKED_CHAT]")

        return f"-{masked}" if is_negative and masked != "[MASKED_CHAT]" else masked

    def _mask_numeric_id(self, id_str: str, fallback: str) -> str:
        """Helper method to mask numeric IDs."""
        visible = self._config.visible_id_chars
        id_len = len(id_str)

        # Complete masking for very short IDs
        if id_len <= 6 or id_len <= visible * 2:
            return fallback

        # Ensure at least 4 characters are masked
        safe_visible = min(visible, (id_len - 4) // 2)

        if safe_visible <= 0:
            return fallback

        mask_len = id_len - safe_visible * 2
        return f"{id_str[:safe_visible]}{'*' * mask_len}{id_str[-safe_visible:]}"

    def _should_exclude_from_masking(self, text: str) -> bool:
        """Check if text should be excluded from masking based on patterns."""
        return any(
            pattern.match(text) for pattern in self._pattern_registry.exclude_patterns
        )

    def _manage_cache_size(self) -> None:
        """Manage cache size by removing old entries."""
        if len(self._sanitization_cache) >= self._config.cache_size_limit:
            # Remove 20% of the oldest entries
            items_to_remove = self._config.cache_size_limit // 5
            for _ in range(items_to_remove):
                self._sanitization_cache.popitem(last=False)

    def sanitize_text(self, text: str) -> str:
        """Comprehensive text sanitization by masking all sensitive data."""
        if not text:
            return text

        # Check cache
        with self._lock:
            if text in self._sanitization_cache:
                # Move to end (LRU)
                self._sanitization_cache.move_to_end(text)
                return self._sanitization_cache[text]

        # Skip sanitization for very short strings
        if len(text) < self._config.min_mask_length:
            with self._lock:
                self._sanitization_cache[text] = text
            return text

        sanitized = self._apply_known_masks(text)
        sanitized = self._apply_pattern_masks(sanitized)

        # Cache the result
        with self._lock:
            self._manage_cache_size()
            self._sanitization_cache[text] = sanitized

        return sanitized

    def _apply_known_masks(self, text: str) -> str:
        """Apply masking for known sensitive data."""
        result = text

        # Mask known secrets (sort by length to avoid partial replacements)
        for secret in sorted(self._known_secrets, key=len, reverse=True):
            if secret in result:
                result = result.replace(secret, self.mask_token(secret))

        # Mask known usernames
        for username in sorted(self._known_usernames, key=len, reverse=True):
            for pattern in [username, f"@{username}"]:
                if pattern in result:
                    result = result.replace(pattern, self.mask_username(username))

        # Mask known user IDs
        for user_id in self._known_user_ids:
            user_id_str = str(user_id)
            if user_id_str in result:
                result = result.replace(user_id_str, self.mask_user_id(user_id))

        # Mask known chat IDs
        for chat_id in self._known_chat_ids:
            chat_id_str = str(chat_id)
            if chat_id_str in result:
                result = result.replace(chat_id_str, self.mask_chat_id(chat_id))

        return result

    def _apply_pattern_masks(self, text: str) -> str:
        """Apply pattern-based masking for unknown secrets."""
        if self._should_exclude_from_masking(text):
            return text

        result = text
        for pattern in self._pattern_registry.secret_patterns:
            result = pattern.sub(self._create_replacement_function(pattern), result)

        return result

    def _create_replacement_function(
        self, pattern: re.Pattern[str]
    ) -> Callable[[re.Match[str]], str]:
        """Create a replacement function for regex substitution."""

        def replacement(match: re.Match[str]) -> str:
            matched_text = match.group(0)

            # Double-check exclusion for each match
            if self._should_exclude_from_masking(matched_text):
                return matched_text

            groups = match.groups()
            pattern_str = pattern.pattern.lower()

            # Handle specific pattern types
            if "user" in pattern_str and groups and groups[0]:
                if groups[0].isdigit():
                    return match.group(0).replace(
                        groups[0], self.mask_user_id(int(groups[0]))
                    )
                return match.group(0).replace(groups[0], self.mask_username(groups[0]))

            if "chat" in pattern_str and groups and groups[0]:
                return match.group(0).replace(
                    groups[0], self.mask_chat_id(int(groups[0]))
                )

            if matched_text.isdigit() and len(matched_text) >= 9:
                # Long numeric ID - probably a user ID
                return self.mask_user_id(int(matched_text))

            # Standard masking
            return "*" * len(matched_text)

        return replacement

    def extract_and_mask_from_telegram_object(self, obj: TelegramObject | None) -> None:
        """Extract sensitive data from Telegram objects and add to masking lists."""
        if obj is None:
            return

        # Handle Update objects
        if isinstance(obj, Update):
            obj = obj.message or obj.callback_query or obj.inline_query
            if obj is None:
                return

        # Extract user information
        if hasattr(obj, "from_user") and (user := obj.from_user):
            if user.id:
                self.add_user_id(user.id)
            if user.username:
                self.add_username(user.username)
            if first_name := getattr(user, "first_name", None):
                self.add_username(first_name)
            if last_name := getattr(user, "last_name", None):
                self.add_username(last_name)

        # Extract chat information
        if hasattr(obj, "chat") and (chat := obj.chat):
            if chat.id:
                self.add_chat_id(chat.id)
            if username := getattr(chat, "username", None):
                self.add_username(username)
            if title := getattr(chat, "title", None):
                self.add_username(title)


class SecureLoggerFilter:
    """Optimized filter for loguru with automatic data masking."""

    __slots__ = ("masker",)

    def __init__(self, masker: DataMasker) -> None:
        self.masker = masker

    def __call__(self, record: dict[str, Any]) -> bool:
        """Filter and sanitize log records."""
        # Sanitize the message
        if message := record.get("message"):
            record["message"] = self.masker.sanitize_text(message)

        # Sanitize extra fields
        if extra := record.get("extra"):
            record["extra"] = self._sanitize_extra(extra)

        return True

    def _sanitize_extra(self, extra: dict[str, Any]) -> dict[str, Any]:
        """Sanitize extra fields in log records."""
        sanitized_extra = {}

        for key, value in extra.items():
            match value:
                case str():
                    sanitized_extra[key] = self.masker.sanitize_text(value)
                case int() | float() if key == "user_id":
                    sanitized_extra[key] = self.masker.mask_user_id(int(value))
                case int() | float() if key == "chat_id":
                    sanitized_extra[key] = self.masker.mask_chat_id(int(value))
                case _:
                    sanitized_extra[key] = value

        return sanitized_extra


class Logger:
    """
    Singleton logger with automatic data masking, context management,
    and session tracking capabilities.
    """

    __slots__ = ("_logger", "_masker", "_filter", "_initialized")

    _instance: Logger | None = None
    _lock: Final[RLock] = RLock()

    def __new__(cls) -> Logger:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._setup_logger()
                    self._initialized = True

    def _setup_logger(self) -> None:
        """Set up the logger with masking and configuration."""
        self._masker = DataMasker()
        self._filter = SecureLoggerFilter(self._masker)
        self._logger = logger

        # Lazy initialization of configuration
        try:
            from pytmbot.utils.cli import parse_cli_args

            log_level = parse_cli_args().log_level.upper()
        except ImportError:
            log_level = "INFO"

        self._configure_logger(log_level)

    def _configure_logger(self, log_level: str) -> None:
        """Configure the logger with optimized settings."""
        self._logger.remove()

        # Main logger with security filter
        self._logger.add(
            sys.stdout,
            format=LogConfig.FORMAT,
            level=log_level,
            colorize=True,
            backtrace=True,
            diagnose=True,
            catch=True,
            filter=self._filter,
        )

        # Special handler for sensitive exceptions
        self._logger.add(
            sys.stdout,
            format=LogConfig.FORMAT,
            level=log_level,
            colorize=True,
            backtrace=False,
            diagnose=False,
            catch=True,
            filter=lambda record: (
                "sensitive_exception" in record.get("extra", {})
                and self._filter(record)
            ),
        )

    def add_secret_to_mask(self, secret: str) -> None:
        """Add a secret that should be masked in all logs."""
        self._masker.add_secret(secret)

    def add_username_to_mask(self, username: str) -> None:
        """Add a username that should be masked in all logs."""
        self._masker.add_username(username)

    def add_user_id_to_mask(self, user_id: int) -> None:
        """Add a user ID that should be masked in all logs."""
        self._masker.add_user_id(user_id)

    def add_chat_id_to_mask(self, chat_id: int) -> None:
        """Add a chat ID that should be masked in all logs."""
        self._masker.add_chat_id(chat_id)

    def configure_masking_from_settings(self, settings: Any) -> None:
        """Configure masking based on application settings."""
        try:
            # Add bot tokens to masking
            secrets_to_mask = [
                settings.bot_token.prod_token[0],
                settings.bot_token.dev_bot_token[0],
                settings.plugins_config.outline.api_url[0],
                settings.plugins_config.outline.cert[0],
            ]

            for secret in secrets_to_mask:
                if secret and hasattr(secret, "get_secret_value"):
                    if secret_value := secret.get_secret_value():
                        self.add_secret_to_mask(secret_value)
        except (AttributeError, IndexError, TypeError):
            # If settings structure is different, continue silently
            pass

    @lru_cache(maxsize=512)
    def _extract_update_data(
        self,
        update_id: int | None,
        update_type: str,
        chat_id: int | None,
        user_id: int | None,
        username: str | None,
    ) -> dict[str, Any]:
        """Extract relevant data from Telegram update objects (cached version)."""
        return {
            "update_type": update_type,
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
        }

    def _get_update_data(self, update: TelegramObject) -> dict[str, Any]:
        """Extract relevant data from Telegram update objects."""
        update_id = None
        obj: Any = update

        if isinstance(update, Update):
            update_id = update.update_id
            obj = update.message or update.callback_query or update.inline_query

        update_type = type(obj).__name__.lower() if obj else "unknown"

        chat_id = getattr(obj.chat, "id", None) if hasattr(obj, "chat") else None
        user_id = (
            getattr(obj.from_user, "id", None) if hasattr(obj, "from_user") else None
        )
        username = (
            getattr(obj.from_user, "username", None)
            if hasattr(obj, "from_user")
            else None
        )

        return self._extract_update_data(
            update_id, update_type, chat_id, user_id, username
        )

    @contextmanager
    def context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        """Context manager for temporarily binding additional data to the logger."""
        previous = getattr(self._logger, "_context", {}).copy()
        try:
            self._logger = self._logger.bind(**kwargs)
            yield self
        finally:
            self._logger = logger.bind(**previous) if previous else logger.bind()

    def session_decorator(
        self, func: Callable[..., T] | None = None
    ) -> Callable[..., T] | Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator for automatic session logging with context."""

        def decorator(f: Callable[..., T]) -> Callable[..., T]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                telegram_object = self._find_telegram_object(args)
                context = self._build_context(f.__name__, telegram_object)

                with self.context(**context) as log:
                    return self._execute_with_logging(f, args, kwargs, log)

            return wrapper

        return decorator(func) if func else decorator

    def _find_telegram_object(self, args: tuple[Any, ...]) -> TelegramObject | None:
        """Find a Telegram object in function arguments."""
        return next(
            (
                arg
                for arg in args
                if isinstance(arg, (Message, Update, CallbackQuery, InlineQuery))
            ),
            None,
        )

    def _build_context(
        self, func_name: str, telegram_object: TelegramObject | None
    ) -> dict[str, Any]:
        """Build context dictionary for logging."""
        context = {
            "component": func_name,
            "action": func_name,
        }

        if telegram_object:
            # Extract sensitive data for masking BEFORE getting update data
            self._masker.extract_and_mask_from_telegram_object(telegram_object)
            # Get update data (will be masked in the filter)
            context.update(self._get_update_data(telegram_object))
        else:
            self._logger.warning(f"No Telegram object found in handler {func_name}")

        return context

    def _execute_with_logging(
        self,
        func: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        log: Logger,
    ) -> T:
        """Execute function with timing and error logging."""
        func_name = func.__name__
        log.info(f"Handler {func_name} started")
        start_time = monotonic_ns()

        try:
            result = func(*args, **kwargs)
            elapsed_ms = (monotonic_ns() - start_time) / 1_000_000
            log.success(
                f"Handler {func_name} completed",
                execution_time=f"{elapsed_ms:.2f}ms",
            )
            return result
        except Exception as e:
            elapsed_ms = (monotonic_ns() - start_time) / 1_000_000
            log.exception(
                f"Handler {func_name} failed after {elapsed_ms:.2f}ms: {e}",
                execution_time=f"{elapsed_ms:.2f}ms",
            )
            raise

    def sanitize_and_log(self, level: str, message: str, **kwargs: Any) -> None:
        """Manual sanitization and logging of a message."""
        sanitized_message = self._masker.sanitize_text(message)
        sanitized_kwargs = {
            k: self._masker.sanitize_text(str(v)) if isinstance(v, str) else v
            for k, v in kwargs.items()
        }
        getattr(self._logger, level.lower())(sanitized_message, **sanitized_kwargs)

    def __getattr__(self, name: str) -> Any:
        """Proxy attributes to the internal logger."""
        return getattr(self._logger, name)


class BaseComponent:
    """Base component with integrated secure logging capabilities."""

    __slots__ = ("_log", "component_name")

    def __init__(self, component_name: str = "") -> None:
        self.component_name = component_name or self.__class__.__name__
        self._log = Logger()

    @contextmanager
    def log_context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        """Context manager for logging with additional data."""
        with self._log.context(component=self.component_name, **kwargs) as log:
            yield log


__all__ = [
    "Logger",
    "LogLevel",
    "BaseComponent",
    "DataMasker",
    "MaskingConfig",
]
