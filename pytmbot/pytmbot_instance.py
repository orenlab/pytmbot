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
    __repository__,
    bot_commands_settings,
    bot_description_settings,
    var_config,
)
from pytmbot.handlers.handler_manager import (
    handler_factory,
    inline_handler_factory,
    # echo_handler_factory,
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

        init_context = {
            "core": {
                "action": "core_init",
                "version": __version__,
                "environment": get_environment_state(),
            }
        }

        self.log.info("Initializing PyTMBot", **init_context)

        self.bot: TeleBot | None = None
        self.plugin_manager = PluginManager()

    def is_healthy(self) -> bool:
        context = {"action": "health_check"}
        self.log.debug("Performing health check", **context)
        try:
            healthy = self.bot is not None and self.bot.get_me()
            self.log.debug("Health check completed", healthy=bool(healthy), **context)
            return True if healthy else False
        except telebot.apihelper.ApiException as e:
            self.log.error(
                "Telegram API connection failed", error=sanitize_exception(e), **context
            )
            return False
        except Exception as e:
            self.log.error(
                "Health check failed", error=sanitize_exception(e), **context
            )
            return False

    def retrieve_bot_token(self) -> str:
        context = {"action": "token_retrieval"}
        try:
            token = (
                settings.bot_token.dev_bot_token[0].get_secret_value()
                if self.args.mode == "dev"
                else settings.bot_token.prod_token[0].get_secret_value()
            )
            self.log.debug("Bot token retrieved", **context)
            return token
        except AttributeError as error:
            raise InitializationError(
                ErrorContext(
                    message="Error retrieving bot token",
                    error_code="CORE_001",
                    metadata={"original_error": str(error)},
                )
            )
        except FileNotFoundError as error:
            raise InitializationError(
                ErrorContext(
                    message="File not found error",
                    error_code="CORE_002",
                    metadata={"original_error": str(error)},
                )
            )
        except ValueError as error:
            raise InitializationError(
                ErrorContext(
                    message="Value error",
                    error_code="CORE_003",
                    metadata={
                        "requested_mode": self.args.mode,
                        "original_error": str(error),
                    },
                )
            )

    def initialize_bot_core(self) -> TeleBot:
        context = {"action": "core_init"}
        self.log.info("Initializing bot core", **context)

        bot_token = self.retrieve_bot_token()
        self.bot = self.create_base_bot(bot_token)
        self.configure_bot_features()

        self.log.info(
            f"Bot initialized successfully: {__version__} ({__repository__})", **context
        )
        return self.bot

    def create_base_bot(self, bot_token: str) -> TeleBot:
        context = {"action": "bot_creation"}
        try:
            bot = telebot.TeleBot(
                token=bot_token,
                threaded=True,
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotExceptionHandler(),
                skip_pending=True,
            )
            self.log.debug("Bot instance created", **context)
            return bot
        except Exception as e:
            self.log.error(
                "Bot instance creation failed", error=sanitize_exception(e), **context
            )
            raise

    def configure_bot_features(self) -> None:
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not initialized")

        context = {"action": "features_config"}
        try:
            self.setup_commands_and_description()
            self.setup_middleware_chain(DEFAULT_MIDDLEWARES)
            self.register_handler_chain()
            self.load_plugins()
            self.log.info("Bot features configured successfully", **context)
        except Exception as e:
            self.log.error(
                "Features configuration failed", error=sanitize_exception(e), **context
            )
            raise

    def setup_commands_and_description(self) -> None:
        context = {"action": "commands_setup"}
        try:
            commands = [
                BotCommand(command, desc)
                for command, desc in bot_commands_settings.bot_commands.items()
            ]
            self.bot.set_my_commands(commands)
            self.bot.set_my_description(bot_description_settings.bot_description)
            self.log.debug(
                "Commands and description set", commands_count=len(commands), **context
            )
        except ApiTelegramException as error:
            self.log.error(
                "Failed to set commands/description",
                error=sanitize_exception(error),
                **context,
            )

    def register_handler_chain(self) -> None:
        handlers_config = [
            (handler_factory, self.bot.register_message_handler),
            (inline_handler_factory, self.bot.register_callback_query_handler),
        ]

        context = {"action": "handlers_registration"}
        for factory, register_method in handlers_config:
            try:
                self.register_handler_group(factory, register_method)
            except Exception as e:
                self.log.error(
                    "Handler registration failed",
                    handler_type=factory.__name__,
                    error=sanitize_exception(e),
                    **context,
                )
                raise

    def setup_middleware_chain(self, middlewares: list[MiddlewareType]) -> None:
        context = {"action": "middleware_setup"}
        for middleware_class, kwargs in sorted(
            middlewares, key=lambda x: x[1].get("priority", 999)
        ):
            try:
                middleware_instance = middleware_class(bot=self.bot, **kwargs)
                self.bot.setup_middleware(middleware_instance)
                self.log.debug(
                    "Middleware configured",
                    middleware=middleware_class.__name__,
                    priority=kwargs.get("priority"),
                    **context,
                )
            except Exception as error:
                self.log.critical(
                    "Middleware setup failed",
                    middleware=middleware_class.__name__,
                    error=sanitize_exception(error),
                    **context,
                )
                raise

    def load_plugins(self) -> None:
        if not self.args.plugins:
            return

        context = {"action": "plugins_load"}
        try:
            self.plugin_manager.register_plugins(self.args.plugins, self.bot)
            self.log.info("Plugins loaded", plugins=self.args.plugins, **context)
        except Exception as err:
            self.log.error(
                "Plugin registration failed", error=sanitize_exception(err), **context
            )

    def register_handler_group(
        self,
        handler_factory_func: Callable[[], HandlerDict],
        register_method: RegisterMethod,
    ) -> None:
        context = {"action": "handler_group_registration"}
        try:
            handlers_dict = handler_factory_func()
            for handlers in handlers_dict.values():
                for handler in handlers:
                    register_method(handler.callback, **handler.kwargs, pass_bot=True)
            self.log.debug(
                "Handler group registered",
                factory=handler_factory_func.__name__,
                **context,
            )
        except Exception as err:
            self.log.error(
                "Handler group registration failed",
                factory=handler_factory_func.__name__,
                error=sanitize_exception(err),
                **context,
            )
            raise

    def launch_bot(self) -> None:
        context = {"action": "bot_launch"}
        self.bot = self.initialize_bot_core()
        self.log.info("Starting bot", **context)

        try:
            self.bot.remove_webhook()
            if self.args.webhook == "True":
                self.start_webhook_server()
            else:
                self.start_polling_loop(self.bot)
        except Exception as error:
            self.log.error(
                "Bot launch failed", error=sanitize_exception(error), **context
            )
            raise

    def recovery(self) -> bool:
        context = {"action": "recovery"}
        try:
            self.bot.get_me()
            if not self.args.webhook == "True":
                self.bot.stop_polling()

            sleep(2)
            self.launch_bot()
            self.log.info("Recovery successful", **context)
            return True

        except ApiTelegramException as err:
            self.log.error(
                "Recovery failed: API error", error=sanitize_exception(err), **context
            )
            return False
        except Exception as err:
            self.log.error(
                "Recovery failed: critical error",
                error=sanitize_exception(err),
                **context,
            )
            return False

    def start_webhook_server(self) -> None:
        context = {"action": "webhook_start"}
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not initialized")

        try:
            from pytmbot.webhook import WebhookServer

            config = WebhookConfig(
                host=self.args.socket_host,
                port=settings.webhook_config.local_port[0],
                token=self.bot.token,
            )

            server = WebhookServer(self.bot, **config)
            self.log.info(
                "Starting webhook server",
                host=config["host"],
                port=config["port"],
                **context,
            )
            server.start()

        except ImportError as err:
            self.log.error(
                "FastAPI import failed", error=sanitize_exception(err), **context
            )
            raise
        except Exception as err:
            self.log.error(
                "Webhook server start failed", error=sanitize_exception(err), **context
            )
            raise

    def start_polling_loop(self, bot_instance: TeleBot) -> None:
        current_sleep_time = DEFAULT_BASE_SLEEP_TIME
        context = {
            "action": "polling",
            "skip_pending": True,
            "timeout": var_config.bot_polling_timeout,
            "long_polling_timeout": var_config.bot_long_polling_timeout,
        }

        while True:
            try:
                self.log.info("Starting polling loop", **context)
                bot_instance.infinity_polling(
                    skip_pending=True,
                    timeout=var_config.bot_polling_timeout,
                    long_polling_timeout=var_config.bot_long_polling_timeout,
                )
                current_sleep_time = DEFAULT_BASE_SLEEP_TIME

            except ssl.SSLError as ssl_error:
                self.log.critical(
                    "SSL security error", error=sanitize_exception(ssl_error), **context
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
                self.log.error(
                    "Polling connection error",
                    error=sanitize_exception(error),
                    retry_delay=current_sleep_time,
                    **context,
                )
                time.sleep(current_sleep_time)
                current_sleep_time = min(current_sleep_time * 2, DEFAULT_MAX_SLEEP_TIME)
