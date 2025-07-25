#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import ssl
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
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


class BotState(Enum):
    """Bot operational states."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    RUNNING = "running"
    RECOVERING = "recovering"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"
    ERROR = "error"


class ConflictResolutionStrategy(Enum):
    """Strategies for handling bot conflicts."""

    GRACEFUL_SHUTDOWN = "graceful"
    FORCE_TAKEOVER = "force"
    ABORT = "abort"


@dataclass(frozen=True)
class BotSession:
    """Immutable bot session information."""

    session_id: str
    start_time: datetime
    mode: str
    webhook_enabled: bool

    @classmethod
    def create(cls, mode: str, webhook_enabled: bool) -> BotSession:
        return cls(
            session_id=str(uuid.uuid4())[:8],
            start_time=datetime.now(),
            mode=mode,
            webhook_enabled=webhook_enabled,
        )


@dataclass
class RecoveryAttempt:
    """Recovery attempt tracking."""

    timestamp: datetime
    error_type: str
    success: bool

    @classmethod
    def create(cls, error_type: str, success: bool) -> RecoveryAttempt:
        return cls(datetime.now(), error_type, success)


type MiddlewareType = tuple[type, dict[str, Any]]
type HandlerDict = dict[str, list[HandlerManager]]
type RegisterMethod = Callable[..., Any]

# Enhanced exception types for better categorization
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

CriticalExceptionTypes: tuple[type[BaseException], ...] = (
    ssl.SSLError,
    MemoryError,
    SystemExit,
    KeyboardInterrupt,
)


class WebhookConfig(TypedDict):
    host: str
    port: int
    token: str


# Constants with better organization
DEFAULT_BASE_SLEEP_TIME: Final[int] = 10
DEFAULT_MAX_SLEEP_TIME: Final[int] = 300
MAX_RECOVERY_ATTEMPTS: Final[int] = 3
RECOVERY_ATTEMPT_WINDOW: Final[timedelta] = timedelta(minutes=5)
POLLING_STOP_TIMEOUT: Final[int] = 30
HEALTH_CHECK_TIMEOUT: Final[int] = 10

DEFAULT_MIDDLEWARES: Final[list[MiddlewareType]] = [
    (AccessControl, {}),
    (RateLimit, {"limit": 8, "period": timedelta(seconds=10)}),
]

CONFLICT_RESOLUTION_STRATEGY: Final[ConflictResolutionStrategy] = (
    ConflictResolutionStrategy.GRACEFUL_SHUTDOWN
)


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
    clear separation of concerns for different bot operations with enhanced
    error handling and conflict resolution.
    """

    __slots__ = (
        "args",
        "log",
        "bot",
        "_middlewares",
        "plugin_manager",
        "_state",
        "_session",
        "_recovery_attempts",
        "_shutdown_timeout_occurred",
    )

    def __init__(self) -> None:
        super().__init__("core")
        self.args = parse_cli_args()
        self.log = Logger()

        self._middlewares: dict[str, Any] = {}
        self._state = BotState.UNINITIALIZED
        self._session: BotSession | None = None
        self._recovery_attempts: list[RecoveryAttempt] = []
        self._shutdown_timeout_occurred = False

        # Initialize session
        self._session = BotSession.create(
            mode=self.args.mode, webhook_enabled=self.args.webhook == "True"
        )

        # Single comprehensive initialization log
        with self.log_context(
            session_id=self._session.session_id,
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
        self._state = BotState.INITIALIZING

    @property
    def state(self) -> BotState:
        """Current bot state."""
        return self._state

    @property
    def session_info(self) -> BotSession | None:
        """Current session information."""
        return self._session

    def _change_state(self, new_state: BotState, reason: str = "") -> None:
        """Change bot state with logging."""
        old_state = self._state
        self._state = new_state

        with self.log_context(
            session_id=self._session.session_id if self._session else "unknown",
            old_state=old_state.value,
            new_state=new_state.value,
            reason=reason,
        ) as log:
            log.debug(f"State transition: {old_state.value} -> {new_state.value}")

    @staticmethod
    def _is_bot_conflict_error(error: Exception) -> bool:
        """Check if error indicates bot conflict (409 Conflict)."""
        return isinstance(error, ApiTelegramException) and error.error_code == 409

    @staticmethod
    def _is_critical_api_error(error: Exception) -> tuple[bool, str]:
        """
        Check if error is critical API error requiring special handling.

        Returns:
            tuple: (is_critical, error_type)
        """
        if not isinstance(error, ApiTelegramException):
            return False, ""

        critical_codes = {
            401: "unauthorized",  # Bot token invalid/revoked
            403: "forbidden",  # Bot blocked/restricted
            404: "not_found",  # Bot not found (deleted)
            409: "conflict",  # Multiple bot instances
            429: "rate_limited",  # Too many requests
            502: "bad_gateway",  # Telegram server issues
            503: "service_unavailable",  # Telegram maintenance
        }

        error_type = critical_codes.get(error.error_code)
        return error_type is not None, error_type or "unknown"

    @staticmethod
    def _is_critical_error(error: Exception) -> bool:
        """Check if error is critical and requires immediate shutdown."""
        return isinstance(error, CriticalExceptionTypes)

    def _handle_bot_conflict(self, strategy: ConflictResolutionStrategy = None) -> bool:
        """
        Handle bot conflict based on resolution strategy.

        Returns:
            bool: True if conflict was resolved, False otherwise.
        """
        if strategy is None:
            strategy = CONFLICT_RESOLUTION_STRATEGY

        with self.log_context(
            session_id=self._session.session_id if self._session else "unknown",
            strategy=strategy.value,
        ) as log:
            log.warning(f"Bot conflict detected, applying {strategy.value} strategy")

        match strategy:
            case ConflictResolutionStrategy.GRACEFUL_SHUTDOWN:
                return self._graceful_conflict_resolution()
            case ConflictResolutionStrategy.FORCE_TAKEOVER:
                return self._force_takeover()
            case ConflictResolutionStrategy.ABORT:
                return self._abort_on_conflict()
            case _:
                return False

    def _handle_critical_api_error(self, error: Exception, error_type: str) -> bool:
        """
        Handle critical API errors based on error type.

        Returns:
            bool: True if error was handled and recovery is possible, False otherwise.
        """
        with self.log_context(
            session_id=self._session.session_id if self._session else "unknown",
            error_code=getattr(error, "error_code", "unknown"),
            error_type=error_type,
            error_message=str(error),
        ) as log:
            log.error(f"Critical API error detected: {error_type}")

        match error_type:
            case "unauthorized":
                with self.log_context() as log:
                    log.critical(
                        "Bot token is invalid or revoked - manual intervention required"
                    )
                return False  # Cannot recover from invalid token

            case "forbidden":
                with self.log_context() as log:
                    log.critical("Bot is blocked or restricted - check bot permissions")
                return False  # Cannot recover from bot restrictions

            case "not_found":
                with self.log_context() as log:
                    log.critical("Bot not found - may have been deleted")
                return False  # Cannot recover from deleted bot

            case "conflict":
                # Handle bot conflicts with existing strategy
                return self._handle_bot_conflict()

            case "rate_limited":
                # Extract retry_after if available
                retry_after = getattr(error, "retry_after", 60)
                with self.log_context(retry_after=retry_after) as log:
                    log.warning(f"Rate limited - waiting {retry_after} seconds")
                time.sleep(min(retry_after, 300))  # Cap at 5 minutes
                return True  # Can recover after waiting

            case "bad_gateway" | "service_unavailable":
                with self.log_context() as log:
                    log.warning("Telegram server issues - will retry with backoff")
                return True  # Can recover with retry

            case _:
                with self.log_context() as log:
                    log.error(f"Unknown critical API error: {error_type}")
                return False  # Unknown error, cannot guarantee recovery

    def _graceful_conflict_resolution(self) -> bool:
        """Gracefully handle bot conflict by backing off."""
        try:
            if self.bot and hasattr(self.bot, "stop_polling"):
                self._safe_stop_polling()

            # Wait before attempting to restart
            sleep(DEFAULT_BASE_SLEEP_TIME * 2)
            return True

        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Graceful conflict resolution failed")
            return False

    def _force_takeover(self) -> bool:
        """Force takeover by removing webhook and starting fresh."""
        try:
            if self.bot:
                self.bot.remove_webhook()
                sleep(5)  # Give other instance time to detect webhook removal
            return True
        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Force takeover failed")
            return False

    def _abort_on_conflict(self) -> bool:
        """Abort operation on conflict."""
        with self.log_context() as log:
            log.error("Aborting due to bot conflict")
        return False

    @contextmanager
    def _polling_safety_context(self):
        """Context manager for safe polling operations."""
        polling_was_active = False
        try:
            if self.bot and hasattr(self.bot, "polling") and self.bot.polling:
                polling_was_active = True
            yield
        except Exception as e:
            # Handle polling-specific errors
            if self._is_bot_conflict_error(e):
                if not self._handle_bot_conflict():
                    raise
            else:
                raise
        finally:
            # Ensure polling is properly stopped if it was active
            if polling_was_active and self.bot:
                self._safe_stop_polling()

    def _safe_stop_polling(self, timeout: int = POLLING_STOP_TIMEOUT) -> bool:
        """
        Safely stop polling with timeout.

        Returns:
            bool: True if stopped successfully, False if timeout occurred.
        """
        if not self.bot or not hasattr(self.bot, "polling"):
            return True

        try:
            # Check if actually polling
            if not getattr(self.bot, "polling", False):
                return True

            with self.log_context(timeout=timeout) as log:
                log.debug("Stopping polling with timeout")

            # Use threading to implement timeout
            import threading
            import concurrent.futures

            def stop_polling_task():
                try:
                    self.bot.stop_polling()
                    return True
                except Exception as e:
                    with self.log_context(error=sanitize_exception(e)) as log:
                        log.warning("Error during polling stop")
                    return False

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(stop_polling_task)
                try:
                    result = future.result(timeout=timeout)
                    return result
                except concurrent.futures.TimeoutError:
                    with self.log_context() as log:
                        log.warning("Polling stop timeout occurred")
                    self._shutdown_timeout_occurred = True
                    return False

        except Exception as e:
            with self.log_context(error=sanitize_exception(e)) as log:
                log.error("Failed to stop polling safely")
            return False

    def _comprehensive_health_check(self) -> tuple[bool, str]:
        """
        Comprehensive health check with detailed status.

        Returns:
            tuple: (is_healthy, status_message)
        """
        if self.bot is None:
            return False, "Bot instance not initialized"

        try:
            # Test basic API connectivity
            bot_info = self.bot.get_me()
            if not bot_info:
                return False, "Failed to get bot information"

            # Check polling state if not using webhook
            if self._session and not self._session.webhook_enabled:
                polling_active = getattr(self.bot, "polling", False)
                if not polling_active and self._state == BotState.RUNNING:
                    return False, "Polling should be active but isn't"

            # Check if we're in a valid state
            if self._state in [BotState.ERROR, BotState.SHUTDOWN]:
                return False, f"Bot in invalid state: {self._state.value}"

            return True, "Bot is healthy"

        except ApiTelegramException as e:
            is_critical_api, error_type = self._is_critical_api_error(e)
            if is_critical_api:
                return False, f"Critical API error: {error_type} ({e.error_code})"
            return False, f"Telegram API error: {e.error_code}"
        except Exception as e:
            return False, f"Health check failed: {sanitize_exception(e)}"

    def is_healthy(self) -> bool:
        """Check if bot is healthy and responsive."""
        is_healthy, status = self._comprehensive_health_check()

        if not is_healthy:
            with self.log_context(
                session_id=self._session.session_id if self._session else "unknown",
                status=status,
                state=self._state.value,
            ) as log:
                log.warning(f"Health check failed: {status}")

        return is_healthy

    def _get_recent_recovery_attempts(self) -> list[RecoveryAttempt]:
        """Get recovery attempts within the window."""
        cutoff_time = datetime.now() - RECOVERY_ATTEMPT_WINDOW
        return [
            attempt
            for attempt in self._recovery_attempts
            if attempt.timestamp > cutoff_time
        ]

    def _can_attempt_recovery(self) -> bool:
        """Check if recovery can be attempted based on recent history."""
        recent_attempts = self._get_recent_recovery_attempts()
        return len(recent_attempts) < MAX_RECOVERY_ATTEMPTS

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
                    metadata={
                        "mode": self.args.mode,
                        "error": str(error),
                        "session_id": self._session.session_id
                        if self._session
                        else None,
                    },
                )
            ) from error
        except (FileNotFoundError, ValueError) as error:
            raise InitializationError(
                ErrorContext(
                    message="Bot token configuration error",
                    error_code="CORE_002",
                    metadata={
                        "mode": self.args.mode,
                        "error": str(error),
                        "session_id": self._session.session_id
                        if self._session
                        else None,
                    },
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
            with self.log_context(
                error=sanitize_exception(e),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
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
                with self.log_context(
                    commands_count=len(commands),
                    session_id=self._session.session_id if self._session else "unknown",
                ) as log:
                    log.debug(
                        "Bot commands configured",
                        commands=[cmd.command for cmd in commands],
                    )

        except ApiTelegramException as error:
            with self.log_context(
                error=sanitize_exception(error),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
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
                    session_id=self._session.session_id if self._session else "unknown",
                ) as log:
                    log.error("Middleware setup failed")
                raise

        # Single comprehensive log for all middleware
        with self.log_context(
            middleware_count=len(middleware_names),
            middleware_chain=middleware_names,
            details=middleware_details if self.args.mode == "dev" else None,
            session_id=self._session.session_id if self._session else "unknown",
        ) as log:
            log.info("Middleware chain configured")

    def get_middleware_stats(self, middleware_name: str) -> dict[str, Any] | None:
        """Get statistics from specific middleware."""
        middleware_key = middleware_name.lower()

        if middleware_key not in self._middlewares:
            return None

        middleware_instance = self._middlewares[middleware_key]

        # Check if middleware has get_stats method
        if not hasattr(middleware_instance, "get_stats"):
            return None

        try:
            return middleware_instance.get_stats()
        except Exception as error:
            with self.log_context(
                middleware=middleware_name,
                error=sanitize_exception(error),
                session_id=self._session.session_id if self._session else "unknown",
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
                handler_type=handler_type,
                count=handler_count,
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.debug(f"Registered {handler_count} {handler_type} handlers")

        except Exception as err:
            with self.log_context(
                factory=handler_factory_func.__name__,
                error=sanitize_exception(err),
                session_id=self._session.session_id if self._session else "unknown",
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
                    handler_type=handler_type,
                    error=sanitize_exception(e),
                    session_id=self._session.session_id if self._session else "unknown",
                ) as log:
                    log.error(f"{handler_type.title()} handler registration failed")
                raise

        # Single comprehensive log for all handlers
        with self.log_context(
            total_handlers=total_handlers,
            breakdown=handler_summary,
            session_id=self._session.session_id if self._session else "unknown",
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
                plugin_count=len(actual_plugins),
                plugins=actual_plugins,
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.info(f"🔌 Loaded {len(actual_plugins)} plugins")
        except Exception as err:
            with self.log_context(
                plugins=actual_plugins,
                error=sanitize_exception(err),
                session_id=self._session.session_id if self._session else "unknown",
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

        except Exception as e:
            with self.log_context(
                error=sanitize_exception(e),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.error("Bot configuration failed")
            raise

    def initialize_bot_core(self) -> TeleBot:
        """Initialize bot core components."""
        try:
            self._change_state(BotState.INITIALIZING, "Starting core initialization")

            bot_token = self.retrieve_bot_token()
            self.bot = self._create_base_bot(bot_token)
            self._configure_bot_features()

            self._change_state(BotState.RUNNING, "Core initialization completed")

            # Single comprehensive success log
            with self.log_context(
                version=__version__,
                mode=self.args.mode,
                webhook_enabled=self.args.webhook == "True",
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.info("Bot core initialization completed")

            return self.bot
        except Exception as e:
            self._change_state(BotState.ERROR, f"Initialization failed: {e}")
            with self.log_context(
                error=sanitize_exception(e),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
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

            with self.log_context(
                host=config["host"],
                port=config["port"],
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.info(
                    f"Starting webhook server on {config['host']}:{config['port']}"
                )

            server = WebhookServer(self.bot, **config)
            server.start()

        except ImportError as err:
            with self.log_context(
                error=sanitize_exception(err),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.error("Webhook server failed - FastAPI not available")
            raise
        except Exception as err:
            with self.log_context(
                error=sanitize_exception(err),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.error("Webhook server failed to start")
            raise

    def _handle_polling_error(
        self, error: Exception, consecutive_errors: int, current_sleep_time: int
    ) -> tuple[int, int]:
        """Handle polling errors and return updated error count and sleep time."""
        # Check for critical errors first
        if self._is_critical_error(error):
            with self.log_context(
                error=sanitize_exception(error),
                consecutive_errors=consecutive_errors,
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.critical("Critical error - terminating bot")
            raise

        # Handle critical API errors first
        is_critical_api, error_type = self._is_critical_api_error(error)
        if is_critical_api:
            if not self._handle_critical_api_error(error, error_type):
                # Cannot recover from this error type
                raise
            # If we can recover, continue with normal error handling

        if isinstance(error, PollingExceptionTypes):
            consecutive_errors += 1

            # Less verbose logging for common connection errors
            if consecutive_errors == 1:
                with self.log_context(
                    error_type=type(error).__name__,
                    retry_delay=current_sleep_time,
                    session_id=self._session.session_id if self._session else "unknown",
                ) as log:
                    log.warning(f"Connection error - retrying in {current_sleep_time}s")
            elif consecutive_errors % 5 == 0:  # Log every 5th consecutive error
                with self.log_context(
                    error_type=type(error).__name__,
                    consecutive_errors=consecutive_errors,
                    retry_delay=current_sleep_time,
                    session_id=self._session.session_id if self._session else "unknown",
                ) as log:
                    log.error(
                        f"Persistent connection issues ({consecutive_errors} errors)"
                    )

            time.sleep(current_sleep_time)
            current_sleep_time = min(current_sleep_time * 2, DEFAULT_MAX_SLEEP_TIME)
            return consecutive_errors, current_sleep_time

        # Unexpected error
        with self.log_context(
            error=sanitize_exception(error),
            consecutive_errors=consecutive_errors,
            session_id=self._session.session_id if self._session else "unknown",
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
            session_id=self._session.session_id if self._session else "unknown",
        ) as log:
            log.info("Starting polling loop")

        with self._polling_safety_context():
            while True:
                try:
                    bot_instance.infinity_polling(
                        skip_pending=True,
                        timeout=var_config.bot_polling_timeout,
                        long_polling_timeout=var_config.bot_long_polling_timeout,
                    )

                    # Reset backoff on successful polling
                    if consecutive_errors > 0:
                        with self.log_context(
                            previous_errors=consecutive_errors,
                            session_id=self._session.session_id
                            if self._session
                            else "unknown",
                        ) as log:
                            log.info("Polling connection restored")

                    current_sleep_time = DEFAULT_BASE_SLEEP_TIME
                    consecutive_errors = 0

                except Exception as error:
                    try:
                        if bot_instance.polling:
                            self._safe_stop_polling()
                            time.sleep(current_sleep_time)
                    except Exception as stop_err:
                        with self.log_context(
                            error=sanitize_exception(stop_err),
                            session_id=self._session.session_id
                            if self._session
                            else "unknown",
                        ) as log:
                            log.warning("Failed to stop polling before retry")

                    consecutive_errors, current_sleep_time = self._handle_polling_error(
                        error, consecutive_errors, current_sleep_time
                    )

    def launch_bot(self) -> None:
        """Launch the bot with appropriate method (webhook or polling)."""
        self.bot = self.initialize_bot_core()

        webhook_enabled = self.args.webhook == "True"

        with self.log_context(
            webhook_enabled=webhook_enabled,
            mode=self.args.mode,
            session_id=self._session.session_id if self._session else "unknown",
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
            self._change_state(BotState.ERROR, f"Launch failed: {error}")
            with self.log_context(
                error=sanitize_exception(error),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.error("Bot launch failed")
            raise

    def recovery(self) -> bool:
        """Attempt to recover from errors with improved logic."""
        if not isinstance(self.bot, TeleBot):
            return False

        # Check if recovery is allowed
        if not self._can_attempt_recovery():
            with self.log_context(
                session_id=self._session.session_id if self._session else "unknown"
            ) as log:
                log.warning("Recovery attempt limit reached")
            return False

        self._change_state(BotState.RECOVERING, "Starting recovery attempt")

        with self.log_context(
            session_id=self._session.session_id if self._session else "unknown"
        ) as log:
            log.warning("Attempting bot recovery")

        recovery_success = False
        error_type = "unknown"

        try:
            # Comprehensive health check first
            is_healthy, status = self._comprehensive_health_check()

            if is_healthy:
                with self.log_context(
                    session_id=self._session.session_id if self._session else "unknown"
                ) as log:
                    log.info("Bot is already healthy, no recovery needed")
                self._change_state(BotState.RUNNING, "Recovery not needed")
                return True

            error_type = status

            # Test basic API connection
            try:
                self.bot.get_me()
            except ApiTelegramException as api_err:
                is_critical_api, api_error_type = self._is_critical_api_error(api_err)
                if is_critical_api:
                    error_type = api_error_type
                    if not self._handle_critical_api_error(api_err, api_error_type):
                        raise
                else:
                    error_type = f"api_error_{api_err.error_code}"
                    raise

            # Stop current operations safely
            if self.args.webhook != "True":
                if hasattr(self.bot, "polling") and self.bot.polling:
                    if not self._safe_stop_polling():
                        with self.log_context(
                            session_id=self._session.session_id
                            if self._session
                            else "unknown"
                        ) as log:
                            log.warning("Polling stop timeout during recovery")

            # Brief pause before restart
            sleep(DEFAULT_BASE_SLEEP_TIME)

            # Restart bot operations
            self.launch_bot()

            # Verify recovery
            is_healthy, _ = self._comprehensive_health_check()
            recovery_success = is_healthy

            if recovery_success:
                self._change_state(BotState.RUNNING, "Recovery completed successfully")
                with self.log_context(
                    session_id=self._session.session_id if self._session else "unknown"
                ) as log:
                    log.info("Bot recovery successful")
            else:
                self._change_state(BotState.ERROR, "Recovery verification failed")

        except Exception as err:
            error_type = type(err).__name__
            self._change_state(BotState.ERROR, f"Recovery failed: {err}")
            with self.log_context(
                error=sanitize_exception(err),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.error("Bot recovery failed")

        finally:
            # Record recovery attempt
            attempt = RecoveryAttempt.create(error_type, recovery_success)
            self._recovery_attempts.append(attempt)

            # Clean up old attempts to prevent memory leak
            self._recovery_attempts = self._get_recent_recovery_attempts()

        return recovery_success

    def graceful_shutdown(self, timeout: int = POLLING_STOP_TIMEOUT) -> bool:
        """
        Perform graceful shutdown with timeout.

        Returns:
            bool: True if shutdown completed within timeout, False otherwise.
        """
        self._change_state(BotState.SHUTTING_DOWN, "Graceful shutdown initiated")

        with self.log_context(
            timeout=timeout,
            session_id=self._session.session_id if self._session else "unknown",
        ) as log:
            log.info("Starting graceful shutdown")

        shutdown_success = True

        try:
            if self.bot:
                # Remove webhook first if applicable
                if self._session and self._session.webhook_enabled:
                    try:
                        self.bot.remove_webhook()
                    except Exception as e:
                        with self.log_context(
                            error=sanitize_exception(e),
                            session_id=self._session.session_id
                            if self._session
                            else "unknown",
                        ) as log:
                            log.warning("Failed to remove webhook during shutdown")

                # Stop polling if active
                if not self._safe_stop_polling(timeout):
                    shutdown_success = False

                # Clean up middleware
                for middleware_name, middleware_instance in self._middlewares.items():
                    try:
                        if hasattr(middleware_instance, "cleanup"):
                            middleware_instance.cleanup()
                    except Exception as e:
                        with self.log_context(
                            middleware=middleware_name,
                            error=sanitize_exception(e),
                            session_id=self._session.session_id
                            if self._session
                            else "unknown",
                        ) as log:
                            log.warning("Middleware cleanup failed")

        except Exception as e:
            shutdown_success = False
            with self.log_context(
                error=sanitize_exception(e),
                session_id=self._session.session_id if self._session else "unknown",
            ) as log:
                log.error("Graceful shutdown encountered errors")

        finally:
            self._change_state(BotState.SHUTDOWN, "Shutdown completed")
            self.bot = None

        return shutdown_success

    def get_bot_session_statistics(self) -> dict[str, Any]:
        """Get comprehensive session statistics."""
        if not self._session:
            return {}

        uptime = datetime.now() - self._session.start_time
        recent_recovery_attempts = self._get_recent_recovery_attempts()

        stats: dict[str, Any] = {
            "session_id": self._session.session_id,
            "start_time": self._session.start_time.isoformat(),
            "uptime_seconds": int(uptime.total_seconds()),
            "uptime_human": str(uptime),
            "mode": self._session.mode,
            "webhook_enabled": self._session.webhook_enabled,
            "current_state": self._state.value,
            "recovery_attempts_recent": len(recent_recovery_attempts),
            "recovery_attempts_successful": len(
                [a for a in recent_recovery_attempts if a.success]
            ),
            "shutdown_timeout_occurred": self._shutdown_timeout_occurred,
        }

        # Add bot-specific stats if available
        if self.bot:
            is_healthy, health_status = self._comprehensive_health_check()
            stats.update(
                {
                    "bot_healthy": is_healthy,
                    "health_status": health_status,
                }
            )

            # Add middleware stats
            rate_limit_stats = self.get_rate_limit_stats()
            if rate_limit_stats:
                stats["rate_limit_stats"] = rate_limit_stats

        return stats
