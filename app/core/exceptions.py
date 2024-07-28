#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers

This module defines custom exceptions for the PyTeleMonBot application.

"""

from telebot import ExceptionHandler

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
        Handle exceptions raised by Telebot.

        Args:
            exception (Exception): The exception to be handled.

        Returns:
            bool: True if the exception was handled successfully.

        Logs:
            If the log level is set to DEBUG, logs the exception with the DEBUG level.
            Otherwise, logs the exception with the ERROR level.
        """
        # Handle exceptions raised by Telebot.
        log_func = bot_logger.debug if bot_logger.level == 10 else bot_logger.error
        log_func(f"Failed at {self.__class__.__name__}: {exception}")

        return True
