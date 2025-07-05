#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from dataclasses import dataclass, field
from typing import Any

from telebot import ExceptionHandler

from pytmbot.logs import Logger
from pytmbot.utils import sanitize_exception, parse_cli_args

logger = Logger()


@dataclass
class ErrorContext:
    message: str
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def sanitized(self) -> "ErrorContext":
        return ErrorContext(
            message=sanitize_exception(Exception(self.message)),
            error_code=self.error_code,
            metadata={
                k: sanitize_exception(Exception(str(v)))
                for k, v in (self.metadata or {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
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


class ServerConnectionError(ConnectionException):
    """Raised on server connection failures."""


class HandlingException(BaseBotException):
    """Base class for message and template handling exceptions."""


class MessageHandlerError(HandlingException):
    """Raised on message handling failures."""


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


class ImageException(DockerOperationException):
    """Base class for image related exceptions."""


class ImageOperationError(ImageException):
    """Raised on image operation failures."""


class QRCodeError(BaseBotException):
    """Raised on QR code generation failures."""


class TelebotExceptionHandler(ExceptionHandler):
    """Custom exception handler for Telebot with structured logging and token sanitization."""

    def handle(self, exception: Exception) -> bool:
        """Handle and log Telebot exceptions with appropriate detail level and token sanitization."""
        log_level = parse_cli_args().log_level

        if isinstance(exception, BaseBotException):
            sanitized_msg = exception.sanitized_message()
            error_context = exception.sanitized_context()

            log_msg = sanitized_msg
            if error_context.metadata:
                log_msg = f"{sanitized_msg} - Context: {error_context.metadata}"
        else:
            log_msg = sanitize_exception(exception)

        if log_level == "DEBUG":
            if isinstance(exception, BaseBotException):
                logger.opt(exception=exception).debug(
                    f"Exception in @Telebot: {log_msg}"
                )
            else:
                logger.opt(exception=exception, diagnose=False).debug(
                    f"Exception in @Telebot: {log_msg}"
                )
        else:
            logger.error(f"Exception in @Telebot: {log_msg}")

        return True


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


class CallbackValidationError(BaseBotException):
    """Raised on Callback data validation error"""
