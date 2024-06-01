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

        Args:
            exception (): exception from Telebot

        Returns: True object

        """
        if bot_logger.level == 10:
            if "Bad getaway" in str(exception):
                bot_logger.error('Connection error to Telegram API. Bad getaway. Error code: 502')
            else:
                bot_logger.error(f"Failed: {exception}", exc_info=False)
        else:
            bot_logger.error(f"Failed: {exception}", exc_info=True)
        return True
