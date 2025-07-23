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
from functools import wraps
from time import sleep
from typing import Any, Final, TypedDict

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

type MiddlewareType = tuple[type, dict[str, Any]]
type HandlerDict = dict[str, list[HandlerManager]]
type RegisterMethod = Callable[..., Any]
PollingExceptionTypes: tuple[type[BaseException], ...] = (
    telebot.apihelper.ApiTelegramException,
    urllib3.exceptions.ConnectionError,
    urllib3.exceptions.ReadTimeoutError,
    requests.exceptions.ConnectionError,
    requests.exceptions.ConnectTimeout,
    urllib3.exceptions.MaxRetryError,
    urllib3.exceptions.NameResolutionError,
    telebot.apihelper.ApiException,
    OSError,
)


class WebhookConfig(TypedDict):
    host: str
    port: int
    token: str


# Constants with better organization
DEFAULT_BASE_SLEEP_TIME: Final[int] = 10
DEFAULT_MAX_SLEEP_TIME: Final[int] = 300
DEFAULT_MIDDLEWARES: Final[list[MiddlewareType]] = [
    (AccessControl, {}),
    (RateLimit, {"limit": 8, "period": timedelta(seconds=10)}),
]


def bot_required(func: Callable) -> Callable:
    """
    Decorator to ensure bot instance is initialized before method execution.

    Raises:
        RuntimeError: If bot instance is not initialized (None).
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not isinstance(self.bot, TeleBot):
            raise RuntimeError("Bot instance not initialized")
        return func(self, *args, **kwargs)

    return wrapper


class PyTMBot(BaseComponent):
    """
    Main bot class handling initialization, configuration, and runtime management.

    This class follows the single responsibility principle and provides
    clear separation of concerns for different bot operations.
    """

    __slots__ = ("args", "log", "bot", "_middlewares", "plugin_manager")

    def __init__(self) -> None:
        super().__init__("core")
        self.args = parse_cli_args()
        self.log = Logger()

        self._middlewares: dict[str, Any] = {}

        # Single comprehensive initialization log
        with self.log_context(
                version=__version__,
                mode=self.args.mode,
                webhook_mode=self.args.webhook == "True",
                plugins_enabled=bool(
                    self.args.plugins and any(p.strip() for p in self.args.plugins)
                ),
                environment=get_environment_state(),
        ) as log:
            log.info("PyTMBot initialization started")

        self.bot: TeleBot | None = None
        self.plugin_manager = PluginManager()

    def is_healthy(self) -> bool:
        """Check if bot is healthy and responsive."""
        if self.bot is None:
            return False

        try:
            return bool(self.bot.get_me())
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
            ) from error
        except (FileNotFoundError, ValueError) as error:
            raise InitializationError(
                ErrorContext(
                    message="Bot token configuration error",
                    error_code="CORE_002",
                    metadata={"mode": self.args.mode, "error": str(error)},
                )
            ) from error

    def _create_base_bot(self, bot_token: str) -> TeleBot:
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

    @bot_required
    def _setup_commands_and_description(self) -> None:
        """Setup bot commands and description."""
        try:
            commands = [
                BotCommand(command, desc)
                for command, desc in bot_commands_settings.bot_commands.items()
            ]
            self.bot.set_my_commands(commands)
            self.bot.set_my_description(bot_description_settings.bot_description)

            # Only log in debug mode or if there are actually commands
            if self.args.mode == "dev" or commands:
                with self.log_context(commands_count=len(commands)) as log:
                    log.debug(
                        "Bot commands configured",
                        commands=[cmd.command for cmd in commands],
                    )

        except ApiTelegramException as error:
            with self.log_context(error=sanitize_exception(error)) as log:
                log.warning("Failed to set bot commands or description")

    @bot_required
    def _setup_middleware_chain(self, middlewares: list[MiddlewareType]) -> None:
        """Setup middleware chain with statistics collection."""
        middleware_names = []
        middleware_details = []

        for middleware_class, kwargs in sorted(
                middlewares, key=lambda x: x[1].get("priority", 999)
        ):
            try:
                middleware_instance = middleware_class(bot=self.bot, **kwargs)
                self.bot.setup_middleware(middleware_instance)

                # Store middleware instance for stats collection
                middleware_name = middleware_class.__name__.lower()
                self._middlewares[middleware_name] = middleware_instance

                middleware_names.append(middleware_class.__name__)

                # Add specific middleware details for logging
                if middleware_class.__name__ == "RateLimit":
                    middleware_details.append(
                        {
                            "name": middleware_class.__name__,
                            "limit": kwargs.get("limit", "default"),
                            "period": str(kwargs.get("period", "default")),
                        }
                    )
                else:
                    middleware_details.append({"name": middleware_class.__name__})

            except Exception as error:
                with self.log_context(
                        middleware=middleware_class.__name__,
                        error=sanitize_exception(error),
                ) as log:
                    log.error("Middleware setup failed")
                raise

        # Single comprehensive log for all middleware
        with self.log_context(
                middleware_count=len(middleware_names),
                middleware_chain=middleware_names,
                details=middleware_details if self.args.mode == "dev" else None,
        ) as log:
            log.info("Middleware chain configured")

    def get_middleware_stats(self, middleware_name: str) -> dict[str, Any] | None:
        """Get statistics from specific middleware."""
        middleware_key = middleware_name.lower()

        if middleware_key not in self._middlewares:
            # Don't log - this is expected behavior for non-existent middleware
            return None

        middleware_instance = self._middlewares[middleware_key]

        # Check if middleware has get_stats method
        if not hasattr(middleware_instance, "get_stats"):
            return None

        try:
            return middleware_instance.get_stats()
        except Exception as error:
            with self.log_context(
                    middleware=middleware_name, error=sanitize_exception(error)
            ) as log:
                log.error("Failed to get middleware statistics")
            return None

    def get_rate_limit_stats(self) -> dict[str, Any] | None:
        """Get rate limiting statistics."""
        return self.get_middleware_stats("RateLimit")

    @bot_required
    def _register_handler_group(
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

            # More descriptive handler type names
            handler_type = (
                "command"
                if "handler_factory" in handler_factory_func.__name__
                else "callback"
            )

            with self.log_context(
                    handler_type=handler_type, count=handler_count
            ) as log:
                log.debug(f"Registered {handler_count} {handler_type} handlers")

        except Exception as err:
            with self.log_context(
                    factory=handler_factory_func.__name__, error=sanitize_exception(err)
            ) as log:
                log.error("Handler group registration failed")
            raise

    @bot_required
    def _register_handler_chain(self) -> None:
        """Register all bot handlers."""
        handlers_config = [
            (handler_factory, self.bot.register_message_handler, "message"),
            (
                inline_handler_factory,
                self.bot.register_callback_query_handler,
                "callback",
            ),
        ]

        total_handlers = 0
        handler_summary = []

        for factory, register_method, handler_type in handlers_config:
            try:
                # Count handlers before registering
                handlers_dict = factory()
                handler_count = sum(
                    len(handlers) for handlers in handlers_dict.values()
                )

                # Register handlers
                for handlers in handlers_dict.values():
                    for handler in handlers:
                        register_method(
                            handler.callback, **handler.kwargs, pass_bot=True
                        )

                total_handlers += handler_count
                handler_summary.append(f"{handler_count} {handler_type}")

            except Exception as e:
                with self.log_context(
                        handler_type=handler_type, error=sanitize_exception(e)
                ) as log:
                    log.error(f"{handler_type.title()} handler registration failed")
                raise

        # Single comprehensive log for all handlers
        with self.log_context(
                total_handlers=total_handlers, breakdown=handler_summary
        ) as log:
            log.info(f"Handlers registered: {', '.join(handler_summary)}")

    @bot_required
    def _load_plugins(self) -> None:
        """Load plugins if specified."""
        if not self.args.plugins:
            return

        # Filter out empty plugins
        actual_plugins = [p.strip() for p in self.args.plugins if p.strip()]
        if not actual_plugins:
            return

        try:
            self.plugin_manager.register_plugins(self.args.plugins, self.bot)
            with self.log_context(
                    plugin_count=len(actual_plugins), plugins=actual_plugins
            ) as log:
                log.info(f"🔌 Loaded {len(actual_plugins)} plugins")
        except Exception as err:
            with self.log_context(
                    plugins=actual_plugins, error=sanitize_exception(err)
            ) as log:
                log.error("Plugin loading failed")
            raise

    @bot_required
    def _configure_bot_features(self) -> None:
        """Configure bot features including commands, middleware, and handlers."""
        try:
            # Group related operations with progress indicators
            self._setup_commands_and_description()
            self._setup_middleware_chain(DEFAULT_MIDDLEWARES)
            self._register_handler_chain()
            self._load_plugins()

            # Don't log success here - it's logged in initialize_bot_core
        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Bot configuration failed")
            raise

    def initialize_bot_core(self) -> TeleBot:
        """Initialize bot core components."""
        try:
            bot_token = self.retrieve_bot_token()
            self.bot = self._create_base_bot(bot_token)
            self._configure_bot_features()

            # Single comprehensive success log
            with self.log_context(
                    version=__version__,
                    mode=self.args.mode,
                    webhook_enabled=self.args.webhook == "True",
            ) as log:
                log.info("Bot core initialization completed")

            return self.bot
        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Bot core initialization failed")
            raise

    @bot_required
    def _start_webhook_server(self) -> None:
        """Start webhook server."""
        try:
            from pytmbot.webhook import WebhookServer

            config = WebhookConfig(
                host=self.args.socket_host,
                port=settings.webhook_config.local_port[0],
                token=self.bot.token,
            )

            with self.log_context(host=config["host"], port=config["port"]) as log:
                log.info(
                    f"🌐 Starting webhook server on {config['host']}:{config['port']}"
                )

            server = WebhookServer(self.bot, **config)
            server.start()

        except ImportError as err:
            with self.log_context(error=sanitize_exception(err)) as log:
                log.error("Webhook server failed - FastAPI not available")
            raise
        except Exception as err:
            with self.log_context(error=sanitize_exception(err)) as log:
                log.error("Webhook server failed to start")
            raise

    def _handle_polling_error(
            self, error: Exception, consecutive_errors: int, current_sleep_time: int
    ) -> tuple[int, int]:
        """Handle polling errors and return updated error count and sleep time."""
        if isinstance(error, ssl.SSLError):
            with self.log_context(
                    error=sanitize_exception(error), consecutive_errors=consecutive_errors
            ) as log:
                log.critical("SSL security error - terminating bot")
            raise

        if isinstance(error, PollingExceptionTypes):
            consecutive_errors += 1

            # Less verbose logging for common connection errors
            if consecutive_errors == 1:
                with self.log_context(
                        error_type=type(error).__name__, retry_delay=current_sleep_time
                ) as log:
                    log.warning(f"Connection error - retrying in {current_sleep_time}s")
            elif consecutive_errors % 5 == 0:  # Log every 5th consecutive error
                with self.log_context(
                        error_type=type(error).__name__,
                        consecutive_errors=consecutive_errors,
                        retry_delay=current_sleep_time,
                ) as log:
                    log.error(
                        f"Persistent connection issues ({consecutive_errors} errors)"
                    )

            time.sleep(current_sleep_time)
            current_sleep_time = min(current_sleep_time * 2, DEFAULT_MAX_SLEEP_TIME)
            return consecutive_errors, current_sleep_time

        # Unexpected error
        with self.log_context(
                error=sanitize_exception(error), consecutive_errors=consecutive_errors
        ) as log:
            log.critical("Unexpected polling error - terminating bot")
        raise

    def _start_polling_loop(self, bot_instance: TeleBot) -> None:
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
                if consecutive_errors > 0:
                    with self.log_context(previous_errors=consecutive_errors) as log:
                        log.info("Polling connection restored")

                current_sleep_time = DEFAULT_BASE_SLEEP_TIME
                consecutive_errors = 0

            except Exception as error:
                consecutive_errors, current_sleep_time = self._handle_polling_error(
                    error, consecutive_errors, current_sleep_time
                )

    def launch_bot(self) -> None:
        """Launch the bot with appropriate method (webhook or polling)."""
        self.bot = self.initialize_bot_core()

        webhook_enabled = self.args.webhook == "True"

        with self.log_context(
                webhook_enabled=webhook_enabled, mode=self.args.mode
        ) as log:
            launch_method = "webhook" if webhook_enabled else "polling"
            log.info(f"Launching bot with {launch_method} mode")

        try:
            self.bot.remove_webhook()
            if webhook_enabled:
                self._start_webhook_server()
            else:
                self._start_polling_loop(self.bot)
        except Exception as error:
            with self.log_context(error=sanitize_exception(error)) as log:
                log.error("Bot launch failed")
            raise

    def recovery(self) -> bool:
        """Attempt to recover from errors."""
        if not isinstance(self.bot, TeleBot):
            return False

        with self.log_context() as log:
            log.warning("Attempting bot recovery")

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

    # Backward compatibility - keeping old method names as public API
    def create_base_bot(self, bot_token: str) -> TeleBot:
        """Create base TeleBot instance. (Deprecated: use _create_base_bot)"""
        return self._create_base_bot(bot_token)

    def configure_bot_features(self) -> None:
        """Configure bot features. (Deprecated: use _configure_bot_features)"""
        self._configure_bot_features()

    def setup_commands_and_description(self) -> None:
        """Setup bot commands and description. (Deprecated: use _setup_commands_and_description)"""
        self._setup_commands_and_description()

    def register_handler_chain(self) -> None:
        """Register all bot handlers. (Deprecated: use _register_handler_chain)"""
        self._register_handler_chain()

    def setup_middleware_chain(self, middlewares: list[MiddlewareType]) -> None:
        """Setup middleware chain. (Deprecated: use _setup_middleware_chain)"""
        self._setup_middleware_chain(middlewares)

    def load_plugins(self) -> None:
        """Load plugins if specified. (Deprecated: use _load_plugins)"""
        self._load_plugins()

    def register_handler_group(
            self,
            handler_factory_func: Callable[[], HandlerDict],
            register_method: RegisterMethod,
    ) -> None:
        """Register a group of handlers. (Deprecated: use _register_handler_group)"""
        self._register_handler_group(handler_factory_func, register_method)

    def start_webhook_server(self) -> None:
        """Start webhook server. (Deprecated: use _start_webhook_server)"""
        self._start_webhook_server()

    def start_polling_loop(self, bot_instance: TeleBot) -> None:
        """Start polling loop. (Deprecated: use _start_polling_loop)"""
        self._start_polling_loop(bot_instance)
