#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import ExceptionHandler

from pytmbot.globals import settings
from pytmbot.logs import bot_logger


class PyTMBotError(Exception):
    """
    Base class for all PyTeleMonBot exceptions.
    """


class PyTMBotConnectionError(PyTMBotError):
    """
    Exception raised when an error occurs while connecting to the server.
    """


class PyTMBotErrorHandlerError(PyTMBotError):
    """
    Exception raised when an error occurs while handling a message.
    """


class PyTMBotErrorTemplateError(PyTMBotError):
    """
    Exception raised when an error occurs while using a template.
    """


class DockerAdapterException(PyTMBotError):
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
        bot_logger.exception(f"Failed at @Telebot package: {sanitized_exception}", exc_info=True)

        return True

    @staticmethod
    def _sanitize_exception(exception: Exception) -> str:
        exception_str = str(exception)
        secret_map = {
            settings.bot_token.prod_token[0].get_secret_value(): "********* BOT TOKEN *********",
            settings.bot_token.dev_bot_token[0].get_secret_value(): "********* DEV BOT TOKEN *********",
        }
        for secret, placeholder in secret_map.items():
            exception_str = exception_str.replace(secret, placeholder)
        return exception_str
