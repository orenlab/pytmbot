#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from functools import lru_cache, wraps
from threading import RLock
from time import monotonic_ns
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
    Protocol,
    TypeVar,
    cast,
    runtime_checkable,
)
from uuid import uuid4

from loguru import logger
from telebot.types import CallbackQuery, InlineQuery, Message, Update

if TYPE_CHECKING:
    pass

T = TypeVar("T")
type TelegramObject = Update | Message | CallbackQuery | InlineQuery


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

    HUMAN_FORMAT: ClassVar[str] = (
        "<green>{time:YYYY-MM-DD}</green> "
        "[<cyan>{time:HH:mm:ss}</cyan>]"
        "[<level>{level: <8}</level>]"
        "[<magenta>{module: <16}</magenta>] › "
        "<level>{message}</level> "
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
            # Username patterns in logs (strict key-value forms only)
            r"\busername\b\s*[:=]\s*['\"]?@?([a-zA-Z0-9_]{3,})\b",
            # Optional explicit "@username" after "user=" or "user:"
            r"\buser\b\s*[:=]\s*@([a-zA-Z0-9_]{3,})\b",
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
    _MAX_STRING_LENGTH: Final[int] = 512
    _MAX_COLLECTION_ITEMS: Final[int] = 12
    _DURATION_RE: Final[re.Pattern[str]] = re.compile(
        r"^\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>ms|s|sec|secs|second|seconds)?\s*$",
        re.IGNORECASE,
    )
    _DROP_EXTRA_KEYS: ClassVar[set[str]] = {
        "action",
        "operation",
        "handler",
        "event",
    }
    _EXTRA_KEY_ALIAS: ClassVar[dict[str, str]] = {
        "update_type": "update",
        "execution_time": "ms",
        "execution_time_ms": "ms",
        "duration_ms": "ms",
        "elapsed_ms": "ms",
        "check_duration": "check_ms",
    }
    _EXTRA_ORDER: ClassVar[tuple[str, ...]] = (
        "trace_id",
        "span_id",
        "update",
        "update_id",
        "user_id",
        "chat_id",
        "ms",
        "check_ms",
        "error",
        "error_type",
    )

    _COMPONENT_ALIAS_MAP: ClassVar[dict[str, set[str]]] = {
        "main": {"main", "botlauncher"},
        "botlauncher": {"main", "botlauncher"},
        "pytmbotinstance": {"pytmbotinstance", "core"},
        "core": {"pytmbotinstance", "core"},
        "healthsystem": {"healthsystem", "healthmonitor"},
        "healthmonitor": {"healthsystem", "healthmonitor"},
    }

    def __init__(self, masker: DataMasker) -> None:
        self.masker = masker

    def __call__(self, record: Any) -> bool:
        """Filter and sanitize log records."""
        if not isinstance(record, dict):
            return True

        if message := record.get("message"):
            record["message"] = self.masker.sanitize_text(message)

        if extra := record.get("extra"):
            record["extra"] = self._sanitize_extra(
                extra,
                module_name=record.get("module"),
                logger_name=record.get("name"),
                message=record.get("message"),
            )

        return True

    def _sanitize_extra(
            self,
            extra: dict[str, Any],
            module_name: str | None = None,
            logger_name: str | None = None,
            message: str | None = None,
    ) -> dict[str, Any]:
        """Sanitize and normalize extra fields."""
        normalized: dict[str, Any] = {}
        component = extra.get("component")
        action = extra.get("action")
        normalized_message = self._normalize_identifier(message or "")

        for key, value in extra.items():
            if value is None:
                continue

            if key in self._DROP_EXTRA_KEYS:
                continue

            if (
                    key == "component"
                    and isinstance(component, str)
                    and self._is_component_duplicate(
                component=component,
                module_name=module_name,
                logger_name=logger_name,
            )
            ):
                continue

            if key == "action" and action == component:
                continue

            if key == "action" and isinstance(value, str):
                normalized_action = self._normalize_identifier(value)
                if normalized_action and (
                        normalized_action in normalized_message
                        or normalized_message.endswith(normalized_action)
                        or (
                                isinstance(component, str)
                                and normalized_action
                                == self._normalize_identifier(component)
                        )
                ):
                    continue

            normalized_key = self._EXTRA_KEY_ALIAS.get(key, key)
            sanitized_value = self._sanitize_value(normalized_key, value)

            if normalized_key in {"ms", "check_ms"}:
                sanitized_value = self._normalize_duration_value(sanitized_value)

            if normalized_key in normalized:
                normalized[normalized_key] = self._merge_extra_values(
                    normalized[normalized_key], sanitized_value
                )
            else:
                normalized[normalized_key] = sanitized_value

        return self._order_extra(normalized)

    @classmethod
    def _normalize_duration_value(cls, value: Any) -> Any:
        """Normalize textual duration values to numeric milliseconds."""
        if isinstance(value, int | float):
            return round(float(value), 2)

        if not isinstance(value, str):
            return value

        match = cls._DURATION_RE.match(value)
        if not match:
            return value

        number = float(match.group("num"))
        unit = (match.group("unit") or "ms").lower()
        if unit in {"s", "sec", "secs", "second", "seconds"}:
            return round(number * 1000, 2)
        return round(number, 2)

    @staticmethod
    def _merge_extra_values(existing: Any, new: Any) -> Any:
        """Merge values for colliding normalized keys."""
        unknown_values = {"", "unknown", "n/a", "none"}
        if isinstance(existing, str) and existing.lower() in unknown_values:
            return new
        if isinstance(new, str) and new.lower() in unknown_values:
            return existing

        if isinstance(existing, str) and isinstance(new, int | float):
            return new
        if isinstance(existing, int | float) and isinstance(new, str):
            return existing

        if existing in (None, [], {}, ()):
            return new
        return existing

    @classmethod
    def _order_extra(cls, extra: dict[str, Any]) -> dict[str, Any]:
        """Return consistently ordered extra payload."""
        ordered: dict[str, Any] = {}
        for key in cls._EXTRA_ORDER:
            if key in extra:
                ordered[key] = extra[key]
        for key in sorted(extra):
            if key not in ordered:
                ordered[key] = extra[key]
        return ordered

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        """Normalize identifiers for duplicate detection."""
        return "".join(ch.lower() for ch in value if ch.isalnum())

    @classmethod
    def _to_class_name(cls, module_name: str | None) -> str:
        """Convert snake_case module names to class-like names."""
        if not module_name:
            return ""
        return "".join(part.capitalize() for part in module_name.split("_") if part)

    @classmethod
    def _expand_component_aliases(cls, value: str | None) -> set[str]:
        """Expand normalized identifier with known component aliases."""
        normalized = cls._normalize_identifier(value or "")
        if not normalized:
            return set()
        return cls._COMPONENT_ALIAS_MAP.get(normalized, {normalized})

    @classmethod
    def _is_component_duplicate(
            cls, component: str, module_name: str | None, logger_name: str | None
    ) -> bool:
        """Detect duplicated component field."""
        normalized_component = cls._normalize_identifier(component)
        if not normalized_component:
            return True

        candidates: set[str] = set()
        if module_name:
            candidates.update(cls._expand_component_aliases(module_name))
            candidates.update(
                cls._expand_component_aliases(cls._to_class_name(module_name))
            )

        if logger_name:
            logger_last_part = logger_name.rsplit(".", 1)[-1]
            candidates.update(cls._expand_component_aliases(logger_last_part))
            candidates.update(
                cls._expand_component_aliases(cls._to_class_name(logger_last_part))
            )

        candidates.discard("")
        return normalized_component in candidates

    def _sanitize_value(self, key: str, value: Any, depth: int = 0) -> Any:
        """Sanitize and compact value recursively to reduce log noise."""
        if depth > 2:
            return "[truncated]"

        if key == "username" and isinstance(value, str):
            normalized_value = value.strip()
            if not normalized_value or normalized_value.lower() in {
                "unknown",
                "n/a",
                "none",
            }:
                return value
            return self.masker.mask_username(normalized_value)

        if isinstance(value, str):
            if len(value) > self._MAX_STRING_LENGTH:
                value = f"{value[: self._MAX_STRING_LENGTH - 3]}..."
            return self.masker.sanitize_text(value)

        if key == "user_id" and isinstance(value, int | float):
            return self.masker.mask_user_id(int(value))

        if key == "chat_id" and isinstance(value, int | float):
            return self.masker.mask_chat_id(int(value))

        if hasattr(value, "value") and hasattr(value, "name"):
            enum_value = getattr(value, "value", None)
            if isinstance(enum_value, str | int | float | bool):
                return enum_value
            return str(value)

        if isinstance(value, dict):
            items = list(value.items())
            limited_items = items[: self._MAX_COLLECTION_ITEMS]
            result: dict[str, Any] = {
                str(k): self._sanitize_value(str(k), v, depth + 1)
                for k, v in limited_items
            }
            if len(items) > self._MAX_COLLECTION_ITEMS:
                result["_truncated_items"] = len(items) - self._MAX_COLLECTION_ITEMS
            return result

        if isinstance(value, list | tuple | set):
            values = list(value)
            limited_values = values[: self._MAX_COLLECTION_ITEMS]
            list_result = [
                self._sanitize_value(key, item, depth + 1) for item in limited_values
            ]
            if len(values) > self._MAX_COLLECTION_ITEMS:
                list_result.append(
                    f"...(+{len(values) - self._MAX_COLLECTION_ITEMS} items)"
                )
            return list_result

        return value


class Logger:
    """
    Singleton logger with automatic data masking, context management,
    and session tracking capabilities.
    """

    __slots__ = ("_logger", "_masker", "_filter", "_initialized")

    _logger: Any
    _masker: DataMasker
    _filter: SecureLoggerFilter
    _initialized: bool
    _instance: Logger | None = None
    _lock: Final[RLock] = RLock()
    _context_data: ClassVar[ContextVar[dict[str, Any] | None]] = ContextVar(
        "logger_context_data", default=None
    )

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
        log_level = "INFO"
        log_format = "human"
        try:
            from pytmbot.utils.cli import parse_cli_args

            cli_args = parse_cli_args()
            raw_level = getattr(cli_args, "log_level", log_level)
            raw_format = getattr(cli_args, "log_format", log_format)

            log_level = str(getattr(raw_level, "value", raw_level)).upper()
            log_format = str(getattr(raw_format, "value", raw_format)).lower()
        except Exception:
            pass

        self._configure_logger(log_level, log_format)

    def _json_sink(self, message: Any) -> None:
        """Render compact structured JSON logs."""
        record = message.record
        timestamp = record["time"].astimezone(UTC).isoformat(timespec="milliseconds")
        payload: dict[str, Any] = {
            "ts": timestamp.replace("+00:00", "Z"),
            "level": record["level"].name,
            "module": record.get("module"),
            "msg": record.get("message"),
        }

        for key, value in record.get("extra", {}).items():
            if value is not None and key not in payload:
                payload[key] = value

        sys.stdout.write(
            f"{json.dumps(payload, ensure_ascii=False, default=str, separators=(',', ':'))}\n"
        )

    def _configure_logger(self, log_level: str, log_format: str) -> None:
        """Configure the logger with optimized settings."""
        self._logger.remove()

        def default_filter(record: dict[str, Any]) -> bool:
            return "sensitive_exception" not in record.get("extra", {}) and self._filter(
                record
            )

        def sensitive_filter(record: dict[str, Any]) -> bool:
            return "sensitive_exception" in record.get("extra", {}) and self._filter(
                record
            )

        if log_format == "json":
            self._logger.add(
                self._json_sink,
                level=log_level,
                backtrace=True,
                diagnose=True,
                catch=True,
                filter=default_filter,
            )
            self._logger.add(
                self._json_sink,
                level=log_level,
                backtrace=False,
                diagnose=False,
                catch=True,
                filter=sensitive_filter,
            )
            return

        self._logger.add(
            sys.stdout,
            format=LogConfig.HUMAN_FORMAT,
            level=log_level,
            colorize=True,
            backtrace=True,
            diagnose=True,
            catch=True,
            filter=default_filter,
        )
        self._logger.add(
            sys.stdout,
            format=LogConfig.HUMAN_FORMAT,
            level=log_level,
            colorize=True,
            backtrace=False,
            diagnose=False,
            catch=True,
            filter=sensitive_filter,
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
    ) -> dict[str, Any]:
        """Extract relevant data from Telegram update objects (cached version)."""
        return {
            "update": update_type,
            "update_id": update_id,
            "chat_id": chat_id,
            "user_id": user_id,
        }

    def _get_update_data(self, update: TelegramObject) -> dict[str, Any]:
        """Extract relevant data from Telegram update objects."""
        update_id = None
        obj: Any = update

        if isinstance(update, Update):
            update_id = update.update_id
            obj = update.message or update.callback_query or update.inline_query

        update_type = "unknown"
        if isinstance(obj, Message):
            update_type = "message"
        elif isinstance(obj, CallbackQuery):
            update_type = "callbackquery"
        elif isinstance(obj, InlineQuery):
            update_type = "inlinequery"

        chat = getattr(obj, "chat", None)
        if chat is None and hasattr(obj, "message"):
            chat = getattr(obj.message, "chat", None)

        chat_id = getattr(chat, "id", None)
        user_id = (
            getattr(obj.from_user, "id", None) if hasattr(obj, "from_user") else None
        )

        return self._extract_update_data(update_id, update_type, chat_id, user_id)

    @contextmanager
    def context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        """Context manager for temporarily binding additional data to the logger."""
        current_context = self._context_data.get() or {}
        context_update = {key: value for key, value in kwargs.items() if value is not None}
        if "trace_id" not in context_update and current_context.get("trace_id"):
            context_update["trace_id"] = current_context["trace_id"]

        merged_context = {**current_context, **context_update}
        token: Token[dict[str, Any] | None] = self._context_data.set(merged_context)
        try:
            yield self
        finally:
            self._context_data.reset(token)

    def session_decorator(
            self, func: Callable[..., T] | None = None
    ) -> Callable[..., T] | Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator for automatic session logging with context."""

        def decorator(f: Callable[..., T]) -> Callable[..., T]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                telegram_object = self._find_telegram_object(args)
                context = self._build_context(f.__name__, telegram_object)
                return self._execute_with_logging(f, args, kwargs, context)

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
        context: dict[str, Any] = {"handler": func_name}

        if telegram_object:
            # Extract sensitive data for masking BEFORE getting update data
            self._masker.extract_and_mask_from_telegram_object(telegram_object)
            # Get update data (will be masked in the filter)
            context.update(self._get_update_data(telegram_object))

        return context

    @staticmethod
    def _handler_log_level(elapsed_ms: float) -> str:
        """Get handler completion level based on execution time."""
        if elapsed_ms < 500:
            return "debug"
        if elapsed_ms <= 2000:
            return "info"
        return "warning"

    @staticmethod
    @lru_cache(maxsize=512)
    def _handler_event_name(func_name: str) -> str:
        """Build stable event name for handler lifecycle logs."""
        normalized = func_name.strip().lower()
        if normalized.startswith("handle_"):
            normalized = normalized[7:]
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        if not normalized:
            normalized = "unknown"
        return f"bot.handler.{normalized}"

    def _execute_with_logging(
            self,
            func: Callable[..., T],
            args: tuple[Any, ...],
            kwargs: dict[str, Any],
            context: dict[str, Any],
    ) -> T:
        """Execute function with timing and error logging."""
        func_name = func.__name__
        start_time = monotonic_ns()
        inherited_context = self._context_data.get() or {}
        trace_id = cast(str | None, inherited_context.get("trace_id")) or uuid4().hex[:12]
        context_with_handler = {**context, "handler": func_name}
        handler_event = self._handler_event_name(func_name)

        with self.context(trace_id=trace_id, handler=func_name):
            try:
                result = func(*args, **kwargs)
                elapsed_ms = (monotonic_ns() - start_time) / 1_000_000
                completion_context = {
                    **context_with_handler,
                    "ms": round(elapsed_ms, 2),
                }
                level = self._handler_log_level(elapsed_ms)
                getattr(self, level)(
                    f"{handler_event}.ok",
                    **completion_context,
                )
                return result
            except Exception:
                elapsed_ms = (monotonic_ns() - start_time) / 1_000_000
                error_context = {
                    **context_with_handler,
                    "ms": round(elapsed_ms, 2),
                }
                self.exception(
                    f"{handler_event}.fail",
                    **error_context,
                )
                raise

    def sanitize_and_log(self, level: str, message: str, **kwargs: Any) -> None:
        """Manual sanitization and logging of a message."""
        sanitized_message = self._masker.sanitize_text(message)
        sanitized_kwargs = {
            k: self._masker.sanitize_text(str(v)) if isinstance(v, str) else v
            for k, v in kwargs.items()
        }
        getattr(self._get_bound_logger(), level.lower())(
            sanitized_message, **sanitized_kwargs
        )

    def _get_bound_logger(self) -> Any:
        """Get logger with current context bound in a thread-safe way."""
        context = self._context_data.get() or {}
        return self._logger.bind(**context) if context else self._logger

    def __getattr__(self, name: str) -> Any:
        """Proxy attributes to the internal logger."""
        return getattr(self._get_bound_logger(), name)


class BaseComponent:
    """Base component with integrated secure logging capabilities."""

    __slots__ = ("_log", "component_name")

    def __init__(self, component_name: str = "") -> None:
        self.component_name = component_name or self.__class__.__name__
        self._log = Logger()

    @contextmanager
    def log_context(self, **kwargs: Any) -> Generator[Logger, None, None]:
        """Context manager for logging with additional data."""
        component = kwargs.pop("component", self.component_name) or self.component_name
        with self._log.context(component=component, **kwargs) as log:
            yield log


__all__ = [
    "Logger",
    "LogLevel",
    "BaseComponent",
    "DataMasker",
    "MaskingConfig",
]
