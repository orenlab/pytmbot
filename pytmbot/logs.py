#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import re
import sys
import uuid
from collections import OrderedDict
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
    Generator,
    TypeVar,
    Dict,
    Set,
    Optional,
    Union,
    Final,
    TYPE_CHECKING,
)

from loguru import logger
from telebot.types import Update, Message, CallbackQuery, InlineQuery

if TYPE_CHECKING:
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


@dataclass(slots=True)
class MaskingConfig:
    """Configuration for data masking."""

    visible_chars: int = 4
    visible_username_chars: int = 2
    visible_id_chars: int = 2
    cache_size_limit: int = 1000
    pattern_cache_size: int = 256
    min_secret_length: int = 8
    min_mask_length: int = 4


class DataMasker:
    """
    Optimized utility for data masking with improved performance.
    """

    # Compiled patterns - created once during initialization
    _COMPILED_PATTERNS: ClassVar[Dict[str, re.Pattern]] = {}

    # Static patterns for exclusions
    _EXCLUDE_PATTERNS: ClassVar[tuple[re.Pattern, ...]] = ()

    # Patterns for secret detection
    _SECRET_PATTERNS: ClassVar[tuple[re.Pattern, ...]] = ()

    __slots__ = (
        "_config",
        "_known_secrets",
        "_known_usernames",
        "_known_user_ids",
        "_known_chat_ids",
        "_sanitization_cache",
        "_lock",
    )

    def __init__(self, config: MaskingConfig | None = None) -> None:
        self._config = config or MaskingConfig()

        # Use frozenset for immutable collections (faster for lookups)
        self._known_secrets: Set[str] = set()
        self._known_usernames: Set[str] = set()
        self._known_user_ids: Set[int] = set()
        self._known_chat_ids: Set[int] = set()

        # Use OrderedDict for LRU cache (more efficient than dict + separate logic)
        self._sanitization_cache: OrderedDict[str, str] = OrderedDict()

        # Lock for thread-safety
        self._lock = RLock()

        # Initialize patterns if not already created
        if not self._COMPILED_PATTERNS:
            self._compile_patterns()

    @classmethod
    def _compile_patterns(cls) -> None:
        """Compile all regex patterns once during class initialization."""
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

        # Compile all patterns
        cls._SECRET_PATTERNS = tuple(
            re.compile(pattern, re.IGNORECASE) for pattern in secret_patterns
        )
        cls._EXCLUDE_PATTERNS = tuple(
            re.compile(pattern) for pattern in exclude_patterns
        )

    def add_secret(self, secret: str) -> None:
        """Adds a known secret to the masking list."""
        if not secret or len(secret.strip()) < self._config.min_secret_length:
            return

        with self._lock:
            self._known_secrets.add(secret.strip())
            self._sanitization_cache.clear()

    def add_username(self, username: str) -> None:
        """Adds a known username to the masking list."""
        if not username or len(username.strip()) == 0:
            return

        with self._lock:
            self._known_usernames.add(username.strip())
            self._sanitization_cache.clear()

    def add_user_id(self, user_id: int) -> None:
        """Adds a known user ID to the masking list."""
        if user_id is None:
            return

        with self._lock:
            self._known_user_ids.add(user_id)
            self._sanitization_cache.clear()

    def add_chat_id(self, chat_id: int) -> None:
        """Adds a known chat ID to the masking list."""
        if chat_id is None:
            return

        with self._lock:
            self._known_chat_ids.add(chat_id)
            self._sanitization_cache.clear()

    @lru_cache(maxsize=256)
    def mask_token(self, token: str) -> str:
        """Masks a token while preserving readability."""
        if not token:
            return token

        visible_chars = self._config.visible_chars
        token_len = len(token)

        # For very short tokens - complete masking
        if token_len < self._config.min_mask_length:
            return "*" * token_len

        # For tokens where visible characters would show too much
        if token_len <= visible_chars * 2:
            return "*" * token_len

        mask_len = token_len - visible_chars * 2
        return f"{token[:visible_chars]}{'*' * mask_len}{token[-visible_chars:]}"

    @lru_cache(maxsize=256)
    def mask_username(self, username: str) -> str:
        """Masks a username leaving some characters visible."""
        if not username or not username.strip():
            return "[MASKED_USER]"

        username = username.strip()

        # Remove @ symbol if present
        if username.startswith("@"):
            username = username[1:]

        visible = self._config.visible_username_chars
        username_len = len(username)

        # For very short names - complete masking
        if username_len <= 4 or username_len <= visible * 2:
            return "[MASKED_USER]"

        # Ensure at least 3 characters are masked
        safe_visible = min(visible, (username_len - 3) // 2)

        if safe_visible <= 0:
            return "[MASKED_USER]"

        mask_len = username_len - safe_visible * 2
        return f"{username[:safe_visible]}{'*' * mask_len}{username[-safe_visible:]}"

    @lru_cache(maxsize=256)
    def mask_user_id(self, user_id: int) -> str:
        """Masks a user ID preserving some digits."""
        if user_id is None:
            return "[MASKED_ID]"

        user_id_str = str(abs(user_id))
        visible = self._config.visible_id_chars
        id_len = len(user_id_str)

        # For very short IDs - complete masking
        if id_len <= 6 or id_len <= visible * 2:
            return "[MASKED_ID]"

        # Ensure at least 4 characters are masked
        safe_visible = min(visible, (id_len - 4) // 2)

        if safe_visible <= 0:
            return "[MASKED_ID]"

        mask_len = id_len - safe_visible * 2
        return (
            f"{user_id_str[:safe_visible]}{'*' * mask_len}{user_id_str[-safe_visible:]}"
        )

    @lru_cache(maxsize=256)
    def mask_chat_id(self, chat_id: int) -> str:
        """Masks a chat ID preserving some digits."""
        if chat_id is None:
            return "[MASKED_CHAT]"

        # Handle negative chat IDs
        is_negative = chat_id < 0
        chat_id_str = str(abs(chat_id))
        visible = self._config.visible_id_chars
        id_len = len(chat_id_str)

        # For very short IDs - complete masking
        if id_len <= 6 or id_len <= visible * 2:
            return "[MASKED_CHAT]"

        # Ensure at least 4 characters are masked
        safe_visible = min(visible, (id_len - 4) // 2)

        if safe_visible <= 0:
            return "[MASKED_CHAT]"

        mask_len = id_len - safe_visible * 2
        masked = (
            f"{chat_id_str[:safe_visible]}{'*' * mask_len}{chat_id_str[-safe_visible:]}"
        )

        return f"-{masked}" if is_negative else masked

    def _should_exclude_from_masking(self, text: str) -> bool:
        """Checks if text should be excluded from masking based on patterns."""
        return any(pattern.match(text) for pattern in self._EXCLUDE_PATTERNS)

    def _manage_cache_size(self) -> None:
        """Manages cache size by removing old entries."""
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

        sanitized = text

        # Mask known secrets (sort by length to avoid partial replacements)
        if self._known_secrets:
            for secret in sorted(self._known_secrets, key=len, reverse=True):
                if secret in sanitized:
                    sanitized = sanitized.replace(secret, self.mask_token(secret))

        # Mask known usernames
        if self._known_usernames:
            for username in sorted(self._known_usernames, key=len, reverse=True):
                patterns = [username, f"@{username}"]
                for pattern in patterns:
                    if pattern in sanitized:
                        sanitized = sanitized.replace(
                            pattern, self.mask_username(username)
                        )

        # Mask known user IDs
        if self._known_user_ids:
            for user_id in self._known_user_ids:
                user_id_str = str(user_id)
                if user_id_str in sanitized:
                    sanitized = sanitized.replace(
                        user_id_str, self.mask_user_id(user_id)
                    )

        # Mask known chat IDs
        if self._known_chat_ids:
            for chat_id in self._known_chat_ids:
                chat_id_str = str(chat_id)
                if chat_id_str in sanitized:
                    sanitized = sanitized.replace(
                        chat_id_str, self.mask_chat_id(chat_id)
                    )

        # Apply pattern-based masking for unknown secrets
        if not self._should_exclude_from_masking(sanitized):
            for pattern in self._SECRET_PATTERNS:

                def replacement(match) -> str:
                    matched_text = match.group(0)
                    # Double-check exclusion for each match
                    if self._should_exclude_from_masking(matched_text):
                        return matched_text

                    # Check if this is a user ID, chat ID, or username pattern
                    groups = match.groups()
                    pattern_str = pattern.pattern.lower()

                    if "user" in pattern_str and groups and groups[0]:
                        if groups[0].isdigit():
                            return match.group(0).replace(
                                groups[0], self.mask_user_id(int(groups[0]))
                            )
                        else:
                            return match.group(0).replace(
                                groups[0], self.mask_username(groups[0])
                            )
                    elif "chat" in pattern_str and groups and groups[0]:
                        return match.group(0).replace(
                            groups[0], self.mask_chat_id(int(groups[0]))
                        )
                    elif matched_text.isdigit() and len(matched_text) >= 9:
                        # Long numeric ID - probably a user ID
                        return self.mask_user_id(int(matched_text))

                    # Standard masking
                    return "*" * len(matched_text)

                sanitized = pattern.sub(replacement, sanitized)

        # Cache the result
        with self._lock:
            self._manage_cache_size()
            self._sanitization_cache[text] = sanitized

        return sanitized

    def extract_and_mask_from_telegram_object(
        self, obj: Union[Update, Message, CallbackQuery, InlineQuery]
    ) -> None:
        """Extracts sensitive data from Telegram objects and adds to masking lists."""
        if isinstance(obj, Update):
            obj = obj.message or obj.callback_query or obj.inline_query

        if not obj:
            return

        # Extract user information
        if hasattr(obj, "from_user") and obj.from_user:
            user = obj.from_user
            if user.id:
                self.add_user_id(user.id)
            if user.username:
                self.add_username(user.username)
            if hasattr(user, "first_name") and user.first_name:
                self.add_username(user.first_name)
            if hasattr(user, "last_name") and user.last_name:
                self.add_username(user.last_name)

        # Extract chat information
        if hasattr(obj, "chat") and obj.chat:
            chat = obj.chat
            if chat.id:
                self.add_chat_id(chat.id)
            if hasattr(chat, "username") and chat.username:
                self.add_username(chat.username)
            if hasattr(chat, "title") and chat.title:
                self.add_username(chat.title)


class SecureLoggerFilter:
    """Optimized filter for loguru with automatic data masking."""

    __slots__ = ("masker",)

    def __init__(self, masker: DataMasker) -> None:
        self.masker = masker

    def __call__(self, record: dict) -> bool:
        """Filters and sanitizes log records."""
        # Always sanitize the message
        message = record.get("message", "")
        if message:
            record["message"] = self.masker.sanitize_text(message)

        # Sanitize extra fields
        extra = record.get("extra")
        if extra:
            sanitized_extra = {}
            for key, value in extra.items():
                if isinstance(value, str):
                    sanitized_extra[key] = self.masker.sanitize_text(value)
                elif isinstance(value, (int, float)) and key in ("user_id", "chat_id"):
                    # Mask numeric user/chat IDs in extra fields
                    if key == "user_id":
                        sanitized_extra[key] = self.masker.mask_user_id(value)
                    elif key == "chat_id":
                        sanitized_extra[key] = self.masker.mask_chat_id(value)
                else:
                    sanitized_extra[key] = value
            record["extra"] = sanitized_extra

        return True


class Logger:
    """
    Singleton logger with automatic data masking, context management,
    and session tracking capabilities.
    """

    __slots__ = ("_logger", "_masker", "_filter", "_initialized")

    _instance: Optional[Logger] = None
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
                    self._masker = DataMasker()
                    self._filter = SecureLoggerFilter(self._masker)
                    self._logger = logger

                    # Lazy initialization of configuration
                    try:
                        from pytmbot.utils.cli import parse_cli_args

                        self._configure_logger(parse_cli_args().log_level.upper())
                    except ImportError:
                        self._configure_logger("INFO")

                    self._initialized = True

    def _configure_logger(self, log_level: str) -> None:
        """Configures the logger with optimized settings."""
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
        """Adds a secret that should be masked in all logs."""
        self._masker.add_secret(secret)

    def add_username_to_mask(self, username: str) -> None:
        """Adds a username that should be masked in all logs."""
        self._masker.add_username(username)

    def add_user_id_to_mask(self, user_id: int) -> None:
        """Adds a user ID that should be masked in all logs."""
        self._masker.add_user_id(user_id)

    def add_chat_id_to_mask(self, chat_id: int) -> None:
        """Adds a chat ID that should be masked in all logs."""
        self._masker.add_chat_id(chat_id)

    def configure_masking_from_settings(self, settings) -> None:
        """Configures masking based on application settings."""
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
                    secret_value = secret.get_secret_value()
                    if secret_value:
                        self.add_secret_to_mask(secret_value)
        except (AttributeError, IndexError, TypeError):
            # If settings structure is different, continue silently
            pass

    @lru_cache(maxsize=512)
    def _extract_update_data(
        self,
        update_id: Optional[int],
        update_type: str,
        chat_id: Optional[int],
        user_id: Optional[int],
        username: Optional[str],
    ) -> dict[str, Any]:
        """Extracts relevant data from Telegram update objects (cached version)."""
        return {
            "update_type": update_type,
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
        }

    def _get_update_data(
        self,
        update: Update | Message | CallbackQuery | InlineQuery,
    ) -> dict[str, Any]:
        """Extracts relevant data from Telegram update objects."""
        update_id = None
        obj = update

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

    def session_decorator(self, func: Callable[..., T] = None) -> Callable[..., T]:
        """Decorator for automatic session logging with context."""

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
                    # Extract sensitive data for masking BEFORE getting update data
                    self._masker.extract_and_mask_from_telegram_object(telegram_object)

                    # Get update data (will be masked in the filter)
                    update_data = self._get_update_data(telegram_object)
                    context.update(update_data)

                    update_id = context.get("update_id")
                    job_id = (
                        f"u-{update_id}"
                        if update_id is not None
                        else f"job-{uuid.uuid4()}"
                    )
                    context["job_id"] = job_id
                else:
                    self._logger.warning(
                        f"No Telegram object found in handler {f.__name__}"
                    )
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
                            execution_time=f"{elapsed_time:.2f}ms",
                        )
                        return result
                    except Exception as e:
                        elapsed_time = (monotonic_ns() - start_time) / 1_000_000
                        # Exception message will be automatically sanitized by the filter
                        log.exception(
                            f"Handler {f.__name__} failed after {elapsed_time:.2f}ms: {e}",
                            execution_time=f"{elapsed_time:.2f}ms",
                        )
                        raise

            return wrapper

        return decorator(func) if func else decorator

    def sanitize_and_log(self, level: str, message: str, **kwargs) -> None:
        """Manual sanitization and logging of a message."""
        sanitized_message = self._masker.sanitize_text(message)
        sanitized_kwargs = {
            k: self._masker.sanitize_text(str(v)) if isinstance(v, str) else v
            for k, v in kwargs.items()
        }
        getattr(self._logger, level.lower())(sanitized_message, **sanitized_kwargs)

    def __getattr__(self, name: str) -> Any:
        """Proxies attributes to the internal logger."""
        return getattr(self._logger, name)


class BaseComponent:
    """Base component with integrated secure logging capabilities."""

    __slots__ = ("_log", "component_name")

    def __init__(self, component_name: str = "") -> None:
        self.component_name = (
            component_name if component_name else self.__class__.__name__
        )
        self._log = Logger()

    @contextmanager
    def log_context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        """Context manager for logging with additional data."""
        with self._log.context(component=self.component_name, **kwargs) as log:
            yield log


__all__ = ["Logger", "LogLevel", "BaseComponent", "DataMasker", "MaskingConfig"]
