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
import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Final

from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from jinja2.exceptions import TemplateError, TemplateNotFound
from jinja2.sandbox import SandboxedEnvironment

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import var_config
from pytmbot.parsers._types import ParserStats, TemplateContext, TemplateValue

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
    maxsize=15, ttl=1800
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
            plugin_suffix = template_name.split("_", 1)[1].split(".", 1)[0]
            plugin_name = plugin_suffix.split("_", 1)[0]
            if not plugin_name:
                raise ValueError("empty plugin name")
            return f"{_PLUGIN_TEMPLATE_BASE}/{plugin_name}"
        except (IndexError, ValueError) as e:
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


def _hash_context(context: TemplateContext) -> str | None:
    """Create hash of context for result caching."""
    if any(not isinstance(key, str) for key in context):
        return None

    def _contains_dynamic_values(value: TemplateValue) -> bool:
        if isinstance(value, (datetime, date)):
            return True
        if isinstance(value, float):
            return True
        if isinstance(value, dict):
            return any(
                _contains_dynamic_values(dict_key)
                or _contains_dynamic_values(dict_value)
                for dict_key, dict_value in value.items()
            )
        if isinstance(value, (list, tuple, set, frozenset)):
            return any(_contains_dynamic_values(item) for item in value)
        return False

    if any(_contains_dynamic_values(value) for value in context.values()):
        return None

    def _normalize_for_hash(value: TemplateValue) -> TemplateValue:
        if isinstance(value, dict):
            return {
                str(dict_key): _normalize_for_hash(dict_value)
                for dict_key, dict_value in sorted(
                    value.items(), key=lambda item: str(item[0])
                )
            }
        if isinstance(value, (list, tuple)):
            return [_normalize_for_hash(item) for item in value]
        if isinstance(value, (set, frozenset)):
            normalized_set = [_normalize_for_hash(item) for item in value]
            return sorted(
                normalized_set,
                key=lambda item: json.dumps(
                    item, sort_keys=True, ensure_ascii=True, separators=(",", ":")
                ),
            )
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    # Stable hash for cacheable contexts
    try:
        normalized_context = _normalize_for_hash(context)
        context_json = json.dumps(
            normalized_context,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.blake2b(context_json.encode(), digest_size=8).hexdigest()
    except (TypeError, ValueError, OverflowError):
        # If context not hashable, don't cache
        return None


def _render_template_hot(template_name: str, context: TemplateContext) -> str:
    """Fast path for hot templates."""
    template = _load_template(template_name)
    return template.render(**context)


def _render_template_cached(template_name: str, context: TemplateContext) -> str:
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
    *,
    context: TemplateContext | None = None,
    strict: bool = True,
    trusted: bool | None = None,
    **kwargs: TemplateValue,
) -> str:
    """Core template rendering with integrated validation."""
    render_context: TemplateContext = dict(context) if context is not None else {}
    render_context.update(kwargs)

    strict_mode = strict if trusted is None else not trusted

    if not strict_mode:
        # Fast validation for internal/trusted templates
        from pytmbot.parsers.validation import (
            validate_context_basic,
            validate_template_name_fast,
        )

        validated_name = validate_template_name_fast(template_name)
        validated_context = validate_context_basic(render_context)
    else:
        # Strict validation for untrusted input
        from pytmbot.parsers.validation import validate_template_render

        validated_name, validated_context = validate_template_render(
            template_name,
            render_context,
            strict=True,
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
                    "strict": strict_mode,
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


def _get_cache_stats() -> ParserStats:
    """Get comprehensive cache and validation statistics."""
    cache_info = _resolve_template_subdirectory.cache_info()
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
            "subdirectory_cache_info": {
                "hits": cache_info.hits,
                "misses": cache_info.misses,
                "maxsize": cache_info.maxsize,
                "currsize": cache_info.currsize,
            },
            "environment_initialized": _environment is not None,
        }

    # Add validation stats
    try:
        from pytmbot.parsers.validation import get_validation_stats

        stats["validation"] = get_validation_stats()
    except ImportError:
        stats["validation"] = {"error": "validation module not available"}

    return stats


# Initialize on import
_precompile_templates()
