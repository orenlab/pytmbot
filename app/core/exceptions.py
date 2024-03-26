#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""


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
