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

    def handle(self, ex: Exception) -> bool:
        """
        Log and handle exceptions raised by Telebot.

        Args:
            ex (Exception): The exception to handle.

        Returns:
            bool: True if the exception was handled successfully.
        """
        bot_logger.log(bot_logger.level, f"Failed at Telebot package: {ex}", exc_info=bot_logger.level)

        return True
