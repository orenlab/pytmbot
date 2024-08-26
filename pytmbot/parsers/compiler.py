#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Any, Dict

from pytmbot.parsers._parser import Jinja2Renderer


class Compiler:
    """
    A class to compile Jinja2 templates using a context manager.

    Attributes:
        template_name (str): The name of the template to compile.
        kwargs (Dict[str, Any]): The context for rendering the template.
    """

    def __init__(self, template_name: str, **kwargs: Dict[str, Any]) -> None:
        """
        Initialize the Compiler with template name and context.

        Args:
            template_name (str): The name of the template to compile.
            **kwargs (Dict[str, Any]): The context for rendering the template.
        """
        self.template_name = template_name
        self.kwargs = kwargs
        self.renderer = None

    def __enter__(self) -> 'Compiler':
        """
        Enter the runtime context related to this object.

        Returns:
            Compiler: The instance of Compiler.
        """
        self.renderer = Jinja2Renderer.instance()
        return self

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: Any) -> None:
        """
        Exit the runtime context related to this object.

        Args:
            exc_type (type): The exception type.
            exc_val (Exception): The exception value.
            exc_tb (Any): The traceback object.
        """
        # No specific cleanup needed for renderer
        self.renderer = None

    def compile(self) -> str:
        """
        Compile the template with the given context.

        Returns:
            str: The rendered template as a string.

        Raises:
            ValueError: If the renderer is not initialized.
        """
        if self.renderer:
            try:
                return self.renderer.render_templates(self.template_name, **self.kwargs)
            except Exception as e:
                # Handle specific exceptions if needed
                raise RuntimeError("Error during template compilation") from e
        else:
            raise ValueError("Renderer is not initialized. Use 'with' statement to initialize it.")
