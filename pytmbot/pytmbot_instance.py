#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import ssl
import time
from collections.abc import Callable
from datetime import timedelta
from time import sleep
from typing import Any, TypeAlias, Final, TypedDict

import requests
import telebot
import urllib3.exceptions
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import BotCommand

from pytmbot import exceptions
from pytmbot.exceptions import InitializationError, ErrorContext
from pytmbot.globals import (
    settings,
    __version__,
    bot_commands_settings,
    bot_description_settings,
    var_config,
)
from pytmbot.handlers.handler_manager import (
    handler_factory,
    inline_handler_factory,
)
from pytmbot.logs import Logger, BaseComponent
from pytmbot.middleware.access_control import AccessControl
from pytmbot.middleware.rate_limit import RateLimit
from pytmbot.models.handlers_model import HandlerManager
from pytmbot.plugins.plugin_manager import PluginManager
from pytmbot.utils import parse_cli_args, sanitize_exception, get_environment_state

MiddlewareType: TypeAlias = tuple[type, dict[str, Any]]
HandlerDict: TypeAlias = dict[str, list[HandlerManager]]
RegisterMethod: TypeAlias = Callable[..., Any]


class WebhookConfig(TypedDict):
    host: str
    port: int
    token: str


DEFAULT_BASE_SLEEP_TIME: Final[int] = 10
DEFAULT_MAX_SLEEP_TIME: Final[int] = 300
DEFAULT_MIDDLEWARES: Final[list[MiddlewareType]] = [
    (AccessControl, {}),
    (RateLimit, {"limit": 8, "period": timedelta(seconds=10)}),
]


class PyTMBot(BaseComponent):
    __slots__ = ("args", "log", "bot", "plugin_manager")

    def __init__(self) -> None:
        super().__init__("core")
        self.args = parse_cli_args()
        self.log = Logger()

        # Single initialization log with key information
        with self.log_context(
                version=__version__,
                mode=self.args.mode,
                environment=get_environment_state(),
        ) as log:
            log.info("PyTMBot core initialization started")

        self.bot: TeleBot | None = None
        self.plugin_manager = PluginManager()

    def is_healthy(self) -> bool:
        """Check if bot is healthy and responsive."""
        try:
            return self.bot is not None and bool(self.bot.get_me())
        except telebot.apihelper.ApiException as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Bot health check failed - Telegram API error")
            return False
        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Bot health check failed - unexpected error")
            return False

    def retrieve_bot_token(self) -> str:
        """Retrieve bot token based on mode."""
        try:
            token = (
                settings.bot_token.dev_bot_token[0].get_secret_value()
                if self.args.mode == "dev"
                else settings.bot_token.prod_token[0].get_secret_value()
            )
            return token
        except AttributeError as error:
            raise InitializationError(
                ErrorContext(
                    message="Bot token not found in configuration",
                    error_code="CORE_001",
                    metadata={"mode": self.args.mode, "error": str(error)},
                )
            )
        except (FileNotFoundError, ValueError) as error:
            raise InitializationError(
                ErrorContext(
                    message="Bot token configuration error",
                    error_code="CORE_002",
                    metadata={"mode": self.args.mode, "error": str(error)},
                )
            )

    def initialize_bot_core(self) -> TeleBot:
        """Initialize bot core components."""
        with self.log_context() as log:
            log.info("Initializing bot core components")

        try:
            bot_token = self.retrieve_bot_token()
            self.bot = self.create_base_bot(bot_token)
            self.configure_bot_features()

            with self.log_context(version=__version__) as log:
                log.info("Bot core initialization completed successfully")

            return self.bot
        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Bot core initialization failed")
            raise

    def create_base_bot(self, bot_token: str) -> TeleBot:
        """Create base TeleBot instance."""
        try:
            return telebot.TeleBot(
                token=bot_token,
                threaded=True,
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotExceptionHandler(),
                skip_pending=True,
            )
        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Failed to create bot instance")
            raise

    def configure_bot_features(self) -> None:
        """Configure bot features including commands, middleware, and handlers."""
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not initialized")

        try:
            self.setup_commands_and_description()
            self.setup_middleware_chain(DEFAULT_MIDDLEWARES)
            self.register_handler_chain()
            self.load_plugins()

            with self.log_context() as log:
                log.info("Bot features configured successfully")
        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Bot features configuration failed")
            raise

    def setup_commands_and_description(self) -> None:
        """Setup bot commands and description."""
        try:
            commands = [
                BotCommand(command, desc)
                for command, desc in bot_commands_settings.bot_commands.items()
            ]
            self.bot.set_my_commands(commands)
            self.bot.set_my_description(bot_description_settings.bot_description)

            with self.log_context(commands_count=len(commands)) as log:
                log.debug("Bot commands and description configured")
        except ApiTelegramException as error:
            with self.log_context(error=sanitize_exception(error)) as log:
                log.warning("Failed to set bot commands or description")

    def register_handler_chain(self) -> None:
        """Register all bot handlers."""
        handlers_config = [
            (handler_factory, self.bot.register_message_handler),
            (inline_handler_factory, self.bot.register_callback_query_handler),
        ]

        for factory, register_method in handlers_config:
            try:
                self.register_handler_group(factory, register_method)
            except Exception as e:
                with self.log_context(
                        handler_type=factory.__name__,
                        error=sanitize_exception(e)
                ) as log:
                    log.error("Handler registration failed")
                raise

    def setup_middleware_chain(self, middlewares: list[MiddlewareType]) -> None:
        """Setup middleware chain."""
        middleware_names = []

        for middleware_class, kwargs in sorted(
                middlewares, key=lambda x: x[1].get("priority", 999)
        ):
            try:
                middleware_instance = middleware_class(bot=self.bot, **kwargs)
                self.bot.setup_middleware(middleware_instance)
                middleware_names.append(middleware_class.__name__)
            except Exception as error:
                with self.log_context(
                        middleware=middleware_class.__name__,
                        error=sanitize_exception(error)
                ) as log:
                    log.error("Middleware setup failed")
                raise

        with self.log_context(middlewares=middleware_names) as log:
            log.debug("Middleware chain configured")

    def load_plugins(self) -> None:
        """Load plugins if specified."""
        if not self.args.plugins:
            return

        try:
            self.plugin_manager.register_plugins(self.args.plugins, self.bot)
            with self.log_context(plugins=self.args.plugins) as log:
                log.info("Plugins loaded successfully")
        except Exception as err:
            with self.log_context(
                    plugins=self.args.plugins,
                    error=sanitize_exception(err)
            ) as log:
                log.error("Plugin loading failed")
            raise

    def register_handler_group(
            self,
            handler_factory_func: Callable[[], HandlerDict],
            register_method: RegisterMethod,
    ) -> None:
        """Register a group of handlers."""
        try:
            handlers_dict = handler_factory_func()
            handler_count = 0

            for handlers in handlers_dict.values():
                for handler in handlers:
                    register_method(handler.callback, **handler.kwargs, pass_bot=True)
                    handler_count += 1

            with self.log_context(
                    factory=handler_factory_func.__name__,
                    count=handler_count
            ) as log:
                log.debug("Handler group registered")
        except Exception as err:
            with self.log_context(
                    factory=handler_factory_func.__name__,
                    error=sanitize_exception(err)
            ) as log:
                log.error("Handler group registration failed")
            raise

    def launch_bot(self) -> None:
        """Launch the bot with appropriate method (webhook or polling)."""
        self.bot = self.initialize_bot_core()

        with self.log_context(webhook_enabled=self.args.webhook == "True") as log:
            log.info("Bot launch initiated")

        try:
            self.bot.remove_webhook()
            if self.args.webhook == "True":
                self.start_webhook_server()
            else:
                self.start_polling_loop(self.bot)
        except Exception as error:
            with self.log_context(error=sanitize_exception(error)) as log:
                log.error("Bot launch failed")
            raise

    def recovery(self) -> bool:
        """Attempt to recover from errors."""
        with self.log_context() as log:
            log.info("Attempting bot recovery")

        try:
            # Test connection
            self.bot.get_me()

            # Stop current operations
            if self.args.webhook != "True":
                self.bot.stop_polling()

            sleep(2)

            # Restart
            self.launch_bot()

            with self.log_context() as log:
                log.info("Bot recovery successful")
            return True

        except (ApiTelegramException, Exception) as err:
            with self.log_context(error=sanitize_exception(err)) as log:
                log.error("Bot recovery failed")
            return False

    def start_webhook_server(self) -> None:
        """Start webhook server."""
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not initialized")

        try:
            from pytmbot.webhook import WebhookServer

            config = WebhookConfig(
                host=self.args.socket_host,
                port=settings.webhook_config.local_port[0],
                token=self.bot.token,
            )

            with self.log_context(
                    host=config["host"],
                    port=config["port"]
            ) as log:
                log.info("Starting webhook server")

            server = WebhookServer(self.bot, **config)
            server.start()

        except ImportError as err:
            with self.log_context(error=sanitize_exception(err)) as log:
                log.error("Webhook server start failed - FastAPI not available")
            raise
        except Exception as err:
            with self.log_context(error=sanitize_exception(err)) as log:
                log.error("Webhook server start failed")
            raise

    def start_polling_loop(self, bot_instance: TeleBot) -> None:
        """Start polling loop with exponential backoff on errors."""
        current_sleep_time = DEFAULT_BASE_SLEEP_TIME
        consecutive_errors = 0

        with self.log_context(
                timeout=var_config.bot_polling_timeout,
                long_polling_timeout=var_config.bot_long_polling_timeout,
        ) as log:
            log.info("Starting polling loop")

        while True:
            try:
                bot_instance.infinity_polling(
                    skip_pending=True,
                    timeout=var_config.bot_polling_timeout,
                    long_polling_timeout=var_config.bot_long_polling_timeout,
                )
                # Reset backoff on successful polling
                current_sleep_time = DEFAULT_BASE_SLEEP_TIME
                consecutive_errors = 0

            except ssl.SSLError as ssl_error:
                with self.log_context(
                        error=sanitize_exception(ssl_error),
                        consecutive_errors=consecutive_errors
                ) as log:
                    log.critical("SSL security error - terminating")
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
                consecutive_errors += 1

                with self.log_context(
                        error=sanitize_exception(error),
                        retry_delay=current_sleep_time,
                        consecutive_errors=consecutive_errors,
                        max_delay=DEFAULT_MAX_SLEEP_TIME
                ) as log:
                    log.error("Polling connection error - retrying")

                time.sleep(current_sleep_time)
                current_sleep_time = min(current_sleep_time * 2, DEFAULT_MAX_SLEEP_TIME)

            except Exception as unexpected_error:
                with self.log_context(
                        error=sanitize_exception(unexpected_error),
                        consecutive_errors=consecutive_errors
                ) as log:
                    log.critical("Unexpected polling error - terminating")
                raise
