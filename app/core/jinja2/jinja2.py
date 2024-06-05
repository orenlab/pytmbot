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
    def __init__(self):
        """
        Initialize the Jinja2 variables.

        This method initializes the Jinja2 variables, including the loader, template folder, and known templates.
        """
        self.loader = None
        self.template_folder = "app/templates/"
        self.known_templates = [
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

    def __initialize_jinja_environment(self):
        """
        Initializes the Jinja2 environment.

        This function creates a FileSystemLoader for the template folder and sets up a
        SandboxedEnvironment with the loader and appropriate autoescape configuration.

        Returns:
            jinja2.Environment: The initialized Jinja2 environment.

        Raises:
            exceptions.TemplateError: If there is an error loading the template.
        """
        try:
            # Create a FileSystemLoader for the template folder
            loader = FileSystemLoader(self.template_folder)

            # Select appropriate autoescape configuration for HTML, text, and Jinja2 templates
            autoescape_config = select_autoescape(
                ['html', 'txt', 'jinja2'],
                default_for_string=True
            )

            # Set up a SandboxedEnvironment with the loader and autoescape configuration
            environment = SandboxedEnvironment(loader=loader, autoescape=autoescape_config)

            # Return the initialized Jinja2 environment
            return environment

        # If there is an error loading the template, raise a TemplateError with a descriptive message
        except TemplateError as error:
            raise TemplateError("Error loading template") from error

    def render_templates(self, template_name: str, **context: dict) -> str:
        """
        Render a template using Jinja2.

        Args:
            template_name (str): The name of the template to render.
            **context (dict): The context variables to pass to the template.

        Returns:
            str: The rendered template.

        Raises:
            exceptions.PyTeleMonBotTemplateError: If the template name is unknown or if there is an error parsing
            the template.
        """
        # Check if the template name is known
        if template_name not in self.known_templates:
            # Raise an exception if the template name is unknown
            raise exceptions.PyTeleMonBotTemplateError("Unknown template name")

        try:
            # Initialize the Jinja2 environment
            jinja_env = self.__initialize_jinja_environment()

            # Get the template by name
            template = jinja_env.get_template(template_name)

            # Render the template with the provided context
            rendered_template = template.render(**context)

            # Return the rendered template
            return rendered_template
        except TemplateError:
            # Raise an exception if there is an error parsing the template
            raise exceptions.PyTeleMonBotTemplateError("Error parsing template")
