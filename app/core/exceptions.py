#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import ExceptionHandler

from app.core.logs import bot_logger
from app.core.settings.bot_settings import BotSettings


class PyTeleMonBotError(Exception):
    """
    Base class for all PyTeleMonBot exceptions.
    """


class PyTeleMonBotConnectionError(PyTeleMonBotError):
    """
    Exception raised when an error occurs while connecting to the server.
    """


class PyTeleMonBotHandlerError(PyTeleMonBotError):
    """
    Exception raised when an error occurs while handling a message.
    """


class PyTeleMonBotTemplateError(PyTeleMonBotError):
    """
    Exception raised when an error occurs while using a template.
    """


class DockerAdapterException(PyTeleMonBotError):
    """
    Exception raised when an error occurs while using Docker.
    """


class TelebotCustomExceptionHandler(ExceptionHandler):
    """
    Custom exception handler for Telebot.
    """

    def handle(self, exception: Exception) -> bool:
        """
        Log and handle exceptions raised by Telebot.

        Args:
            exception (Exception): The exception to handle.

        Returns:
            bool: True if the exception was handled successfully.
        """
        sanitized_exception = self._sanitize_exception(exception)
        bot_logger.error(f"Failed at @Telebot package: {sanitized_exception}")
        return True

    @staticmethod
    def _sanitize_exception(exception: Exception) -> str:
        config = BotSettings()
        exception_str = str(exception)
        secret_map = {
            config.bot_token.get_secret_value(): "bot_token*********",
            config.dev_bot_token.get_secret_value(): "dev_bot_token*********"
        }
        for secret, placeholder in secret_map.items():
            exception_str = exception_str.replace(secret, placeholder)
        return exception_str
