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


class DockerImageUpdateCheckerException(PyTeleMonBotError):
    """Exception raised when an error occurs while checking Docker image"""


class GlancesError(Exception):
    """General GlancesApiError exception occurred."""


class GlancesApiConnectionError(GlancesError):
    """When a connection error is encountered."""


class GlancesApiAuthorizationError(GlancesError):
    """When a connection error is encountered."""


class GlancesApiNoDataAvailable(GlancesError):
    """When no data is available."""
