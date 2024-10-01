import os
import weakref
from typing import Optional, Dict, Any

import jinja2
from jinja2 import select_autoescape
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from pytmbot import exceptions
from pytmbot.globals import var_config
from pytmbot.logs import bot_logger
from pytmbot.parsers.filters import format_timestamp


class Jinja2Renderer:
    """Class for rendering templates using Jinja2."""

    _instance: Optional["Jinja2Renderer"] = None
    _jinja_env: Optional[jinja2.Environment] = None

    def __init__(self):
        self._template_cache = weakref.WeakValueDictionary()
        bot_logger.debug("Jinja2Renderer instance initialized.")

    @classmethod
    def instance(cls) -> "Jinja2Renderer":
        """
        Returns the singleton instance of the Jinja2Renderer class.

        Returns:
            Jinja2Renderer: The singleton instance.
        """
        if cls._instance is None:
            bot_logger.debug("Creating a new Jinja2Renderer instance.")
            cls._instance = cls._initialize_instance()
        else:
            bot_logger.debug("Reusing existing Jinja2Renderer instance.")
        return cls._instance

    @classmethod
    def _initialize_instance(cls) -> "Jinja2Renderer":
        """
        Initializes the Jinja2Renderer instance.

        Returns:
            Jinja2Renderer: The initialized instance.
        """
        bot_logger.debug("Initializing Jinja2 environment.")
        cls._jinja_env = cls.__initialize_jinja_environment()
        return cls()

    @staticmethod
    def __initialize_jinja_environment() -> jinja2.Environment:
        """
        Initializes the Jinja2 environment.

        Returns:
            jinja2.Environment: The initialized Jinja2 environment.
        """
        template_path = var_config.template_path
        bot_logger.debug(
            f"Setting up Jinja2 environment with template path: {template_path}"
        )

        env = SandboxedEnvironment(
            loader=jinja2.FileSystemLoader(template_path),
            autoescape=select_autoescape(
                ["html", "txt", "jinja2"], default_for_string=True
            ),
        )

        env.filters["format_timestamp"] = format_timestamp

        return env

    def render_templates(
            self,
            template_name: str,
            emojis: Optional[Dict[str, str]] = None,
            **kwargs: Dict[str, Any],
    ) -> str:
        """
        Render a Jinja2 template with the given name and context.

        Args:
            template_name (str): The name of the template to render.
            emojis (Optional[Dict[str, str]]): Optional dictionary of emojis to pass to the template.
            **kwargs: Additional context for the template.

        Returns:
            str: The rendered template.

        Raises:
            exceptions.PyTMBotErrorTemplateError: If there is an error parsing the template.
        """
        try:
            bot_logger.debug(
                f"Rendering template: {template_name} with context: {kwargs.keys()}"
            )
            template_subdir = self.__get_subdirectory(template_name)
            rendered_template = self.__get_template(
                template_name, template_subdir
            ).render(emojis=emojis, **kwargs)
            bot_logger.debug(f"Template {template_name} rendered successfully.")
            return rendered_template
        except TemplateError as error:
            bot_logger.error(f"Error parsing template: {template_name}, Error: {error}")
            raise exceptions.PyTMBotErrorTemplateError(
                f"Error parsing template: {template_name}"
            ) from error

    def __get_template(
            self, template_name: str, template_subdir: str
    ) -> jinja2.Template:
        """
        Get a Jinja2 template by its name.

        Args:
            template_name (str): The name of the template to retrieve.
            template_subdir (str): The subdirectory containing the template.

        Returns:
            jinja2.Template: The requested template.

        Raises:
            exceptions.PyTMBotErrorTemplateError: If there is an error loading the template.
        """
        cache_key = (template_name, template_subdir)
        template = self._template_cache.get(cache_key)

        if template is None:
            bot_logger.debug(
                f"Template {template_name} not found in cache, loading from folder {template_subdir}..."
            )
            self.jinja_env = self._jinja_env or self.__initialize_jinja_environment()

            template_path = os.path.join(template_subdir, template_name)
            bot_logger.debug(f"Loading template from path: {template_path}")

            try:
                template = self.jinja_env.get_template(template_path)
                self._template_cache[cache_key] = template
                bot_logger.debug(f"Template {template_name} loaded successfully!")
            except TemplateError as error:
                bot_logger.error(f"Error loading template {template_name}: {error}")
                raise exceptions.PyTMBotErrorTemplateError(
                    f"Error loading template: {template_name}"
                ) from error

        return template

    @staticmethod
    def __get_subdirectory(template_name: str) -> str:
        """
        Get the subdirectory for the given template name.

        Args:
            template_name (str): The name of the template.

        Returns:
            str: The subdirectory for the template.

        Raises:
            exceptions.PyTMBotErrorTemplateError: If the template name is unknown.
        """
        subdirectories = {
            "a": "auth_templates",
            "b": "base_templates",
            "d": "docker_templates",
        }

        if template_name.startswith("plugin_"):
            plugin_name = template_name.split("_")[1]
            plugin_dir = f"plugins_template/{plugin_name}"
            bot_logger.debug(f"Plugin template detected, subdirectory: {plugin_dir}")
            return plugin_dir

        subdirectory = subdirectories.get(template_name[0])
        if subdirectory is None:
            bot_logger.error(
                f"Unknown template: {template_name}, can't find subdirectory."
            )
            raise exceptions.PyTMBotErrorTemplateError(
                f"Unknown template: {template_name}, can't find subdirectory"
            )

        bot_logger.debug(
            f"Using subdirectory {subdirectory} for template {template_name}"
        )
        return subdirectory
