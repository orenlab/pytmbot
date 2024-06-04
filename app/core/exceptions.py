#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot import ExceptionHandler

from app.core.logs import bot_logger


class PyTeleMonBotError(Exception):
    """General pyTeleMonBot exception occurred."""


class PyTeleMonBotConnectionError(PyTeleMonBotError):
    """Exception raised when an error occurs while connecting to the Telegram"""


class PyTeleMonBotHandlerError(PyTeleMonBotError):
    """Exception raised when an error occurs while handling Telegram"""


class PyTeleMonBotTemplateError(PyTeleMonBotError):
    """Exception raised when an error template not found"""


class DockerAdapterException(PyTeleMonBotError):
    """Exception raised when an error occurs while checking Docker image"""


class TelebotCustomExceptionHandler(ExceptionHandler):
    """Custom exception handler that handles exceptions raised during the execution"""

    def handle(self, exception):
        """
        Handle the exception and log it.

        Args:
            exception (Exception): The exception raised by Telebot.

        Returns:
            bool: True if the exception was handled successfully.

        Logs:
            If the log level is set to DEBUG, logs the exception with the DEBUG level.
            Otherwise, logs the exception with the ERROR level.
        """
        # Check the log level
        if bot_logger.level == 10:
            # Log the exception with the DEBUG level
            bot_logger.debug(f"Failed: {exception}")
        else:
            # Log the exception with the ERROR level
            bot_logger.error(f"Failed: {exception}")

        # Return True to indicate that the exception was handled successfully
        return True
