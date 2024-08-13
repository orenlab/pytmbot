#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import ExceptionHandler

from app import config
from app.core.logs import bot_logger


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

    def handle(self, ex: Exception) -> bool:
        """
        Log and handle exceptions raised by Telebot.

        Args:
            ex (Exception): The exception to handle.

        Returns:
            bool: True if the exception was handled successfully.
        """
        sanitized_ex = str(ex).replace(config.bot_token.get_secret_value(), "bot_token*********").replace(
            config.dev_bot_token.get_secret_value(), "dev_bot_token*********")

        # Log the exception
        bot_logger.error(f"Failed at @Telebot package: {str(sanitized_ex)}")

        # Return True to indicate successful handling of the exception
        return True
