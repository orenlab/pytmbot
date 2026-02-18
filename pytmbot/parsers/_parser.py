#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Private parser module - optimized core implementation.
Use public interfaces from compiler.py instead.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any, Final

from cachetools import TTLCache  # type: ignore[import-untyped]
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from jinja2.exceptions import TemplateError, TemplateNotFound
from jinja2.sandbox import SandboxedEnvironment

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import var_config

# Private constants
_TEMPLATE_SUBDIRECTORIES: Final[dict[str, str]] = {
    "a": "auth_templates",
    "b": "base_templates",
    "d": "docker_templates",
}

_PLUGIN_PREFIX: Final[str] = "plugin_"
_PLUGIN_TEMPLATE_BASE: Final[str] = "plugins_template"

# Production-ready caching with TTL
_template_cache: TTLCache[str, Template] = TTLCache(maxsize=100, ttl=3600)  # 1 hour TTL
_result_cache: TTLCache[str, str] = TTLCache(
    maxsize=50, ttl=1800
)  # 30 min result cache
_cache_lock = RLock()

# Singleton environment
_environment: Environment | None = None
_env_lock = RLock()

# Hot templates for fast path
_HOT_TEMPLATES: Final[frozenset[str]] = frozenset(
    [
        "d_containers.jinja2",
        "d_images.jinja2",
        "b_base.jinja2",
        "a_auth.jinja2",
    ]
)


def _get_jinja_environment() -> Environment:
    """Get singleton Jinja2 environment with lazy initialization."""
    global _environment

    if _environment is not None:
        return _environment

    with _env_lock:
        if _environment is not None:
            return _environment

        template_path = Path(var_config.template_path)

        if not template_path.exists():
            raise exceptions.TemplateError(
                ErrorContext(
                    message=f"Template directory not found: {template_path}",
                    error_code="TEMPLATE_DIR_001",
                    metadata={"template_path": str(template_path)},
                )
            )

        _environment = SandboxedEnvironment(
            loader=FileSystemLoader(template_path, followlinks=False, encoding="utf-8"),
            autoescape=select_autoescape(
                enabled_extensions=("html", "txt", "jinja2"),
                default_for_string=True,
            ),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            finalize=lambda x: x if x is not None else "",
            cache_size=200,  # Jinja internal cache
            auto_reload=False,
        )

        # Register filters
        from pytmbot.parsers.filters import (
            format_bytes,
            format_duration,
            format_timestamp,
        )

        _environment.filters.update(
            {
                "format_timestamp": format_timestamp,
                "format_bytes": format_bytes,
                "format_duration": format_duration,
            }
        )

        return _environment


@lru_cache(maxsize=64)
def _resolve_template_subdirectory(template_name: str) -> str:
    """Resolve template subdirectory with caching."""
    if template_name.startswith(_PLUGIN_PREFIX):
        try:
            plugin_name = template_name.split("_", 1)[1].split(".", 1)[
                0
            ]  # Remove extension
            return f"{_PLUGIN_TEMPLATE_BASE}/{plugin_name}"
        except IndexError as e:
            raise exceptions.TemplateError(
                ErrorContext(
                    message=f"Invalid plugin template name: {template_name}",
                    error_code="TEMPLATE_PLUGIN_001",
                    metadata={"template_name": template_name},
                )
            ) from e

    try:
        first_char = template_name[0].lower()
        return _TEMPLATE_SUBDIRECTORIES[first_char]
    except (IndexError, KeyError) as e:
        raise exceptions.TemplateError(
            ErrorContext(
                message=f"Unknown template pattern: {template_name}",
                error_code="TEMPLATE_PATTERN_001",
                metadata={"template_name": template_name},
            )
        ) from e


def _load_template(template_name: str) -> Template:
    """Load template with TTL caching."""
    with _cache_lock:
        template = _template_cache.get(template_name)
        if isinstance(template, Template):
            return template

    # Load from filesystem
    env = _get_jinja_environment()
    subdirectory = _resolve_template_subdirectory(template_name)
    template_path = f"{subdirectory}/{template_name}"

    try:
        template = env.get_template(template_path)

        with _cache_lock:
            _template_cache[template_name] = template

        return template

    except TemplateNotFound as e:
        raise exceptions.TemplateError(
            ErrorContext(
                message=f"Template not found: {template_name}",
                error_code="TEMPLATE_NOT_FOUND",
                metadata={
                    "template_name": template_name,
                    "template_path": template_path,
                },
            )
        ) from e
    except TemplateError as e:
        raise exceptions.TemplateError(
            ErrorContext(
                message=f"Template error: {template_name}",
                error_code="TEMPLATE_ERROR",
                metadata={"template_name": template_name},
            )
        ) from e


def _hash_context(context: dict[str, Any]) -> str | None:
    """Create hash of context for result caching."""
    # Simple hash for cacheable contexts
    try:
        context_str = str(sorted(context.items()))
        return hashlib.md5(context_str.encode()).hexdigest()[:16]
    except (TypeError, ValueError):
        # If context not hashable, don't cache
        return None


def _render_template_hot(template_name: str, context: dict[str, Any]) -> str:
    """Fast path for hot templates."""
    template = _load_template(template_name)
    return template.render(**context)


def _render_template_cached(template_name: str, context: dict[str, Any]) -> str:
    """Cached rendering for stable contexts."""
    context_hash = _hash_context(context)

    if context_hash:
        cache_key = f"{template_name}:{context_hash}"
        with _cache_lock:
            result = _result_cache.get(cache_key)
            if isinstance(result, str):
                return result

    # Render and cache
    result = _render_template_hot(template_name, context)

    if context_hash:
        with _cache_lock:
            _result_cache[cache_key] = result

    return result


def _render_template(
    template_name: str,
    trusted: bool = False,
    **kwargs: Any,
) -> str:
    """Core template rendering with integrated validation."""

    # Use proper validation based on trust level
    if trusted:
        # Fast validation for internal/trusted templates
        from pytmbot.parsers.validation import (
            validate_context_basic,
            validate_template_name_fast,
        )

        validated_name = validate_template_name_fast(template_name)
        validated_context = validate_context_basic(kwargs)
    else:
        # Strict validation for untrusted input
        from pytmbot.parsers.validation import validate_template_render

        validated_name, validated_context = validate_template_render(
            template_name, kwargs, trusted=False
        )

    try:
        # Hot path for frequently used templates
        if validated_name in _HOT_TEMPLATES:
            return _render_template_hot(validated_name, validated_context)

        # Cached path for others
        return _render_template_cached(validated_name, validated_context)

    except Exception as e:
        if isinstance(e, exceptions.TemplateError):
            raise
        raise exceptions.TemplateError(
            ErrorContext(
                message=f"Failed to render template: {validated_name}",
                error_code="TEMPLATE_RENDER_ERROR",
                metadata={
                    "template_name": validated_name,
                    "trusted": trusted,
                    "error_type": type(e).__name__,
                },
            )
        ) from e


def _precompile_templates() -> None:
    """Precompile common templates at startup."""
    template_path = Path(var_config.template_path)

    if not template_path.exists():
        return

    # Preload hot templates
    for template_name in _HOT_TEMPLATES:
        try:
            _load_template(template_name)
        except Exception:
            # Don't fail startup if template missing
            pass


def _get_cache_stats() -> dict[str, Any]:
    """Get comprehensive cache and validation statistics."""
    with _cache_lock:
        stats = {
            "template_cache_size": len(_template_cache),
            "template_cache_hits": _template_cache.hits
            if hasattr(_template_cache, "hits")
            else 0,
            "template_cache_misses": _template_cache.misses
            if hasattr(_template_cache, "misses")
            else 0,
            "result_cache_size": len(_result_cache),
            "subdirectory_cache_info": _resolve_template_subdirectory.cache_info(),
            "environment_initialized": _environment is not None,
        }

    # Add validation stats
    try:
        from pytmbot.parsers.validation import get_validation_stats

        stats["validation"] = get_validation_stats()
    except ImportError:
        stats["validation"] = {"error": "validation module not available"}

    return stats


def _clear_template_cache() -> None:
    """Clear all caches including validation cache."""
    global _environment, _template_cache, _result_cache

    with _cache_lock:
        _template_cache.clear()
        _result_cache.clear()

    with _env_lock:
        _environment = None

    _resolve_template_subdirectory.cache_clear()

    # Clear validation cache too
    try:
        from pytmbot.parsers.validation import clear_validation_cache

        clear_validation_cache()
    except ImportError:
        pass


# Initialize on import
_precompile_templates()
