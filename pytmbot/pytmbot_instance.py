from __future__ import annotations

import ssl
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any, TypeAlias, Final, TypedDict

import requests
import telebot
import urllib3.exceptions
from telebot import TeleBot
from telebot.types import BotCommand

from pytmbot import exceptions
from pytmbot.globals import (
    settings,
    __version__,
    __repository__,
    bot_commands_settings,
    bot_description_settings,
    var_config,
)
from pytmbot.handlers.handler_manager import (
    handler_factory,
    inline_handler_factory,
    echo_handler_factory,
)
from pytmbot.logs import bot_logger
from pytmbot.middleware.access_control import AccessControl
from pytmbot.middleware.rate_limit import RateLimit
from pytmbot.models.handlers_model import HandlerManager
from pytmbot.plugins.plugin_manager import PluginManager
from pytmbot.utils.utilities import parse_cli_args, sanitize_exception

# Type Hints
MiddlewareType: TypeAlias = tuple[type, dict[str, Any]]
HandlerDict: TypeAlias = dict[str, list[HandlerManager]]
RegisterMethod: TypeAlias = Callable[..., Any]


class WebhookConfig(TypedDict):
    """Webhook configuration."""
    host: str
    port: int
    token: str


DEFAULT_BASE_SLEEP_TIME: Final[int] = 10
DEFAULT_MAX_SLEEP_TIME: Final[int] = 300
DEFAULT_MIDDLEWARES: Final[list[MiddlewareType]] = [
    (AccessControl, {}),
    (RateLimit, {"limit": 8, "period": timedelta(seconds=10)}),
]


class PyTMBot:
    """
    Manages the creation, configuration, and operation of a Telegram bot using the TeleBot library.

    This class implements a more robust error handling, type safety, and follows Python 3.12+ best practices.
    """

    def __init__(self) -> None:
        self.args = parse_cli_args()
        self.bot: TeleBot | None = None
        self.plugin_manager = PluginManager()

    def retrieve_bot_token(self) -> str:
        """Retrieves bot token based on operational mode."""
        bot_logger.debug(f"Current bot mode: {self.args.mode}")
        try:
            return (
                settings.bot_token.dev_bot_token[0].get_secret_value()
                if self.args.mode == "dev"
                else settings.bot_token.prod_token[0].get_secret_value()
            )
        except (FileNotFoundError, ValueError) as error:
            raise exceptions.PyTMBotError("Invalid or missing pytmbot.yaml file") from error

    def initialize_bot_core(self) -> TeleBot:
        """Creates and configures the core bot instance with all necessary setup."""
        bot_token = self.retrieve_bot_token()
        bot_logger.debug("Bot token retrieved successfully")

        self.bot = self.create_base_bot(bot_token)
        self.configure_bot_features()

        bot_logger.info(
            f"New instance started! PyTMBot {__version__} ({__repository__})"
        )
        return self.bot

    def create_base_bot(self, bot_token: str) -> TeleBot:
        """Creates the base bot instance with initial configuration."""
        self.bot = telebot.TeleBot(
            token=bot_token,
            threaded=True,
            use_class_middlewares=True,
            exception_handler=exceptions.TelebotCustomExceptionHandler(),
            skip_pending=True,
        )
        bot_logger.debug("Bot instance created successfully")
        return self.bot

    def configure_bot_features(self) -> None:
        """Configures all bot features and capabilities."""
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not properly initialized")

        self.setup_commands_and_description()
        self.setup_middleware_chain(DEFAULT_MIDDLEWARES)
        self.register_handler_chain()
        self.load_plugins()

    def setup_commands_and_description(self) -> None:
        """Sets up bot commands and description in Telegram."""
        try:
            commands = [
                BotCommand(command, desc)
                for command, desc in bot_commands_settings.bot_commands.items()
            ]
            self.bot.set_my_commands(commands)
            self.bot.set_my_description(bot_description_settings.bot_description)
            bot_logger.debug("Bot commands and description configured successfully")
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Failed to set bot commands/description: {error}")

    def register_handler_chain(self) -> None:
        """Registers complete chain of bot handlers."""
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not properly initialized")

        handlers_config = [
            (handler_factory, self.bot.register_message_handler),
            (inline_handler_factory, self.bot.register_callback_query_handler),
            (echo_handler_factory, self.bot.register_message_handler),
        ]

        for factory, register_method in handlers_config:
            self.register_handler_group(factory, register_method)

    def setup_middleware_chain(self, middlewares: list[MiddlewareType]) -> None:
        """Sets up chain of middleware processors."""
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not properly initialized")

        for middleware_class, kwargs in middlewares:
            try:
                middleware_instance = middleware_class(bot=self.bot, **kwargs)
                self.bot.setup_middleware(middleware_instance)
                bot_logger.debug(
                    f"Middleware setup successful: {middleware_class.__name__}"
                )
            except Exception as error:
                bot_logger.critical(f"Failed to set up middleware: {error}")
                raise

    def load_plugins(self) -> None:
        """Loads and initializes plugin system if enabled."""
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not properly initialized")

        if self.args.plugins != [""]:
            try:
                self.plugin_manager.register_plugins(self.args.plugins, self.bot)
            except Exception as err:
                bot_logger.exception(f"Failed to register plugins: {err}")

    @staticmethod
    def register_handler_group(
            handler_factory_func: Callable[[], HandlerDict],
            register_method: RegisterMethod,
    ) -> None:
        """Registers group of related handlers."""
        try:
            bot_logger.debug(
                f"Registering handlers using {register_method.__name__}..."
            )

            handlers_dict = handler_factory_func()
            handler_count = 0

            for handlers in handlers_dict.values():
                for handler in handlers:
                    register_method(handler.callback, **handler.kwargs, pass_bot=True)
                    handler_count += 1

            bot_logger.debug(f"Registered {handler_count} handlers")

        except Exception as err:
            bot_logger.exception(f"Handler registration failed: {err}")
            raise

    def launch_bot(self) -> None:
        """Launches bot instance in appropriate mode."""
        self.bot = self.initialize_bot_core()
        bot_logger.info("Starting bot...")

        try:
            self.bot.remove_webhook()
            if self.args.webhook == "True":
                self.start_webhook_server()
            else:
                self.start_polling_loop(self.bot)
        except Exception as error:
            bot_logger.error(f"Failed to start bot: {error}")
            raise

    def start_webhook_server(self) -> None:
        """Initializes and starts webhook server."""
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not properly initialized")

        try:
            from pytmbot.webhook import WebhookServer

            webhook_config = WebhookConfig(
                host=self.args.socket_host,
                port=settings.webhook_config.local_port[0],
                token=self.bot.token,
            )

            server = WebhookServer(self.bot, **webhook_config)

            import asyncio
            asyncio.run(server.start())

        except ImportError as err:
            bot_logger.exception(f"Failed to import FastAPI: {err}")
            raise
        except Exception as err:
            bot_logger.exception(f"Webhook startup failed: {err}")
            raise

    @staticmethod
    def start_polling_loop(bot_instance: TeleBot) -> None:
        """Runs main polling loop with exponential backoff."""
        current_sleep_time = DEFAULT_BASE_SLEEP_TIME

        while True:
            try:
                bot_instance.infinity_polling(
                    skip_pending=True,
                    timeout=var_config.bot_polling_timeout,
                    long_polling_timeout=var_config.bot_long_polling_timeout,
                )
                current_sleep_time = DEFAULT_BASE_SLEEP_TIME

            except ssl.SSLError as ssl_error:
                bot_logger.critical(
                    f"SSL error (security issue): {sanitize_exception(ssl_error)}"
                )
                raise

            except (
                    telebot.apihelper.ApiTelegramException,
                    urllib3.exceptions.ConnectionError,
                    urllib3.exceptions.ReadTimeoutError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ConnectTimeout,
                    urllib3.exceptions.MaxRetryError,
                    urllib3.exceptions.NameResolutionError,
                    telebot.apihelper.ApiException,
                    OSError,
            ) as error:
                bot_logger.error(
                    f"Connection error: {sanitize_exception(error)}. "
                    f"Retry in {current_sleep_time} seconds"
                )
                time.sleep(current_sleep_time)
                current_sleep_time = min(
                    current_sleep_time * 2,
                    DEFAULT_MAX_SLEEP_TIME
                )


__all__ = ["PyTMBot"]
