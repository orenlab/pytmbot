from typing import Any, Dict, Optional

from pytmbot.parsers._parser import Jinja2Renderer


class Compiler:
    """
    A class to compile Jinja2 templates using a context manager.

    Attributes:
        template_name (str): The name of the template to compile.
        kwargs (Dict[str, Any]): The context for rendering the template.
        renderer (Optional[Jinja2Renderer]): The Jinja2Renderer instance for rendering.
    """

    def __init__(self, template_name: str, **kwargs: Any) -> None:
        """
        Initialize the Compiler with template name and context.

        Args:
            template_name (str): The name of the template to compile.
            **kwargs (Dict[str, Any]): The context for rendering the template.
        """
        self.template_name = template_name
        self.kwargs = kwargs
        self.renderer: Optional[Jinja2Renderer] = None

    def __enter__(self) -> 'Compiler':
        """
        Enter the runtime context related to this object.

        Returns:
            Compiler: The instance of Compiler.
        """
        self.renderer = Jinja2Renderer.instance()
        return self

    def __exit__(self, exc_type: Optional[type], exc_val: Optional[Exception], exc_tb: Optional[Any]) -> None:
        """
        Exit the runtime context related to this object.

        Args:
            exc_type (Optional[type]): The exception type.
            exc_val (Optional[Exception]): The exception value.
            exc_tb (Optional[Any]): The traceback object.
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
            RuntimeError: If there is an error during template compilation.
        """
        if self.renderer:
            try:
                return self.renderer.render_templates(self.template_name, **self.kwargs)
            except Exception as e:
                raise RuntimeError("Error during template compilation") from e
        else:
            raise ValueError("Renderer is not initialized. Use 'with' statement to initialize it.")
