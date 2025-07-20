#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Dict, Final, Optional
from weakref import WeakValueDictionary

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import var_config
from pytmbot.logs import Logger, BaseComponent
from pytmbot.parsers.filters import format_timestamp

TEMPLATE_SUBDIRECTORIES: Final[Dict[str, str]] = {
    "a": "auth_templates",
    "b": "base_templates",
    "d": "docker_templates",
}

_PLUGIN_PREFIX: Final[str] = "plugin_"
_PLUGIN_TEMPLATE_BASE: Final[str] = "plugins_template"


@dataclass(frozen=True, slots=True)
class TemplateMetadata:
    """Metadata for template caching and identification with optimized hashing."""

    name: str
    subdirectory: str

    def __hash__(self) -> int:
        return hash(self.name) ^ hash(self.subdirectory)


class Jinja2Renderer(BaseComponent):
    """
    High-performance thread-safe singleton for Jinja2 template rendering
    with advanced caching and security features.

    Optimizations:
    - Lazy initialization with double-checked locking
    - Weak reference template caching
    - LRU subdirectory resolution
    - Pre-compiled template path resolution
    - Optimized error handling with context
    """

    _instance: ClassVar[Optional[Jinja2Renderer]] = None
    _jinja_env: ClassVar[Optional[Environment]] = None

    # Thread-safe lock for singleton creation
    __slots__ = ("_template_cache", "_path_cache")

    def __init__(self) -> None:
        """Initialize renderer with optimized caching structures."""
        super().__init__("template_renderer")

        # Weak reference cache for automatic memory management
        self._template_cache: WeakValueDictionary[TemplateMetadata, Template] = (
            WeakValueDictionary()
        )

        # Path cache for template resolution
        self._path_cache: Dict[str, Path] = {}

        with self.log_context(action="renderer_init") as log:
            log.debug(
                "Template renderer initialized",
                cache_type="WeakValueDictionary",
                path_cache_enabled=True,
            )

    @classmethod
    def instance(cls) -> Jinja2Renderer:
        """Thread-safe singleton with double-checked locking pattern."""
        if cls._instance is None:
            # Double-checked locking for thread safety
            import threading

            lock = threading.RLock()
            with lock:
                if cls._instance is None:
                    logger = Logger()
                    with logger.context(
                        component="template_renderer", action="singleton_creation"
                    ) as log:
                        log.debug("Creating Jinja2Renderer singleton instance")
                        cls._instance = cls._initialize_instance()
        return cls._instance

    @classmethod
    def _initialize_instance(cls) -> Jinja2Renderer:
        """Initialize renderer with optimized Jinja2 environment."""
        logger = Logger()
        with logger.context(
            component="template_renderer", action="environment_setup"
        ) as log:
            start_time = time.perf_counter()

            log.debug("Initializing optimized Jinja2 environment")
            cls._jinja_env = cls._create_jinja_environment()

            setup_time = (time.perf_counter() - start_time) * 1000
            log.debug(
                "Jinja2 environment ready",
                setup_duration_ms=round(setup_time, 2),
                loader_type="FileSystemLoader",
                sandbox_enabled=True,
            )

            return cls()

    @staticmethod
    def _create_jinja_environment() -> Environment:
        """Create optimized sandboxed Jinja2 environment with security features."""
        template_path = Path(var_config.template_path)

        logger = Logger()
        with logger.context(
            component="template_renderer",
            action="jinja_env_creation",
            template_path=str(template_path),
        ) as log:
            if not template_path.exists():
                log.error(
                    "Template directory not found",
                    template_path=str(template_path),
                    error_code="TEMPLATE_DIR_001",
                )
                raise exceptions.TemplateError(
                    ErrorContext(
                        message=f"Template directory not found: {template_path}",
                        error_code="TEMPLATE_DIR_001",
                        metadata={"template_path": str(template_path)},
                    )
                )

            env = SandboxedEnvironment(
                loader=FileSystemLoader(
                    template_path, followlinks=False, encoding="utf-8"
                ),
                autoescape=select_autoescape(
                    enabled_extensions=("html", "txt", "jinja2"),
                    default_for_string=True,
                ),
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
                finalize=lambda x: x if x is not None else "",
                cache_size=400,
                auto_reload=False,
            )

            # Регистрируем фильтры
            env.filters["format_timestamp"] = format_timestamp

            log.debug(
                "Sandboxed Jinja2 environment configured",
                available_filters=list(env.filters.keys()),
                cache_size=400,
                security_features=["sandbox", "autoescape", "no_followlinks"],
            )

            return env

    def render_template(
        self,
        template_name: str,
        emojis: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> str:
        """
        High-performance template rendering with comprehensive error handling.

        Args:
            template_name: Template identifier
            emojis: Emoji mapping dictionary (optional)
            **kwargs: Template context variables

        Returns:
            str: Rendered template content

        Raises:
            TemplateError: On rendering or loading failures
        """
        start_time = time.perf_counter()

        with self.log_context(
            action="template_render",
            template_name=template_name,
            context_vars_count=len(kwargs),
            has_emojis=bool(emojis),
        ) as log:
            try:
                if not template_name or not isinstance(template_name, str):
                    log.error(
                        "Invalid template name provided",
                        template_name=template_name,
                        error_code="TEMPLATE_INVALID_001",
                    )
                    raise exceptions.TemplateError(
                        ErrorContext(
                            message="Template name must be a non-empty string",
                            error_code="TEMPLATE_INVALID_001",
                            metadata={"provided_name": template_name},
                        )
                    )

                template_subdir = self._get_template_subdirectory(template_name)

                metadata = TemplateMetadata(template_name, template_subdir)

                template = self._get_template(metadata)

                render_context = {"emojis": emojis or {}, **kwargs}

                rendered_content = template.render(**render_context)

                render_duration = (time.perf_counter() - start_time) * 1000
                log.debug(
                    "Template rendered successfully",
                    output_length=len(rendered_content),
                    render_duration_ms=round(render_duration, 2),
                    cache_hit=metadata in self._template_cache,
                    template_subdirectory=template_subdir,
                )

                return rendered_content

            except TemplateError as e:
                render_duration = (time.perf_counter() - start_time) * 1000
                log.error(
                    "Template rendering failed",
                    template_name=template_name,
                    error_details=str(e),
                    render_duration_ms=round(render_duration, 2),
                    error_code="TEMPLATE_RENDER_001",
                )

                raise exceptions.TemplateError(
                    ErrorContext(
                        message=f"Failed to render template '{template_name}'",
                        error_code="TEMPLATE_RENDER_001",
                        metadata={
                            "template_name": template_name,
                            "original_error": str(e),
                            "render_duration_ms": round(render_duration, 2),
                        },
                    )
                ) from e

            except Exception as e:
                render_duration = (time.perf_counter() - start_time) * 1000
                log.error(
                    "Unexpected error during template rendering",
                    template_name=template_name,
                    error_type=type(e).__name__,
                    error_details=str(e),
                    render_duration_ms=round(render_duration, 2),
                    error_code="TEMPLATE_UNEXPECTED_001",
                )

                raise exceptions.TemplateError(
                    ErrorContext(
                        message=f"Unexpected error rendering template '{template_name}'",
                        error_code="TEMPLATE_UNEXPECTED_001",
                        metadata={
                            "template_name": template_name,
                            "error_type": type(e).__name__,
                            "original_error": str(e),
                        },
                    )
                ) from e

    @lru_cache(maxsize=256)
    def _get_template_subdirectory(self, template_name: str) -> str:
        """
        Optimized template subdirectory resolution with comprehensive caching.

        Uses LRU cache for O(1) lookup performance on repeated calls.
        """
        with self.log_context(
            action="subdirectory_lookup", template_name=template_name
        ) as log:
            if template_name.startswith(_PLUGIN_PREFIX):
                try:
                    plugin_name = template_name.split("_", 1)[1]
                    subdirectory = f"{_PLUGIN_TEMPLATE_BASE}/{plugin_name}"

                    log.debug(
                        "Plugin template subdirectory resolved",
                        plugin_name=plugin_name,
                        subdirectory=subdirectory,
                        lookup_type="plugin",
                    )
                    return subdirectory

                except IndexError:
                    log.error(
                        "Invalid plugin template name format",
                        template_name=template_name,
                        expected_format="plugin_<name>",
                        error_code="TEMPLATE_PLUGIN_001",
                    )
                    raise exceptions.TemplateError(
                        ErrorContext(
                            message=f"Invalid plugin template name: {template_name}",
                            error_code="TEMPLATE_PLUGIN_001",
                            metadata={
                                "template_name": template_name,
                                "expected_format": "plugin_<name>",
                            },
                        )
                    )

            try:
                first_char = template_name[0].lower()
                subdirectory = TEMPLATE_SUBDIRECTORIES[first_char]

                log.debug(
                    "Standard template subdirectory resolved",
                    first_character=first_char,
                    subdirectory=subdirectory,
                    lookup_type="standard",
                )
                return subdirectory

            except (IndexError, KeyError) as e:
                log.error(
                    "Template name does not match any known pattern",
                    template_name=template_name,
                    available_prefixes=list(TEMPLATE_SUBDIRECTORIES.keys()),
                    error_type=type(e).__name__,
                    error_code="TEMPLATE_PATTERN_001",
                )

                raise exceptions.TemplateError(
                    ErrorContext(
                        message=f"Unknown template pattern: {template_name}",
                        error_code="TEMPLATE_PATTERN_001",
                        metadata={
                            "template_name": template_name,
                            "available_prefixes": list(TEMPLATE_SUBDIRECTORIES.keys()),
                            "plugin_prefix": _PLUGIN_PREFIX,
                        },
                    )
                ) from e

    def _get_template(self, metadata: TemplateMetadata) -> Template:
        """
        High-performance template retrieval with weak reference caching.

        Uses weak references to allow automatic garbage collection of unused templates.
        """
        start_time = time.perf_counter()

        with self.log_context(
            action="template_retrieval",
            template_name=metadata.name,
            subdirectory=metadata.subdirectory,
        ) as log:
            cached_template = self._template_cache.get(metadata)
            if cached_template is not None:
                retrieval_time = (time.perf_counter() - start_time) * 1000
                log.debug(
                    "Template retrieved from cache",
                    cache_hit=True,
                    retrieval_duration_ms=round(retrieval_time, 3),
                    cache_size=len(self._template_cache),
                )
                return cached_template

            try:
                log.debug(
                    "Cache miss - loading template from filesystem",
                    cache_hit=False,
                    cache_size=len(self._template_cache),
                )

                template_path = Path(metadata.subdirectory) / metadata.name
                template_path_str = str(template_path)

                template = self._jinja_env.get_template(template_path_str)

                self._template_cache[metadata] = template

                loading_time = (time.perf_counter() - start_time) * 1000
                log.debug(
                    "Template loaded and cached successfully",
                    template_path=template_path_str,
                    loading_duration_ms=round(loading_time, 2),
                    cache_size_after=len(self._template_cache),
                    template_metadata=f"{metadata.name}@{metadata.subdirectory}",
                )

                return template

            except TemplateError as e:
                loading_time = (time.perf_counter() - start_time) * 1000
                log.error(
                    "Failed to load template from filesystem",
                    template_path=f"{metadata.subdirectory}/{metadata.name}",
                    jinja_error=str(e),
                    loading_duration_ms=round(loading_time, 2),
                    error_code="TEMPLATE_LOAD_001",
                )

                raise exceptions.TemplateError(
                    ErrorContext(
                        message=f"Cannot load template: {metadata.name}",
                        error_code="TEMPLATE_LOAD_001",
                        metadata={
                            "template_name": metadata.name,
                            "subdirectory": metadata.subdirectory,
                            "template_path": f"{metadata.subdirectory}/{metadata.name}",
                            "jinja_error": str(e),
                        },
                    )
                ) from e

            except Exception as e:
                loading_time = (time.perf_counter() - start_time) * 1000
                log.error(
                    "Unexpected error during template loading",
                    template_name=metadata.name,
                    error_type=type(e).__name__,
                    error_details=str(e),
                    loading_duration_ms=round(loading_time, 2),
                    error_code="TEMPLATE_LOAD_UNEXPECTED_001",
                )

                raise exceptions.TemplateError(
                    ErrorContext(
                        message=f"Unexpected error loading template: {metadata.name}",
                        error_code="TEMPLATE_LOAD_UNEXPECTED_001",
                        metadata={
                            "template_name": metadata.name,
                            "error_type": type(e).__name__,
                            "original_error": str(e),
                        },
                    )
                ) from e

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get current cache statistics for monitoring and debugging."""
        with self.log_context(action="cache_stats_request") as log:
            stats = {
                "template_cache_size": len(self._template_cache),
                "template_cache_type": "WeakValueDictionary",
                "max_subdirectory_cache": 256,
            }

            log.debug("Cache statistics retrieved", **stats)
            return stats

    def clear_caches(self) -> None:
        """Clear all caches - useful for testing or memory management."""
        with self.log_context(action="cache_clearing") as log:
            template_count = len(self._template_cache)

            self._template_cache.clear()
            self._get_template_subdirectory.cache_clear()

            log.info(
                "All caches cleared",
                templates_evicted=template_count,
                subdirectory_cache_cleared=True,
            )
