#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import os
from typing import Optional, Dict, Any

import jinja2
from jinja2 import (
    select_autoescape
)
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from app import config
from app.core import exceptions
from app.core.logs import bot_logger


class Jinja2Renderer:
    """Class for rendering templates using Jinja2."""

    _instance: Optional['Jinja2Renderer'] = None
    _jinja_env: Optional[jinja2.Environment] = None
    _template_cache: Dict[str, jinja2.Template] = {}

    @classmethod
    def instance(cls) -> 'Jinja2Renderer':
        """
        Returns the singleton instance of the Jinja2Renderer class.

        This method ensures that only one instance of the Jinja2Renderer class is created.
        It uses the Singleton design pattern to achieve this.

        Returns:
            Jinja2Renderer: The singleton instance of the Jinja2Renderer class.
        """
        # Check if the instance already exists
        if not cls._instance:
            # If not, initialize it
            cls._instance = cls._initialize_instance()
        # Return the instance
        return cls._instance

    @classmethod
    def _initialize_instance(cls) -> 'Jinja2Renderer':
        """
        Initializes the Jinja2Renderer instance.

        This method sets up the Jinja2 environment and creates an empty template cache.
        It then returns a new instance of the Jinja2Renderer class.

        Returns:
            Jinja2Renderer: The initialized Jinja2Renderer instance.
        """
        # Set up the Jinja2 environment
        cls._jinja_env = cls.__initialize_jinja_environment()

        # Create an empty template cache
        cls._template_cache = {}

        # Return a new instance of the Jinja2Renderer class
        return cls()

    @staticmethod
    def __initialize_jinja_environment() -> jinja2.Environment:
        """
        Initializes the Jinja2 environment.

        This method creates a SandboxedEnvironment instance with a FileSystemLoader
        that loads templates from the 'app/templates/' directory. The environment
        also uses autoescape for HTML, TXT, and Jinja2 templates.

        Returns:
            jinja2.Environment: The initialized Jinja2 environment.
        """
        # Create a SandboxedEnvironment instance to ensure security and isolation
        # when rendering templates.
        return SandboxedEnvironment(
            # Use a FileSystemLoader to load templates from the 'app/templates/' directory.
            loader=jinja2.FileSystemLoader("app/templates/"),
            # Enable autoescape for HTML, TXT, and Jinja2 templates to prevent XSS attacks.
            autoescape=select_autoescape(['html', 'txt', 'jinja2'], default_for_string=True)
        )

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
        try:
            # Check if the template name is known
            if template_name not in config.known_templates:
                raise exceptions.PyTeleMonBotTemplateError(f"Unknown template: {template_name}")

            # Get the template and render it with the given context
            template_subdir = self.__get_subdirectory(template_name)
            return self.__get_template(template_name, template_subdir).render(emojis=emojis, **kwargs)
        except TemplateError as error:
            # If there is an error parsing the template, raise an exception with a descriptive message
            raise exceptions.PyTeleMonBotTemplateError(f"Error parsing template: {template_name}") from error

    def __get_template(self, template_name: str, template_subdir: str) -> jinja2.Template:
        """
        Get a Jinja2 template by its name. If the template is not found in the cache,
        it will be loaded from the folder and added to the cache.

        Args:
            template_name (str): The name of the template to render.
            template_subdir (str): The subdirectory where the template is located.

        Returns:
            jinja2.Template: The loaded Jinja2 template.

        Raises:
            exceptions.PyTeleMonBotTemplateError: If the template name is unknown or if there is an error parsing the template.
        """
        try:
            # Log the template name being loaded
            bot_logger.debug(
                f"Loading template: {template_name} from subdirectory: {template_subdir}...")

            # Check if the template is already in the cache
            template = self._template_cache.get(template_name)

            if template is None:
                # Log that the template is not in the cache
                bot_logger.debug(f"Template {template_name} not found in cache, loading from folder...")

                # Initialize the Jinja2 environment if it hasn't been initialized yet
                self.jinja_env = self._jinja_env or self.__initialize_jinja_environment()

                template_path = os.path.join(template_subdir, template_name)

                bot_logger.debug(f"Template path: {template_path}")

                # Load the template from the folder and add it to the cache
                template = self.jinja_env.get_template(template_path)
                self._template_cache[template_name] = template

                # Log that the template was loaded successfully
                bot_logger.debug(f"Template {template_name} loaded from folder successfully!")

            return template

        except TemplateError as error:
            # If there is an error parsing the template, raise an exception with a descriptive message
            raise exceptions.PyTeleMonBotTemplateError(f"Error parsing template: {template_name}") from error

    @staticmethod
    def __get_subdirectory(template_name):
        """
        Get the subdirectory for the given template name.

        Args:
            template_name (str): The name of the template.

        Returns:
            str: The subdirectory corresponding to the template name.

        Raises:
            exceptions.PyTeleMonBotTemplateError: If the template name is unknown.
        """
        # Define the subdirectories mapping
        subdirectories = {
            'a': 'auth_templates',
            'b': 'base_templates',
            'd': 'docker_templates'
        }

        # Get the subdirectory for the template name
        subdirectory = subdirectories.get(template_name[0])

        # Raise an exception if the subdirectory is None
        if subdirectory is None:
            raise exceptions.PyTeleMonBotTemplateError(f"Unknown template: {template_name}, cant find subdirectory")

        return subdirectory
