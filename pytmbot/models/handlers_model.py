#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps

from pytmbot.logs import Logger

logger = Logger()

type CallbackType[R] = Callable[..., R]


def log_execution[R](func: CallbackType[R]) -> CallbackType[R]:
    """Decorator to log function execution with its arguments."""

    @wraps(func)
    def wrapper(self: "HandlerManager[R]", **kwargs: object) -> R:
        logger.debug("bot.models.handlers_model.exec.callback.debug")
        return func(self, **kwargs)

    return wrapper


@dataclass(frozen=True, slots=True)
class HandlerManager[R]:
    """
    Class for storing and managing callback functions and keyword arguments.

    Attributes:
        callback (CallbackType[R]): The callback function to be stored
        kwargs (dict[str, object]): Keyword arguments to be stored with the callback
    """

    callback: CallbackType[R]
    kwargs: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the callback after instance creation."""
        if not callable(self.callback):
            logger.error("bot.models.handlers_model.invalid.callback.fail")
            raise ValueError("The 'callback' parameter must be callable")

    @log_execution
    def execute(self, **extra_kwargs: object) -> R:
        """
        Execute the stored callback function with stored and additional keyword arguments.

        Args:
            **extra_kwargs: Additional keyword arguments to pass to the callback

        Returns:
            The result of the callback function execution
        """
        return self.callback(**{**self.kwargs, **extra_kwargs})

    def __repr__(self) -> str:
        """Return a string representation of the HandlerManager instance."""
        return (
            f"{self.__class__.__name__}"
            f"(callback={self.callback.__name__}, kwargs={self.kwargs})"
        )
