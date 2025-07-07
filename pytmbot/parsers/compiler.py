#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Dict, Final

from pytmbot.exceptions import TemplateError, ErrorContext
from pytmbot.logs import BaseComponent
from pytmbot.parsers._parser import Jinja2Renderer


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


class Compiler(BaseComponent):
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
        "plugin_": TemplateType.PLUGIN,
    }

    def __init__(self, template_name: str, **context: Any) -> None:
        """
        Initialize the compiler with template details.

        Args:
            template_name: Name of the template to compile
            context: Template context data

        Raises:
            PyTMBotErrorTemplateError: If template name is invalid
        """
        super().__init__("template_compiler")
        self._template_name = template_name
        self._context = context
        self._encoding: str = CompilerConfig.DEFAULT_ENCODING
        self._renderer = Jinja2Renderer.instance()

        with self.log_context(
            action="init", template=template_name, context_keys=list(context.keys())
        ) as log:
            log.info("Template compiler initialized")

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

        with self.log_context(
            action="template_type", template_name=self._template_name
        ) as log:
            log.error("Unknown template prefix")
            raise TemplateError(
                ErrorContext(
                    message="Unknown template prefix",
                    error_code="UNKNOWN_TEMPLATE_PREFIX",
                    metadata={"template_name": self._template_name},
                )
            )

    def compile(self) -> str:
        """
        Compile the template with provided context.

        Returns:
            str: Compiled template content

        Raises:
            PyTMBotErrorTemplateError: If compilation fails
        """
        try:
            with self.log_context(
                action="compile",
                template=self._template_name,
                type=self.template_type.value,
            ) as log:
                log.info("Starting template compilation")

                compiled_content = self._renderer.render_template(
                    template_name=self._template_name, **self._context
                )

                log.success("Template compilation completed successfully")
                return compiled_content

        except Exception as e:
            with self.log_context(
                action="compile", template=self._template_name, error=str(e)
            ) as log:
                log.error("Template compilation failed")
                raise TemplateError(
                    ErrorContext(
                        message="Template compilation failed",
                        error_code="TEMPLATE_COMPILATION_ERROR",
                        metadata={"template": self._template_name, "error": str(e)},
                    )
                )


__all__ = ["Compiler", "TemplateType"]
