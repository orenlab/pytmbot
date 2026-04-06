#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from types import TracebackType
from typing import ClassVar, Final

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


_TEMPLATE_TYPE_PREFIXES: Final[dict[str, TemplateType]] = {
    "a_": TemplateType.AUTH,
    "b_": TemplateType.BASE,
    "d_": TemplateType.DOCKER,
    "plugin_": TemplateType.PLUGIN,
}


def detect_template_type(template_name: str) -> TemplateType:
    """Determine template type from filename prefix."""
    for prefix, template_type in _TEMPLATE_TYPE_PREFIXES.items():
        if template_name.startswith(prefix):
            return template_type

    raise TemplateError(
        ErrorContext(
            message="Unknown template type prefix",
            error_code="UNKNOWN_TEMPLATE_PREFIX",
            metadata={
                "template_name": template_name,
                "supported_prefixes": list(_TEMPLATE_TYPE_PREFIXES),
            },
        )
    )


def quick_render_template(template_name: str, **context: TemplateValue) -> str:
    """Quick rendering for trusted templates without the compiler context manager."""
    return _render_template(template_name, trusted=True, context=context)


def _compile_template(
    component: BaseComponent,
    *,
    template_name: str,
    context: dict[str, TemplateValue],
    strict: bool,
) -> str:
    try:
        if strict:
            with component.log_context(
                action="compile_template",
                template_name=template_name,
            ) as log:
                log.debug("bot.parsers.compiler.compiling.untrusted.debug")

        return _render_template(
            template_name,
            trusted=not strict,
            context=context,
        )

    except Exception as error:
        with component.log_context(
            action="compile_template_error",
            template_name=template_name,
            strict=strict,
        ) as log:
            log.error("bot.parsers.compiler.template.compilation.fail")

        if isinstance(error, TemplateError):
            raise

        raise TemplateError(
            ErrorContext(
                message="Template compilation failed",
                error_code="TEMPLATE_COMPILATION_ERROR",
                metadata={
                    "template_name": template_name,
                    "strict": strict,
                    "error": str(error),
                },
            )
        ) from error


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
    quick_render: ClassVar[Callable[..., str]]

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
        return None

    @property
    def template_type(self) -> TemplateType:
        """Determine template type from name prefix."""
        return detect_template_type(self.template_name)

    def compile(self) -> str:
        """Compile the template with the current trust mode and context."""
        return _compile_template(
            self,
            template_name=self.template_name,
            context=self.context,
            strict=self.strict,
        )


Compiler.quick_render = staticmethod(quick_render_template)


__all__ = [
    "Compiler",
    "TemplateType",
]
