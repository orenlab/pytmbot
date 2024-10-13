#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import ExceptionHandler

from pytmbot.logs import bot_logger
from pytmbot.utils.utilities import sanitize_exception, parse_cli_args


class PyTMBotError(Exception):
    """
    Base class for all exceptions related to PyTeleMonBot.
    """


class PyTMBotConnectionError(PyTMBotError):
    """
    Exception raised when there is an error connecting to the server.
    """


class PyTMBotErrorHandlerError(PyTMBotError):
    """
    Exception raised when there is an error handling a message.
    """


class PyTMBotErrorTemplateError(PyTMBotError):
    """
    Exception raised when there is an error using a template.
    """


class DockerAdapterException(PyTMBotError):
    """
    Exception raised when there is an error interacting with Docker.
    """


class TelebotCustomExceptionHandler(ExceptionHandler):
    """
    Custom exception handler for handling exceptions raised by Telebot.
    """

    def handle(self, exception: Exception) -> bool:
        """
        Logs and handles exceptions raised by Telebot.

        Args:
            exception (Exception): The exception to handle.

        Returns:
            bool: True if the exception was handled successfully.
        """
        sanitized_exception = sanitize_exception(exception)
        log_level = parse_cli_args().log_level

        if log_level == "DEBUG":
            # Log the full exception trace at the DEBUG level
            bot_logger.opt(exception=exception).debug(f"Exception in @Telebot: {sanitized_exception}")
        else:
            # Log only the short exception message without the trace at INFO or higher levels
            bot_logger.error(f"Exception in @Telebot: {sanitized_exception}")

        return True
