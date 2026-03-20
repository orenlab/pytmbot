#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from enum import StrEnum
from types import TracebackType
from typing import Final

from pytmbot.exceptions import ErrorContext, TemplateError
from pytmbot.logs import BaseComponent
from pytmbot.parsers._parser import _render_template
from pytmbot.parsers._types import TemplateValue


class TemplateType(StrEnum):
    """Supported template types."""

    AUTH = "auth"
    BASE = "base"
    DOCKER = "docker"
    PLUGIN = "plugin"


class Compiler(BaseComponent):
    """
    Template compiler with context manager interface.

    Provides safe, easy-to-use template compilation with proper resource management.
    Uses optimized private parser implementation internally.

    Example:
        # Trusted template (from internal code)
        with Compiler("d_images.jinja2", images=imgs, trusted=True) as c:
            output = c.compile()

        # Untrusted template (from user input)
        with Compiler(user_template, data=data, trusted=False) as c:
            output = c.compile()
    """

    __slots__ = ("template_name", "context", "strict")

    TEMPLATE_TYPE_PREFIXES: Final[dict[str, TemplateType]] = {
        "a_": TemplateType.AUTH,
        "b_": TemplateType.BASE,
        "d_": TemplateType.DOCKER,
        "plugin_": TemplateType.PLUGIN,
    }

    def __init__(
        self,
        template_name: str,
        trusted: bool = False,
        **context: TemplateValue,
    ) -> None:
        """
        Initialize compiler with template and context.

        Args:
            template_name: Name of the template file
            trusted: If True, use fast validation for internal templates.
            **context: Template context variables
        """
        super().__init__("template_compiler")
        self.template_name = template_name
        self.context = context
        self.strict = not trusted

    def __enter__(self) -> Compiler:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit."""
        pass

    @property
    def template_type(self) -> TemplateType:
        """
        Determine template type from name prefix.

        Returns:
            TemplateType: Detected template type

        Raises:
            TemplateError: If template prefix is unknown
        """
        for prefix, template_type in self.TEMPLATE_TYPE_PREFIXES.items():
            if self.template_name.startswith(prefix):
                return template_type

        raise TemplateError(
            ErrorContext(
                message="Unknown template type prefix",
                error_code="UNKNOWN_TEMPLATE_PREFIX",
                metadata={
                    "template_name": self.template_name,
                    "supported_prefixes": list(self.TEMPLATE_TYPE_PREFIXES),
                },
            )
        )

    def compile(self) -> str:
        """
        Compile template with integrated validation and context.

        Returns:
            str: Rendered template content

        Raises:
            TemplateError: If compilation fails
        """
        try:
            # Light logging only for untrusted templates or errors
            if self.strict:
                with self.log_context(
                    action="compile_template",
                    template_name=self.template_name,
                ) as log:
                    log.debug("bot.parsers.compiler.compiling.untrusted.debug")

            # Validation is now handled inside _render_template
            result = _render_template(
                self.template_name,
                trusted=not self.strict,
                context=self.context,
            )

            return result

        except Exception as e:
            # Always log errors
            with self.log_context(
                action="compile_template_error",
                template_name=self.template_name,
                strict=self.strict,
            ) as log:
                log.error("bot.parsers.compiler.template.compilation.fail")

            if isinstance(e, TemplateError):
                raise

            raise TemplateError(
                ErrorContext(
                    message="Template compilation failed",
                    error_code="TEMPLATE_COMPILATION_ERROR",
                    metadata={
                        "template_name": self.template_name,
                        "strict": self.strict,
                        "error": str(e),
                    },
                )
            ) from e

    @staticmethod
    def quick_render(template_name: str, **context: TemplateValue) -> str:
        """
        Quick rendering for trusted templates without context manager.

        Args:
            template_name: Template name (must be trusted)
            **context: Template context

        Returns:
            str: Rendered template
        """
        return _render_template(template_name, trusted=True, context=context)


__all__ = [
    "Compiler",
    "TemplateType",
]
