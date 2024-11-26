# /venv/bin/python3
import ssl
import time
from datetime import timedelta
from typing import List, Dict, Callable

import requests
import telebot
import urllib3.exceptions
from telebot import TeleBot

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

urllib3.disable_warnings()


class PyTMBot:
    """
    Manages the creation, configuration, and operation of a Telegram bot using the TeleBot library.

    Attributes:
        args (Namespace): Command line arguments parsed using `parse_cli_args`.
        bot (TeleBot | None): Instance of TeleBot, or None if not initialized.
        plugin_manager (PluginManager): Manager for plugin discovery and registration.
    """

    def __init__(self):
        self.args = parse_cli_args()
        self.bot: TeleBot | None = None
        self.plugin_manager = PluginManager()

    def _get_bot_token(self) -> str:
        """
        Retrieves the bot token based on the operational mode (dev/prod).

        Returns:
            str: The bot token.

        Raises:
            PyTMBotError: If the `pytmbot.yaml` file is missing or invalid.
        """
        bot_logger.debug(f"Current bot mode: {self.args.mode}")
        try:
            return (
                settings.bot_token.dev_bot_token[0].get_secret_value()
                if self.args.mode == "dev"
                else settings.bot_token.prod_token[0].get_secret_value()
            )
        except (FileNotFoundError, ValueError) as error:
            raise exceptions.PyTMBotError(
                "pytmbot.yaml file is not valid or not found"
            ) from error

    def _register_plugins_if_needed(self):
        """
        Registers plugins if specified in the command line arguments.
        """
        if self.args.plugins != [""]:
            try:
                self.plugin_manager.register_plugins(self.args.plugins, self.bot)
            except Exception as err:
                bot_logger.exception(f"Failed to register plugins: {err}")

    def _create_bot_instance(self) -> TeleBot:
        """
        Creates and configures the bot instance.

        Returns:
            telebot.TeleBot: The initialized bot instance.
        """
        bot_token = self._get_bot_token()
        bot_logger.debug("Bot token successfully retrieved")

        self.bot = self._initialize_bot(bot_token)
        self._setup_bot_commands_and_description()

        # Set up middlewares
        self._setup_middlewares(
            [
                (AccessControl, {}),
                (RateLimit, {"limit": 8, "period": timedelta(seconds=10)}),
            ]
        )

        # Register handlers
        self._register_handlers(handler_factory, self.bot.register_message_handler)
        self._register_handlers(
            inline_handler_factory, self.bot.register_callback_query_handler
        )

        # Register plugins
        self._register_plugins_if_needed()

        # Register echo handlers
        self._register_handlers(echo_handler_factory, self.bot.register_message_handler)

        bot_logger.info(
            f"New instance started! PyTMBot {__version__} ({__repository__})"
        )
        return self.bot

    def _initialize_bot(self, bot_token: str) -> TeleBot:
        """
        Initializes the bot instance with the provided token.

        Args:
            bot_token (str): The token used to authenticate the bot.

        Returns:
            telebot.TeleBot: The created TeleBot instance.
        """
        self.bot = telebot.TeleBot(
            token=bot_token,
            threaded=True,
            use_class_middlewares=True,
            exception_handler=exceptions.TelebotCustomExceptionHandler(),
            skip_pending=True,
        )
        bot_logger.debug("Bot instance created successfully")
        return self.bot

    def _setup_bot_commands_and_description(self):
        """
        Configures the bot's commands and description from the settings.
        """
        try:
            commands = [
                telebot.types.BotCommand(command, desc)
                for command, desc in bot_commands_settings.bot_commands.items()
            ]
            self.bot.set_my_commands(commands)
            self.bot.set_my_description(bot_description_settings.bot_description)
            bot_logger.debug("Bot commands and description set successfully.")
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Failed to set bot commands and description: {error}")

    def _setup_middlewares(self, middlewares: list[tuple[type, dict]]):
        """
        Sets up multiple middlewares for the bot.

        Args:
            middlewares (list[tuple[type, dict]]): A list of tuples, where each tuple contains
                a middleware class and a dictionary of arguments to be passed to its constructor.

        Example:
            To set up AccessControl and RateLimit middlewares:
                self._setup_middlewares([
                    (AccessControl, {}),
                    (RateLimit, {'limit': 8, 'period': timedelta(seconds=10)})
                ])
        """
        for middleware_class, kwargs in middlewares:
            try:
                self._setup_middleware(middleware_class, **kwargs)
            except telebot.apihelper.ApiTelegramException as error:
                bot_logger.error(
                    f"Failed to set up middleware {middleware_class.__name__}: {error}"
                )

    def _setup_middleware(self, middleware_class: type, *args, **kwargs):
        """
        Sets up a specified middleware for the bot.

        Args:
            middleware_class (type): The middleware class to be set up.
            *args: Positional arguments to be passed to the middleware constructor.
            **kwargs: Keyword arguments to be passed to the middleware constructor.

        Raises:
            telebot.apihelper.ApiTelegramException: If there is an error while setting up the middleware.

        Example:
            To set up AccessControl middleware:
                self._setup_middleware(AccessControl)

            To set up RateLimit middleware with a limit of 5 requests per 10 seconds:
                self._setup_middleware(RateLimit, limit=5, period=timedelta(seconds=10))
        """
        try:
            middleware_instance = middleware_class(bot=self.bot, *args, **kwargs)
            self.bot.setup_middleware(middleware_instance)
            bot_logger.debug(
                f"Middleware setup successful: {middleware_class.__name__}."
            )
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.critical(f"Failed to set up middleware: {error}")
            exit(1)

    @staticmethod
    def _register_handlers(
        handler_factory_func: Callable[[], Dict[str, List[HandlerManager]]],
        register_method: Callable,
    ):
        """
        Registers bot handlers using the provided factory function and registration method.

        Args:
            handler_factory_func (Callable[[], Dict[str, List[HandlerManager]]]):
                A factory function that returns a dictionary of handlers.
            register_method (Callable): The method used to register the handlers.
        """
        try:
            bot_logger.debug(
                f"Registering handlers using {register_method.__name__}..."
            )
            handlers_dict = handler_factory_func()
            for handlers in handlers_dict.values():
                for handler in handlers:
                    register_method(handler.callback, **handler.kwargs, pass_bot=True)
            bot_logger.debug(
                f"Registered {sum(len(handlers) for handlers in handlers_dict.values())} handlers."
            )
        except telebot.apihelper.ApiTelegramException as api_err:
            bot_logger.error(
                f"Failed to register handlers: {sanitize_exception(api_err)}"
            )
        except Exception as err:
            bot_logger.exception(f"Unexpected error while registering handlers: {err}")

    def _start_webhook_mode(self):
        """
        Starts the bot in webhook mode and sets up the webhook.
        """
        try:
            from pytmbot.webhook import WebhookServer

            bot_logger.info("Starting webhook mode...")

            webhook_settings = settings.webhook_config

            url = webhook_settings.url[0].get_secret_value()
            bot_logger.debug(f"Webhook URL: {url}")
            port = webhook_settings.webhook_port[0]
            bot_logger.debug(f"Webhook port: {port}")

            webhook_url = f"https://{url}:{port}/webhook/{self.bot.token}/"

            bot_logger.debug("Generated webhook URL.")

            # Set the webhook
            self._set_webhook(
                webhook_url,
                certificate_path=settings.webhook_config.cert[0].get_secret_value()
                or None,
            )
            bot_logger.info("Webhook successfully set.")

            # Start the FastAPI server
            webhook_server = WebhookServer(
                self.bot,
                self.bot.token,
                self.args.socket_host,
                webhook_settings.local_port[0],
            )
            webhook_server.run()
        except ImportError as import_error:
            bot_logger.exception(f"Failed to import FastAPI: {import_error}")
        except ValueError as value_error:
            bot_logger.exception(f"Failed to start webhook server: {value_error}")
        except Exception as error:
            bot_logger.exception(
                f"Unexpected error while starting webhook: {sanitize_exception(error)}"
            )
            exit(1)

    def _set_webhook(self, webhook_url: str, certificate_path: str = None):
        try:
            self.bot.set_webhook(
                url=webhook_url,
                timeout=20,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
                certificate=certificate_path,
            )
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Failed to set webhook: {sanitize_exception(error)}")
            exit(1)

    def start_bot_instance(self) -> None:
        """
        Starts the bot instance and enters an infinite polling loop or webhook mode.

        Raises:
            SystemExit: Exits the program if an unexpected error occurs.
        """
        bot_instance = self._create_bot_instance()
        bot_logger.info("Starting bot...")

        if self.args.webhook == "True":
            self._start_webhook_mode_with_error_handling()
        else:
            self._start_polling_mode_with_error_handling(bot_instance)

    def _start_webhook_mode_with_error_handling(self) -> None:
        """Starts the bot in webhook mode with error handling."""
        try:
            self.bot.remove_webhook()
            self._start_webhook_mode()
        except Exception as error:
            bot_logger.error(
                f"Unexpected error while starting or stopping webhook: {error}. Exiting..."
            )
            exit(1)

    def _start_polling_mode_with_error_handling(self, bot_instance) -> None:
        """Starts the bot in polling mode with error handling."""
        if self.bot.remove_webhook():
            bot_logger.warning("Webhook removed, but not in webhook mode.")

        try:
            self._start_polling_mode(bot_instance)
        except Exception as error:
            bot_logger.error(
                f"Unexpected error while starting polling mode: {error}. Exiting..."
            )
            exit(1)

    @staticmethod
    def _start_polling_mode(bot_instance: TeleBot):
        """
        Starts the bot in polling mode with dynamic backoff for connection errors.
        """
        base_sleep_time = 10
        max_sleep_time = 300
        current_sleep_time = base_sleep_time

        while True:
            try:
                bot_instance.infinity_polling(
                    skip_pending=True,
                    timeout=var_config.bot_polling_timeout,
                    long_polling_timeout=var_config.bot_long_polling_timeout,
                )
                current_sleep_time = base_sleep_time
            except ssl.SSLError as ssl_error:
                bot_logger.critical(
                    f"SSL error (potential security issue): {sanitize_exception(ssl_error)}. Shutting down."
                )
                raise ssl_error
            except telebot.apihelper.ApiTelegramException as t_error:
                bot_logger.error(
                    f"Polling failed: {sanitize_exception(t_error)}. Retrying in {current_sleep_time} seconds."
                )
                time.sleep(current_sleep_time)
                current_sleep_time = min(current_sleep_time * 2, max_sleep_time)
            except (
                urllib3.exceptions.ConnectionError,
                urllib3.exceptions.ReadTimeoutError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ConnectTimeout,
                urllib3.exceptions.MaxRetryError,
                urllib3.exceptions.NameResolutionError,
                OSError,
            ) as conn_error:
                bot_logger.error(
                    f"Connection error: {sanitize_exception(conn_error)}. Retrying in {current_sleep_time} seconds."
                )
                time.sleep(current_sleep_time)
                current_sleep_time = min(current_sleep_time * 2, max_sleep_time)
            except telebot.apihelper.ApiException as api_error:
                bot_logger.error(
                    f"API error: {sanitize_exception(api_error)}. Retrying in {current_sleep_time} seconds."
                )
                time.sleep(current_sleep_time)
                current_sleep_time = min(current_sleep_time * 2, max_sleep_time)
            except Exception as error:
                bot_logger.exception(
                    f"Unexpected error: {sanitize_exception(error)}. Retrying in {current_sleep_time} seconds."
                )
                time.sleep(current_sleep_time)
                current_sleep_time = min(current_sleep_time * 2, max_sleep_time)


__all__ = ["PyTMBot"]
