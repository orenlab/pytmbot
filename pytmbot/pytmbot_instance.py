import importlib
import importlib.util
import inspect
import re
import time
from typing import List, Dict, Callable, Type

import telebot
from telebot import TeleBot

from pytmbot import exceptions
from pytmbot.globals import (
    settings,
    __version__,
    __repository__,
    bot_commands_settings,
    bot_description_settings,
    var_config
)
from pytmbot.handlers.handler_manager import handler_factory, inline_handler_factory, echo_handler_factory
from pytmbot.logs import bot_logger
from pytmbot.middleware.access_control import AccessControl
from pytmbot.models.handlers_model import HandlerManager
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.utils.utilities import parse_cli_args


class PyTMBot:
    """
    Manages the creation, configuration, and operation of a Telegram bot using the TeleBot library.

    Attributes:
        args (Namespace):
            Command line arguments parsed with `parse_cli_args`.
        bot (TeleBot | None):
            Instance of the TeleBot, or None if not initialized.

    Methods:
        _get_bot_token() -> str:
            Retrieves the bot token based on the operational mode.

        __validate_plugin_name(plugin_name: str) -> bool:
            Validates the plugin name against a predefined pattern.

        __module_exists(plugin_name: str) -> bool:
            Checks if the module for the given plugin name exists.

        __import_module(plugin_name: str):
            Imports the module for the given plugin name.

        __find_plugin_classes(module) -> List[Type[PluginInterface]]:
            Finds and returns all valid plugin classes in the module.

        _register_plugin(plugin_name: str):
            Registers a single plugin by its name.

        _register_plugins(plugin_names: List[str]):
            Registers multiple plugins based on the provided list of plugin names.

        _create_bot_instance() -> TeleBot:
            Creates and configures the bot instance.

        _initialize_bot(bot_token: str) -> TeleBot:
            Initializes a TeleBot instance with the given token.

        _setup_bot_commands_and_description():
            Sets up the bot commands and description.

        _setup_middleware():
            Sets up the middleware for the bot.

        _register_handlers(handler_factory_func: Callable[[], Dict[str, List[HandlerManager]]],
                           register_method: Callable):
            Registers handlers using the provided registration method.

        _register_plugins_if_needed():
            Registers plugins if specified in the command line arguments.

        start_bot_instance():
            Starts the bot instance and enters an infinite polling loop.
    """

    def __init__(self):
        self.args = parse_cli_args()
        self.bot: TeleBot | None = None

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
            raise exceptions.PyTMBotError("pytmbot.yaml file is not valid or not found") from error

    @staticmethod
    def __validate_plugin_name(plugin_name: str) -> bool:
        """Check if the plugin name is valid based on predefined pattern."""
        valid_plugin_name_pattern = re.compile(r'^[a-z_]+$')
        return bool(valid_plugin_name_pattern.match(plugin_name))

    @staticmethod
    def __module_exists(plugin_name: str) -> bool:
        """Check if the module for the given plugin name exists."""
        module_path = f'pytmbot.plugins.{plugin_name}.plugin'
        return importlib.util.find_spec(module_path) is not None

    @staticmethod
    def __import_module(plugin_name: str):
        """Import the module for the given plugin name."""
        module_path = f'pytmbot.plugins.{plugin_name}.plugin'
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            bot_logger.error(f"ImportError: {e} - Module path: {module_path}")
            raise

    @staticmethod
    def __find_plugin_classes(module) -> List[Type[PluginInterface]]:
        """Find and return all valid plugin classes in the module."""
        plugin_classes = []
        for attribute_name in dir(module):
            attr = getattr(module, attribute_name)
            if inspect.isclass(attr) and issubclass(attr, PluginInterface) and attr is not PluginInterface:
                plugin_classes.append(attr)
        return plugin_classes

    def _register_plugin(self, plugin_name: str):
        """Register a single plugin."""
        if not self.__validate_plugin_name(plugin_name):
            bot_logger.error(f"Invalid plugin name: '{plugin_name}'. Skipping...")
            return

        if not self.__module_exists(plugin_name):
            bot_logger.error(f"Module '{plugin_name}' not found. Skipping...")
            return

        try:
            module = self.__import_module(plugin_name)

            if not hasattr(module, '__all__'):
                bot_logger.error(f"Module '{plugin_name}' does not have '__all__' attribute. Skipping...")
                return

            plugin_classes = self.__find_plugin_classes(module)

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
        Create and configure the bot instance.

        Returns:
            telebot.TeleBot: The created bot instance.
        """
        bot_token = self._get_bot_token()
        bot_logger.debug("Bot token setup successful")

        self.bot = self._initialize_bot(bot_token)
        self._setup_bot_commands_and_description()
        self._setup_middleware()

        # Register handlers
        self._register_handlers(handler_factory, self.bot.register_message_handler)
        self._register_handlers(inline_handler_factory, self.bot.register_callback_query_handler)

        self._register_plugins_if_needed()

        # Register echo handlers
        self._register_handlers(echo_handler_factory, self.bot.register_message_handler)

        bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")
        return self.bot

    def _initialize_bot(self, bot_token: str) -> TeleBot:
        self.bot = telebot.TeleBot(
            token=bot_token,
            threaded=True,
            use_class_middlewares=True,
            exception_handler=exceptions.TelebotCustomExceptionHandler(),
            skip_pending=True
        )
        bot_logger.debug("Bot instance created")
        return self.bot

    def _setup_bot_commands_and_description(self):
        try:
            commands = [telebot.types.BotCommand(command, desc)
                        for command, desc in bot_commands_settings.bot_commands.items()]
            self.bot.set_my_commands(commands)
            self.bot.set_my_description(bot_description_settings.bot_description)
            bot_logger.debug("Bot commands and description setup successful.")
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Error setting up bot commands and description: {error}")

    def _setup_middleware(self):
        try:
            self.bot.setup_middleware(AccessControl(bot=self.bot))
            bot_logger.debug(f"Middleware setup successful: {AccessControl.__name__}.")
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Failed to set up middleware: {error}")

    @staticmethod
    def _register_handlers(handler_factory_func: Callable[[], Dict[str, List[HandlerManager]]],
                           register_method: Callable):
        """
        Register handlers using the provided registration method.

        Args:
            handler_factory_func (Callable[[], Dict[str, List[Handler]]]): A function that returns a dictionary of handlers.
            register_method (Callable): The method used to register the handlers.
        """
        try:
            bot_logger.debug(f"Registering handlers using {register_method.__name__}...")
            handlers_dict = handler_factory_func()
            for handlers in handlers_dict.values():
                for handler in handlers:
                    register_method(handler.callback, **handler.kwargs, pass_bot=True)
            bot_logger.debug(f"Registered {sum(len(handlers) for handlers in handlers_dict.values())} handlers.")
        except Exception as err:
            raise exceptions.PyTMBotError(f"Failed to register handlers: {err}")

    def _register_plugins_if_needed(self):
        if self.args.plugins != ['']:
            try:
                self._register_plugins(self.args.plugins)
            except Exception as err:
                bot_logger.error(f"Failed to register plugins: {err}")

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
