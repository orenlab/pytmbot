from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Dict, Final

from pytmbot.exceptions import TemplateError, ErrorContext
from pytmbot.logs import Logger, LogContext
from pytmbot.parsers._parser import Jinja2Renderer

logger = Logger()


class TemplateType(StrEnum):
    """Supported template types."""
    AUTH = "auth"
    BASE = "base"
    DOCKER = "docker"
    PLUGIN = "plugin"


@dataclass(frozen=True)
class CompilerConfig:
    """Template compiler configuration."""
    TEMPLATE_EXTENSIONS: ClassVar[tuple[str, ...]] = (".jinja2",)
    DEFAULT_ENCODING: ClassVar[str] = "utf-8"


class Compiler:
    """
    Template compiler that uses Jinja2Renderer for template rendering.

    Provides a context manager interface for template compilation with
    proper resource management and error handling.

    Example:
        template_context = {
            'images': images,
            'emojis': {
                'thought_balloon': em.get_emoji("thought_balloon"),
                'spouting_whale': em.get_emoji("spouting_whale"),
                'minus': em.get_emoji("minus")
            }
        }

        with Compiler(
                template_name="d_images.jinja2",
                context=template_context
        ) as compiler:
            bot_answer = compiler.compile()
    """

    _TEMPLATE_TYPE_PREFIXES: Final[Dict[str, TemplateType]] = {
        "a_": TemplateType.AUTH,
        "b_": TemplateType.BASE,
        "d_": TemplateType.DOCKER,
        "plugin_": TemplateType.PLUGIN
    }

    def __init__(
            self,
            template_name: str,
            **context: Any
    ) -> None:
        """
        Initialize the compiler with template details.

        Args:
            template_name: Name of the template to compile
            context: Template context data
            encoding: Character encoding (default: utf-8)

        Raises:
            PyTMBotErrorTemplateError: If template name is invalid
        """
        self._template_name = template_name
        self._context = context
        self._encoding: str = CompilerConfig.DEFAULT_ENCODING
        self._renderer = Jinja2Renderer.instance()

        with LogContext(logger) as log:
            log.info("Template compiler initialized",
                     extra={
                         "template": template_name,
                         "context_keys": list(context.keys())
                     })

    def __enter__(self) -> Compiler:
        """Context manager entry point."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit point."""
        pass

    @property
    def template_type(self) -> TemplateType:
        """
        Determine template type from template name prefix.

        Returns:
            TemplateType: Determined template type

        Raises:
            PyTMBotErrorTemplateError: If template prefix is unknown
        """
        for prefix, template_type in self._TEMPLATE_TYPE_PREFIXES.items():
            if self._template_name.startswith(prefix):
                return template_type

        with LogContext(logger) as log:
            log.error("Unknown template prefix",
                      extra={"template_name": self._template_name})
            raise TemplateError(ErrorContext(
                message="Unknown template prefix",
                error_code="UNKNOWN_TEMPLATE_PREFIX",
                metadata={"template_name": self._template_name}
            ))

    def compile(self) -> str:
        """
        Compile the template with provided context.

        Returns:
            str: Compiled template content

        Raises:
            PyTMBotErrorTemplateError: If compilation fails
        """
        with LogContext(logger) as log:
            try:
                log.info("Starting template compilation",
                         extra={
                             "template": self._template_name,
                             "type": self.template_type.value
                         })

                compiled_content = self._renderer.render_templates(
                    template_name=self._template_name,
                    **self._context
                )

                log.success("Template compilation completed")

                return compiled_content

            except Exception as e:
                log.error("Template compilation failed",
                          extra={
                              "template": self._template_name,
                              "error": str(e)
                          })
                raise TemplateError(ErrorContext(
                    message="Template compilation failed",
                    error_code="TEMPLATE_COMPILATION_ERROR",
                    metadata={
                        "template": self._template_name,
                        "error": str(e)
                    }
                ))


__all__ = ["Compiler", "TemplateType"]
