from typing import Any, Dict, Optional

from pytmbot.parsers._parser import Jinja2Renderer


class Compiler:
    """
    A class for compiling Jinja2 templates using a context manager.

    This class allows for the rendering of Jinja2 templates with a specified context.
    It uses a context manager to handle the initialization and cleanup of the Jinja2 renderer.

    Attributes:
        template_name (str): The name of the Jinja2 template to compile.
        kwargs (Dict[str, Any]): The context variables for rendering the template.
        renderer (Optional[Jinja2Renderer]): The Jinja2Renderer instance used for rendering, initialized when entering the context.
    """

    def __init__(self, template_name: str, **kwargs: Any) -> None:
        """
        Initialize the Compiler with a template name and context.

        Args:
            template_name (str): The name of the Jinja2 template to compile.
            **kwargs (Any): The context variables to pass to the template for rendering.
        """
        self.template_name = template_name
        self.kwargs = kwargs
        self.renderer: Optional[Jinja2Renderer] = None

    def __enter__(self) -> "Compiler":
        """
        Enter the runtime context related to this object.

        Initializes the Jinja2Renderer instance for rendering the template.

        Returns:
            Compiler: The current instance of Compiler.
        """
        self.renderer = Jinja2Renderer.instance()
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[Exception],
        exc_tb: Optional[Any],
    ) -> None:
        """
        Exit the runtime context related to this object.

        Cleans up the Jinja2Renderer instance. No specific cleanup action is required for the renderer.

        Args:
            exc_type (Optional[type]): The exception type, if an exception was raised.
            exc_val (Optional[Exception]): The exception value, if an exception was raised.
            exc_tb (Optional[Any]): The traceback object, if an exception was raised.
        """
        # No specific cleanup needed for renderer
        self.renderer = None

    def compile(self) -> str:
        """
        Compile and render the template with the provided context.

        Returns:
            str: The rendered template as a string.

        Raises:
            ValueError: If the renderer is not initialized (i.e., if 'with' statement was not used).
            RuntimeError: If an error occurs during template rendering.
        """
        if self.renderer:
            try:
                return self.renderer.render_templates(self.template_name, **self.kwargs)
            except Exception as e:
                raise RuntimeError("Error during template compilation") from e
        else:
            raise ValueError(
                "Renderer is not initialized. Ensure the 'with' statement is used to initialize it."
            )
