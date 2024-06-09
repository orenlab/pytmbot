#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot import ExceptionHandler

from app.core.logs import bot_logger


class PyTeleMonBotError(Exception):
    """
    Base class for all PyTeleMonBot exceptions.

    Returns:
        None

    Raises:
        None
    """


class PyTeleMonBotConnectionError(PyTeleMonBotError):
    """
    Exception raised when an error occurs while connecting to the server

    Returns:
        None

    Raises:
        None
    """


class PyTeleMonBotHandlerError(PyTeleMonBotError):
    """
    Exception raised when an error occurs while handling a message

    Returns:
        None

    Raises:
        None
    """


class PyTeleMonBotTemplateError(PyTeleMonBotError):
    """
    Exception raised when an error occurs while using a template

    Returns:
        None

    Raises:
        None
    """


class DockerAdapterException(PyTeleMonBotError):
    """
    Exception raised when an error occurs while using Docker

    Returns:
        None

    Raises:
        None
    """


class TelebotCustomExceptionHandler(ExceptionHandler):
    """
    Custom exception handler for Telebot.

    This class overrides the `handle` method of the `ExceptionHandler` class
    and handles exceptions raised by the `Telebot` class.

    Returns:
        bool: True if the exception was handled successfully.

    Logs:
        If the log level is set to DEBUG, logs the exception with the DEBUG level.
        Otherwise, logs the exception with the ERROR level.

    Raises:
        None
    """

    def handle(self, exception: Exception) -> bool:
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
