from __future__ import annotations

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
from pytmbot.logs import Logger, LogContext
from pytmbot.parsers.filters import format_timestamp

logger = Logger()

TEMPLATE_SUBDIRECTORIES: Final[Dict[str, str]] = {
    'a': 'auth_templates',
    'b': 'base_templates',
    'd': 'docker_templates',
}


@dataclass(frozen=True)
class TemplateMetadata:
    """Metadata for template caching and identification."""
    name: str
    subdirectory: str

    def __hash__(self) -> int:
        return hash((self.name, self.subdirectory))


class Jinja2Renderer:
    """
    A thread-safe singleton class for rendering Jinja2 templates with caching support.

    This class implements the Singleton pattern and provides a sandboxed environment
    for secure template rendering with weak reference caching.
    """

    _instance: ClassVar[Optional[Jinja2Renderer]] = None
    _jinja_env: ClassVar[Optional[Environment]] = None

    def __init__(self) -> None:
        """Initialize the renderer with a weak reference cache for templates."""
        self._template_cache: WeakValueDictionary[TemplateMetadata, Template] = WeakValueDictionary()

        with LogContext(logger) as log:
            log.info("Initializing Jinja2Renderer instance",
                     extra={"cache_type": "WeakValueDictionary"})

    @classmethod
    def instance(cls) -> Jinja2Renderer:
        """
        Get or create the singleton instance of Jinja2Renderer.

        Returns:
            Jinja2Renderer: The singleton instance.

        Thread-safety: This method is thread-safe through Python's GIL.
        """
        if cls._instance is None:
            with LogContext(logger) as log:
                log.info("Creating new Jinja2Renderer singleton instance")
                cls._instance = cls._initialize_instance()
                log.debug("Jinja2Renderer singleton instance created successfully")
        return cls._instance

    @classmethod
    def _initialize_instance(cls) -> Jinja2Renderer:
        """
        Initialize the Jinja2Renderer instance with its environment.

        Returns:
            Jinja2Renderer: A newly initialized instance.
        """
        with LogContext(logger) as log:
            log.info("Initializing Jinja2 environment")
            cls._jinja_env = cls._create_jinja_environment()
            return cls()

    @staticmethod
    def _create_jinja_environment() -> Environment:
        """
        Create and configure a sandboxed Jinja2 environment.

        Returns:
            Environment: A configured Jinja2 environment.

        Security: Uses SandboxedEnvironment to prevent code execution in templates.
        """
        template_path = Path(var_config.template_path)

        with LogContext(logger) as log:
            log.info("Creating Jinja2 environment",
                     extra={"template_path": str(template_path)})

            env = SandboxedEnvironment(
                loader=FileSystemLoader(template_path),
                autoescape=select_autoescape(
                    enabled_extensions=('html', 'txt', 'jinja2'),
                    default_for_string=True
                ),
                trim_blocks=True,
                lstrip_blocks=True,
            )

            # Register custom filters
            env.filters['format_timestamp'] = format_timestamp

            log.debug("Jinja2 environment created successfully",
                      extra={"filters": list(env.filters.keys())})
            return env

    def render_templates(
            self,
            template_name: str,
            emojis: Optional[Dict[str, str]] = None,
            **kwargs: Any,
    ) -> str:
        """
        Render a Jinja2 template with the given context.

        Args:
            template_name: Name of the template to render
            emojis: Optional emoji mappings for template
            **kwargs: Template context variables

        Returns:
            str: The rendered template string

        Raises:
            PyTMBotErrorTemplateError: If template rendering fails

        Security: All template rendering is done in a sandboxed environment
        """
        try:
            with LogContext(logger) as log:
                log.info(f"Rendering template",
                         extra={
                             "template": template_name,
                             "context_keys": list(kwargs.keys())
                         })

                template_subdir = self._get_template_subdirectory(template_name)
                template = self._get_template(
                    TemplateMetadata(template_name, template_subdir)
                )

                rendered = template.render(emojis=emojis or {}, **kwargs)

                log.debug("Template rendered successfully",
                          extra={"template": template_name,
                                 "output_length": len(rendered)})
                return rendered

        except TemplateError as error:
            with LogContext(logger) as log:
                log.error("Template rendering failed",
                          extra={
                              "template": template_name,
                              "error": str(error)
                          })
            raise exceptions.TemplateError(ErrorContext(
                message="Template rendering failed",
                error_code="TEMPLATE_001",
                metadata={"template": template_name, "error": str(error)}
            ))

    @lru_cache(maxsize=128)
    def _get_template_subdirectory(self, template_name: str) -> str:
        """
        Get the subdirectory for a template using LRU cache.

        Args:
            template_name: Name of the template

        Returns:
            str: Subdirectory path for the template

        Raises:
            PyTMBotErrorTemplateError: If template subdirectory cannot be determined
        """
        if template_name.startswith("plugin_"):
            plugin_name = template_name.split("_", 1)[1]
            return f"plugins_template/{plugin_name}"

        try:
            return TEMPLATE_SUBDIRECTORIES[template_name[0]]
        except (IndexError, KeyError) as error:
            with LogContext(logger) as log:
                log.error("Invalid template name",
                          extra={
                              "template": template_name,
                              "error": str(error)
                          })
            raise exceptions.TemplateError(ErrorContext(
                message="Invalid template name",
                error_code="TEMPLATE_002",
                metadata={"template": template_name, "error": str(error)}
            ))

    def _get_template(self, metadata: TemplateMetadata) -> Template:
        """
        Get a template from cache or load it from filesystem.

        Args:
            metadata: Template metadata for identification

        Returns:
            Template: The requested Jinja2 template

        Raises:
            PyTMBotErrorTemplateError: If template cannot be loaded
        """
        if template := self._template_cache.get(metadata):
            return template

        try:
            with LogContext(logger) as log:
                log.debug("Template cache miss, loading from filesystem",
                          extra={
                              "template": metadata.name,
                              "subdirectory": metadata.subdirectory
                          })

                template_path = Path(metadata.subdirectory) / metadata.name
                template = self._jinja_env.get_template(str(template_path))
                self._template_cache[metadata] = template

                log.info("Template loaded and cached successfully",
                         extra={"template_path": str(template_path)})
                return template

        except TemplateError as error:
            with LogContext(logger) as log:
                log.error("Failed to load template",
                          extra={
                              "template": metadata.name,
                              "error": str(error)
                          })
            raise exceptions.TemplateError(ErrorContext(
                message="Failed to load template",
                error_code="TEMPLATE_003",
                metadata={"template": metadata.name, "error": str(error)}
            ))
