#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from jinja2 import (
    FileSystemLoader,
    select_autoescape
)
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app.core import exceptions


class Jinja2Renderer:
    """
    Class to render Jinja2 templates.

    This class initializes the Jinja2 environment and sets the template folder and known templates.
    """

    def __init__(self):
        """
        Initialize the Jinja2 variables.

        This method initializes the Jinja2 variables, including the loader, template folder, and known templates.
        """
        # Initialize the Jinja2 loader
        self.loader = None

        # Set the template folder
        self.template_folder: str = "app/templates/"

        # Set the known templates
        self.known_templates: list[str] = [
            'containers.jinja2',
            'fs.jinja2',
            'index.jinja2',
            'load_average.jinja2',
            'memory.jinja2',
            'none.jinja2',
            'process.jinja2',
            'sensors.jinja2',
            'uptime.jinja2',
            'bot_update.jinja2',
            'swap.jinja2',
            'how_update.jinja2',
            'net_io.jinja2',
            'about_bot.jinja2'
        ]

    def _init_jinja2(self):
        """
        Initializes the Jinja2 environment.

        This function initializes the Jinja2 environment by creating a FileSystemLoader
        and setting up a SandboxedEnvironment. It sets the template folder and configures
        the autoscape for different template extensions.

        Returns:
            jinja2.Environment: The initialized Jinja2 environment.

        Raises:
            exceptions.PyTeleMonBotTemplateError: If there is an error loading the template.
        """
        try:
            # Create a FileSystemLoader with the template folder
            self.loader = FileSystemLoader(self.template_folder)

            # Set up a SandboxedEnvironment with the loader and autoescape configuration
            jinja2 = SandboxedEnvironment(
                loader=self.loader,
                autoescape=select_autoescape(
                    ['html', 'txt', 'jinja2'],
                    default_for_string=True
                )
            )

            # Return the initialized Jinja2 environment
            return jinja2
        except TemplateError:
            # Raise an exception if there is an error loading the template
            raise exceptions.PyTeleMonBotTemplateError("Error loading template")

    def render_templates(self, template_name: str, **context: dict) -> str:
        """
        Render a template using Jinja2.

        Args:
            template_name (str): The name of the template to render.
            **context (dict): The context variables to pass to the template.

        Returns:
            str: The rendered template.

        Raises:
            exceptions.PyTeleMonBotTemplateError: If the template name is unknown or if there is an error parsing the template.
        """
        try:
            # Check if the template name is known
            if template_name in self.known_templates:
                # Initialize Jinja2 environment
                jinja = self._init_jinja2()

                # Get the template
                template = jinja.get_template(template_name)

                # Render the template with the context variables
                rendered_template = template.render(**context)

                # Return the rendered template
                return rendered_template
            else:
                # Raise an exception if the template name is unknown
                raise exceptions.PyTeleMonBotTemplateError("Unknown template name")
        except TemplateError:
            # Raise an exception if there is an error parsing the template
            raise exceptions.PyTeleMonBotTemplateError("Error parsing template")
