#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from dataclasses import dataclass, field

import requests
import urllib3.exceptions
from telebot import ExceptionHandler
from telebot.apihelper import ApiHTTPException, ApiTelegramException

from pytmbot.logs import Logger
from pytmbot.utils import parse_cli_args, sanitize_exception

logger = Logger()


@dataclass(slots=True)
class ErrorContext:
    message: str
    error_code: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def sanitized(self) -> "ErrorContext":
        return ErrorContext(
            message=sanitize_exception(Exception(self.message)),
            error_code=self.error_code,
            metadata={
                k: sanitize_exception(Exception(str(v)))
                for k, v in (self.metadata or {}).items()
            },
        )

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        return {
            "message": self.message,
            "error_code": self.error_code,
            "metadata": self.metadata,
        }


class BaseBotException(Exception):
    def __init__(self, context: ErrorContext | str) -> None:
        self.context = (
            context if isinstance(context, ErrorContext) else ErrorContext(str(context))
        )
        super().__init__(str(self.context.message))

    def sanitized_message(self) -> str:
        return sanitize_exception(self)

    def sanitized_context(self) -> ErrorContext:
        return self.context.sanitized()


class BotException(BaseBotException):
    """Base class for bot operation related exceptions."""


class InitializationError(BotException):
    """Raised during bot initialization failures."""


class ShutdownError(BotException):
    """Raised during bot shutdown failures."""


class AuthError(BotException):
    """Raised during authentication failures."""


class ConnectionException(BaseBotException):
    """Base class for connection related exceptions."""


class HandlingException(BaseBotException):
    """Base class for message and template handling exceptions."""


class TemplateError(HandlingException):
    """Raised on template processing failures."""


class DockerException(BaseBotException):
    """Base class for Docker related exceptions."""


class DockerConnectionError(DockerException):
    """Raised on Docker daemon connection failures."""


class DockerOperationException(DockerException):
    """Base class for Docker operation exceptions."""


class ContainerException(DockerOperationException):
    """Base class for container related exceptions."""


class ContainerNotFoundError(ContainerException):
    """Raised when a container cannot be found."""


class ContainerLogsUnavailableError(ContainerException):
    """Raised when container logs cannot be read with current logging driver."""


class InvalidContainerReferenceError(ContainerException):
    """Raised when a container reference is not a valid Docker name or ID."""


class ContainerActionInProgressError(ContainerException):
    """Raised when another action on the same container is still running."""


class ContainerStateConflictError(ContainerException):
    """Raised when an action does not fit the container's current state."""

    def __init__(self, context: ErrorContext | str, *, state: str = "") -> None:
        super().__init__(context)
        self.state = state


class ImageException(DockerOperationException):
    """Base class for image related exceptions."""


class ImageOperationError(ImageException):
    """Raised on image operation failures."""


class QRCodeError(BaseBotException):
    """Raised on QR code generation failures."""


# Telegram answers these immediately. pyTelegramBotAPI defers the next getUpdates
# only when ExceptionHandler.handle() returns False (0.25s, then double, cap 60s).
_TRANSIENT_TELEGRAM_STATUS_CODES = frozenset({409, 429, 500, 502, 503, 504})

# Transport failures are not ApiException. Unhandled, polling() raises them and
# the launcher defers the next poll. Handled, the library retries in 0.25s flat.
_TRANSPORT_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
    urllib3.exceptions.HTTPError,
    TimeoutError,
    ConnectionError,
)


def _library_defers_retry(exception: Exception) -> bool:
    """Whether pyTelegramBotAPI, not this handler, should postpone the next call."""
    if isinstance(exception, ApiTelegramException):
        return exception.error_code in _TRANSIENT_TELEGRAM_STATUS_CODES
    if isinstance(exception, ApiHTTPException):
        status_code = getattr(getattr(exception, "result", None), "status_code", None)
        return (
            not isinstance(status_code, int)
            or status_code in _TRANSIENT_TELEGRAM_STATUS_CODES
        )
    return isinstance(exception, _TRANSPORT_ERRORS)


class TelebotExceptionHandler(ExceptionHandler):
    """Custom exception handler for Telebot with structured logging and token sanitization."""

    # codeclone: ignore[dead-code]
    def handle(self, exception: Exception) -> bool:
        """Log the failure. Return False when the library must defer the retry.

        ``TeleBot.__threaded_polling`` treats ``True`` as "already handled" and
        then sleeps a fixed ``error_interval`` of 0.25s. That interval grows
        (0.25s, 0.5s, ... 60s) only on the unhandled ``ApiException`` path.
        Returning ``True`` for 502 and read timeouts is what produced a few
        requests per second for the whole outage. Transport errors are not
        ``ApiException``: returning ``False`` lets ``polling()`` raise, and
        the launcher applies its own backoff.
        """
        log_level = parse_cli_args().log_level
        log_context: dict[str, object] = {
            "exception_type": type(exception).__name__,
        }

        if isinstance(exception, BaseBotException):
            sanitized_message = exception.sanitized_message()
            error_context = exception.sanitized_context()
            log_context["message"] = sanitized_message
            log_context["error_code"] = error_context.error_code
            if error_context.metadata:
                log_context["metadata"] = error_context.metadata
        else:
            log_context["message"] = sanitize_exception(exception)

        if log_level == "DEBUG":
            if isinstance(exception, BaseBotException):
                logger.opt(exception=exception).debug(
                    "bot.exceptions.telebot.fail", **log_context
                )
            else:
                logger.bind(sensitive_exception=True).debug(
                    "bot.exceptions.telebot.fail", **log_context
                )
        else:
            logger.error("bot.exceptions.telebot.fail", **log_context)

        return not _library_defers_retry(exception)


class InfluxDBException(BaseBotException):
    """Base class for InfluxDB related exceptions."""


class InfluxDBConnectionError(ConnectionException):
    """Raised on InfluxDB connection failures."""


class InfluxDBConfigError(InfluxDBException):
    """Raised on InfluxDB configuration issues."""


class InfluxDBWriteError(InfluxDBException):
    """Raised on InfluxDB write operation failures."""


class InfluxDBQueryError(InfluxDBException):
    """Raised on InfluxDB query operation failures."""


class KeyboardError(BaseBotException):
    """Custom exception for keyboard-related errors."""


class TOTPError(BaseBotException):
    """Custom exception for TOTP-related errors."""
