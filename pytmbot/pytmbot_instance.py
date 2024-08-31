#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import importlib
import importlib.util
import inspect
import re
import time
from typing import List

import telebot
from telebot import TeleBot

from pytmbot import exceptions
from pytmbot.globals import (
    settings,
    __version__,
    __repository__,
    bot_command_settings,
    bot_description_settings,
    var_config
)
from pytmbot.handlers.handler_manager import handler_factory, inline_handler_factory
from pytmbot.logs import bot_logger
from pytmbot.middleware.access_control import AccessControl
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.utils.utilities import parse_cli_args


class PyTMBot:
    def __init__(self):
        self.args = parse_cli_args()
        self.bot = None

    def _get_bot_token(self) -> str:
        """
        Get the bot token based on the bot mode from the command line arguments.
        Returns:
            str: The bot token.
        """
        bot_logger.debug(f"Operational bot mode: {self.args.mode}")

        try:
            return (
                settings.bot_token.dev_bot_token[0].get_secret_value()
                if self.args.mode == "dev"
                else settings.bot_token.prod_token[0].get_secret_value()
            )
        except (FileNotFoundError, ValueError) as error:
            raise exceptions.PyTMBotError(".pytmbotenv file is not valid or not found") from error

    @staticmethod
    def _validate_plugin_name(plugin_name: str) -> bool:
        """Check if the plugin name is valid based on predefined pattern."""
        valid_plugin_name_pattern = re.compile(r'^[a-z_]+$')
        return bool(valid_plugin_name_pattern.match(plugin_name))

    @staticmethod
    def _module_exists(plugin_name: str) -> bool:
        """Check if the module for the given plugin name exists."""
        module_spec = importlib.util.find_spec(f'pytmbot.plugins.{plugin_name}.plugin')
        return module_spec is not None

    @staticmethod
    def _import_module(plugin_name: str):
        """Import the module for the given plugin name."""
        return importlib.import_module(f'pytmbot.plugins.{plugin_name}.plugin')

    @staticmethod
    def _find_plugin_classes(module) -> List[type]:
        """Find and return all valid plugin classes in the module."""
        return [
            getattr(module, attribute_name)
            for attribute_name in dir(module)
            if inspect.isclass(getattr(module, attribute_name)) and
               issubclass(getattr(module, attribute_name), PluginInterface) and
               getattr(module, attribute_name) is not PluginInterface
        ]

    def _register_plugin(self, plugin_name: str):
        """Register a single plugin."""
        if not self._validate_plugin_name(plugin_name):
            bot_logger.error(f"Invalid plugin name: '{plugin_name}'. Skipping...")
            return

        if not self._module_exists(plugin_name):
            bot_logger.error(f"Module '{plugin_name}' not found. Skipping...")
            return

        try:
            module = self._import_module(plugin_name)

            if not hasattr(module, '__all__'):
                bot_logger.error(f"Module '{plugin_name}' does not have '__all__' attribute. Skipping...")
                return

            plugin_classes = self._find_plugin_classes(module)

            if not plugin_classes:
                bot_logger.error(f"No valid plugin class found in module '{plugin_name}'. Skipping...")
                return

            plugin_instance = plugin_classes[0](self.bot)
            plugin_instance.register()
            bot_logger.info(f"Plugin '{plugin_name}' registered successfully.")

        except ValueError as ve:
            bot_logger.error(f"Plugin registration error for '{plugin_name}': {ve}")
        except Exception as error:
            bot_logger.error(f"Unexpected error loading plugin '{plugin_name}': {error}")

    def _register_plugins(self, plugin_names: List[str]):
        """Register multiple plugins based on the provided list of plugin names."""
        for plugin_name in plugin_names:
            self._register_plugin(plugin_name)

    def _create_bot_instance(self) -> TeleBot:
        """
        Create the bot instance.
        Returns:
            telebot.TeleBot: The created bot instance.
        """
        bot_token = self._get_bot_token()
        bot_logger.debug("Bot token setup successful")

        self.bot = telebot.TeleBot(
            token=bot_token,
            threaded=True,
            use_class_middlewares=True,
            exception_handler=exceptions.TelebotCustomExceptionHandler(),
            skip_pending=True
        )
        bot_logger.debug("Bot instance created")

        # Set up bot commands and description
        try:
            commands = [telebot.types.BotCommand(command, desc) for command, desc in
                        bot_command_settings.bot_commands.items()]
            self.bot.set_my_commands(commands)
            self.bot.set_my_description(bot_description_settings.bot_description)
            bot_logger.debug("Bot commands and description setup successful.")
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Error setting up bot commands and description: {error}")

        # Set up middleware
        try:
            self.bot.setup_middleware(AccessControl(bot=self.bot))
            bot_logger.debug(f"Middleware setup successful: {AccessControl.__name__}.")
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Failed to set up middleware: {error}")

        # Register message and inline handlers
        try:
            bot_logger.debug("Registering message handlers...")
            for handlers in handler_factory().values():
                for handler in handlers:
                    self.bot.register_message_handler(handler.callback, **handler.kwargs, pass_bot=True)
            bot_logger.debug(f"Registered {len(handler_factory())} message handlers.")

            bot_logger.debug("Registering inline message handlers...")
            for handlers in inline_handler_factory().values():
                for handler in handlers:
                    self.bot.register_callback_query_handler(handler.callback, **handler.kwargs, pass_bot=True)
            bot_logger.debug(f"Registered {len(inline_handler_factory())} inline message handlers.")
        except Exception as err:
            raise exceptions.PyTMBotError(f"Failed to register handlers: {err}")

        # Register plugins
        if self.args.plugins != ['']:
            try:
                self._register_plugins(self.args.plugins)
            except Exception as err:
                bot_logger.error(f"Failed to register plugins: {err}")

        bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")
        return self.bot

    def start_bot_instance(self):
        """
        Start the bot instance.
        """
        bot_instance = self._create_bot_instance()
        bot_logger.info("Starting polling............")

        while True:
            try:
                bot_instance.infinity_polling(
                    skip_pending=True,
                    timeout=var_config.bot_polling_timeout,
                    long_polling_timeout=var_config.bot_long_polling_timeout
                )
            except telebot.apihelper.ApiTelegramException as error:
                bot_logger.error(f"Polling failed: {error}")
                time.sleep(10)
            except Exception as error:
                bot_logger.error(f"Unexpected error: {error}")
                time.sleep(10)


__all__ = ['PyTMBot']
