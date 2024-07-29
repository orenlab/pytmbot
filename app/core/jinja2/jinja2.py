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

        # Define the list of known templates
        self.known_templates: List[str] = config.known_templates

        # Initialize template_cache as an empty dictionary
        self.jinja_env = None

        # Set the template folder path
        self.template_folder: str = "app/templates/"

        # Initialize template_cache as an empty dictionary
        self.template_cache: Dict[str, jinja2.Template] = {}

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
            bot_logger.debug("Initializing Jinja2 environment...")
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

            bot_logger.debug("Jinja2 environment initialized successfully!")

            # Return the initialized Jinja2 environment
            return environment

        # If there is an error loading the template, raise a TemplateError with a descriptive message
        except TemplateError as error:
            raise TemplateError("Error loading template from template folder:") from error

    def render_templates(self, template_name: str, emojis: Optional[Dict[str, str]] = None,
                         **kwargs: Dict[str, Any]) -> str:
        """
        Render a Jinja2 template with the given name and context.

        Args:
            template_name (str): The name of the template to render.
            emojis (Optional[Dict[str, str]]): A dictionary of emojis to use in the template.
            **kwargs: Additional context to pass to the template.

        Returns:
            str: The rendered template.

        Raises:
            exceptions.PyTeleMonBotTemplateError: If the template name is unknown or if there is an error parsing the
            template.
        """
        # Check if the template name is known
        if template_name not in self.known_templates:
            raise exceptions.PyTeleMonBotTemplateError(f"Unknown template: {template_name}")

        try:
            # Get the template and render it with the given context
            return self.__get_template(template_name).render(emojis=emojis, **kwargs)
        except TemplateError as error:
            # If there is an error parsing the template, raise an exception with a descriptive message
            raise exceptions.PyTeleMonBotTemplateError(f"Error parsing template: {template_name}") from error

    def __get_template(self, template_name: str) -> jinja2.Template:
        """
        Get a Jinja2 template by its name. If the template is not found in the cache,
        it will be loaded from the folder and added to the cache.

        Args:
            template_name (str): The name of the template.

        Returns:
            jinja2.Template: The Jinja2 template object.

        Raises:
            TemplateError: If there is an error loading the template.

        """
        try:
            # Log the template name being loaded
            bot_logger.debug(f"Loading template: {template_name}")

            # Check if the template is already in the cache
            template = self.template_cache.get(template_name)

            if template is None:
                # Log that the template is not in the cache
                bot_logger.debug(f"Template {template_name} not found in cache, loading from folder...")

                # Initialize the Jinja2 environment if it hasn't been initialized yet
                self.jinja_env = self.jinja_env or self.__initialize_jinja_environment()

                # Load the template from the folder and add it to the cache
                template = self.jinja_env.get_template(template_name)
                self.template_cache[template_name] = template

                # Log that the template was loaded successfully
                bot_logger.debug(f"Template {template_name} loaded from folder successfully!")

            return template

        except TemplateError as error:
            # Raise an exception with a descriptive message if there is an error loading the template
            raise TemplateError(f"Error loading template: {template_name}") from error
