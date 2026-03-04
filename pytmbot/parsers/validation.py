#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TypeGuard

from pytmbot.exceptions import ErrorContext, TemplateError
from pytmbot.parsers._types import TemplateContext, TemplateValue

# Validation patterns - compiled once
_TEMPLATE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*\.jinja2?$")
_SAFE_KEY_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Security limits - reasonable for production
MAX_TEMPLATE_NAME_LENGTH = 100
MAX_CONTEXT_KEYS = 50
MAX_CONTEXT_KEY_LENGTH = 30
MAX_STRING_VALUE_LENGTH = 10_000

# Dangerous types to block
_UNSAFE_TYPES = {
    "function",
    "method",
    "builtin_function_or_method",
    "module",
    "type",
    "code",
    "frame",
    "traceback",
    "generator",
    "coroutine",
}


def is_safe_template_name(name: object) -> TypeGuard[str]:
    """
    Fast type guard for safe template names.

    Args:
        name: Value to check

    Returns:
        bool: True if name is safe to use
    """
    return (
        isinstance(name, str)
        and 0 < len(name) <= MAX_TEMPLATE_NAME_LENGTH
        and _TEMPLATE_NAME_PATTERN.match(name) is not None
        and ".." not in name
        and "/" not in name
        and "\\" not in name
    )


@lru_cache(maxsize=128)
def validate_template_name_cached(name: str) -> str:
    """
    Cached template name validation for performance.

    Args:
        name: Template name to validate

    Returns:
        str: Validated template name

    Raises:
        TemplateError: If validation fails
    """
    if not is_safe_template_name(name):
        raise TemplateError(
            ErrorContext(
                message="Invalid template name",
                error_code="INVALID_TEMPLATE_NAME",
                metadata={"template_name": name},
            )
        )
    return name


def validate_template_name_fast(name: str) -> str:
    """
    Fast template name validation for trusted contexts.

    Args:
        name: Template name to validate

    Returns:
        str: Validated template name

    Raises:
        TemplateError: If validation fails
    """
    if not name or ".." in name or "/" in name:
        raise TemplateError(
            ErrorContext(
                message="Invalid template name",
                error_code="INVALID_TEMPLATE_NAME",
                metadata={"template_name": name},
            )
        )
    return name


def is_safe_context_key(key: object) -> TypeGuard[str]:
    """
    Type guard for safe context keys.

    Args:
        key: Key to check

    Returns:
        bool: True if key is safe
    """
    return (
        isinstance(key, str)
        and 0 < len(key) <= MAX_CONTEXT_KEY_LENGTH
        and _SAFE_KEY_PATTERN.match(key) is not None
        and key
        not in {"self", "super", "range", "dict", "list", "str", "int", "float", "bool"}
    )


def is_safe_context_value(value: TemplateValue) -> bool:
    """
    Check if context value is safe to use in templates.

    Args:
        value: Value to check

    Returns:
        bool: True if value is safe
    """
    # Check type safety
    value_type = type(value).__name__
    if value_type in _UNSAFE_TYPES:
        return False

    # Check for callable objects (except types)
    if callable(value) and not isinstance(value, type):
        return False

    # Size limits for strings
    if isinstance(value, (str, bytes)) and len(value) > MAX_STRING_VALUE_LENGTH:
        return False

    return True


def validate_context_basic(context: TemplateContext) -> TemplateContext:
    """
    Basic context validation - fast and minimal.

    Args:
        context: Template context to validate

    Returns:
        dict: Validated context

    Raises:
        TemplateError: If validation fails
    """
    if not isinstance(context, dict):
        raise TemplateError(
            ErrorContext(
                message="Context must be a dictionary",
                error_code="INVALID_CONTEXT_TYPE",
                metadata={"context_type": type(context).__name__},
            )
        )

    if len(context) > MAX_CONTEXT_KEYS:
        raise TemplateError(
            ErrorContext(
                message=f"Too many context keys (max {MAX_CONTEXT_KEYS})",
                error_code="TOO_MANY_CONTEXT_KEYS",
                metadata={"key_count": len(context)},
            )
        )

    return context


def validate_context_strict(context: TemplateContext) -> TemplateContext:
    """
    Strict context validation - thorough security checks.

    Args:
        context: Template context to validate

    Returns:
        dict: Validated and sanitized context

    Raises:
        TemplateError: If validation fails
    """
    # Basic validation first
    validated_context = validate_context_basic(context)

    # Detailed validation
    sanitized_context: TemplateContext = {}

    for key, value in validated_context.items():
        # Validate key
        if not is_safe_context_key(key):
            raise TemplateError(
                ErrorContext(
                    message=f"Invalid context key: {key}",
                    error_code="INVALID_CONTEXT_KEY",
                    metadata={"key": key},
                )
            )

        # Validate value
        if not is_safe_context_value(value):
            raise TemplateError(
                ErrorContext(
                    message=f"Unsafe context value for key: {key}",
                    error_code="UNSAFE_CONTEXT_VALUE",
                    metadata={"key": key, "value_type": type(value).__name__},
                )
            )

        sanitized_context[key] = value

    return sanitized_context


class TemplateValidator:
    """
    Template validator with configurable validation levels.

    Provides both fast and strict validation modes based on use case.
    """

    def __init__(self) -> None:
        self._validation_stats: dict[str, int] = {
            "fast_validations": 0,
            "strict_validations": 0,
            "validation_errors": 0,
        }

    def validate_render_params(
        self, template_name: str, context: TemplateContext, strict: bool = False
    ) -> tuple[str, TemplateContext]:
        """
        Validate template render parameters.

        Args:
            template_name: Template name to validate
            context: Template context to validate
            strict: If True, use strict validation

        Returns:
            tuple: (validated_name, validated_context)

        Raises:
            TemplateError: If validation fails
        """
        try:
            if strict:
                validated_name = validate_template_name_cached(template_name)
                validated_context = validate_context_strict(context)
                self._validation_stats["strict_validations"] += 1
            else:
                validated_name = validate_template_name_fast(template_name)
                validated_context = validate_context_basic(context)
                self._validation_stats["fast_validations"] += 1

            return validated_name, validated_context

        except Exception:
            self._validation_stats["validation_errors"] += 1
            raise

    def get_stats(self) -> dict[str, int]:
        """Get validation statistics."""
        return self._validation_stats.copy()


# Global validator instance
_validator = TemplateValidator()


# Public API functions
def validate_template_render(
    template_name: str,
    context: TemplateContext,
    *,
    strict: bool = True,
    trusted: bool | None = None,
) -> tuple[str, TemplateContext]:
    """
    Validate template render parameters with appropriate validation level.

    Args:
        template_name: Template name
        context: Template context
        strict: If True, use strict validation; if False, use fast validation.
        trusted: Backward compatibility alias. When provided, overrides strict mode
            using inverse mapping (trusted=True -> strict=False).

    Returns:
        tuple: (validated_name, validated_context)
    """
    strict_mode = strict if trusted is None else not trusted
    return _validator.validate_render_params(
        template_name,
        context,
        strict=strict_mode,
    )


def get_validation_stats() -> dict[str, int]:
    """Get global validation statistics."""
    return _validator.get_stats()


def clear_validation_cache() -> None:
    """Clear validation cache."""
    validate_template_name_cached.cache_clear()


__all__ = [
    "is_safe_template_name",
    "is_safe_context_key",
    "is_safe_context_value",
    "validate_template_render",
    "get_validation_stats",
    "clear_validation_cache",
    "validate_template_name_fast",
    "validate_context_basic",
]
