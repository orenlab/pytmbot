#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from typing import Optional, Dict, Any, List

import jinja2
from jinja2 import (
    FileSystemLoader,
    select_autoescape
)
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app import config
from app.core import exceptions
from app.core.logs import bot_logger


class Jinja2Renderer:
    """
    Class for rendering templates using Jinja2.

    Attributes:
        loader (Optional[jinja2.BaseLoader]): The loader for Jinja2 templates.
        template_cache (Dict[str, jinja2.Template]): Cache for compiled Jinja2 templates.
        template_folder (str): The path to the folder containing Jinja2 templates.
        known_templates (List[str]): List of known templates.
    """

    def __init__(self) -> None:
        """
        Initialize the Jinja2 variables.

        This method initializes the Jinja2 variables for the Jinja2Renderer class.
        It sets the loader to None, initializes the template_cache as an empty dictionary,
        sets the template folder path, and defines the list of known templates.

        Args:
            self (Jinja2Renderer): The Jinja2Renderer instance.

        Returns:
            None
        """
        # Initialize loader as None
        self.loader: Optional[jinja2.BaseLoader] = None

        # Initialize template_cache as an empty dictionary
        self.template_cache: Dict[str, jinja2.Template] = {}

        # Set the template folder path
        self.template_folder: str = "app/templates/"

        # Define the list of known templates
        self.known_templates: List[str] = config.known_templates

    def __initialize_jinja_environment(self) -> jinja2.Environment:
        """
        Initializes the Jinja2 environment.

        Args:
            self (Jinja2Renderer): The Jinja2Renderer instance.

        Returns:
            jinja2.Environment: The initialized Jinja2 environment.

        Raises:
            TemplateError: If there is an error loading the template.
        """
        try:
            # Create a FileSystemLoader for the template folder
            loader: FileSystemLoader = FileSystemLoader(self.template_folder)

            # Select appropriate autoescape configuration for HTML, text, and Jinja2 templates
            autoescape_config = select_autoescape(
                ['html', 'txt', 'jinja2'],
                default_for_string=True
            )

            # Set up a SandboxedEnvironment with the loader and autoescape configuration
            environment: SandboxedEnvironment = SandboxedEnvironment(
                loader=loader,
                autoescape=autoescape_config
            )

            # Return the initialized Jinja2 environment
            return environment

        # If there is an error loading the template, raise a TemplateError with a descriptive message
        except TemplateError as error:
            raise TemplateError("Error loading template") from error

    def render_templates(self, template_name: str, *, emojis: Optional[Dict[str, str]] = None,
                         **context: Dict[str, Any]) -> str:
        """
        Render a template using Jinja2.

        Args:
            template_name (str): The name of the template to render.
            emojis (Optional[Dict[str, str]]): A dictionary of emojis to be used in the template.
            **context (Dict[str, Any]): The context variables to pass to the template.

        Returns:
            str: The rendered template.

        Raises:
            exceptions.PyTeleMonBotTemplateError: If the template name is unknown or if there is an error parsing
            the template.
        """
        # Check if the template name is known
        if template_name not in self.known_templates:
            raise exceptions.PyTeleMonBotTemplateError(f"Unknown template name: {template_name}")

        try:
            # Initialize Jinja2 environment
            bot_logger.debug("Initializing Jinja2 environment")
            jinja_env = self.__initialize_jinja_environment()

            # Load the template either from cache or the file system
            bot_logger.debug(f"Loading template: {template_name}")
            template = self.template_cache.get(template_name)
            if template is None:
                bot_logger.debug("Template not in cache, loading from file system")
                template = jinja_env.get_template(template_name)
                self.template_cache[template_name] = template

            # Render the template with provided context and emojis
            bot_logger.debug(f"Rendering template: {template_name}")
            rendered_template = template.render(emojis=emojis, **context)

            return rendered_template
        except TemplateError as e:
            raise exceptions.PyTeleMonBotTemplateError("Error parsing template") from e
