#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Callable, Any, Dict, TypeAlias
from typing import final

from loguru import logger

CallbackType: TypeAlias = Callable[..., Any]


class HandlerManager:
    """Class for storing and managing callback functions and keyword arguments."""

    def __init__(self, callback: CallbackType, **kwargs: Any) -> None:
        """
        Initializes the HandlerManager with a callback and keyword arguments.

        Args:
            callback (CallbackType): The callback function to be stored.
            **kwargs (Any): Keyword arguments to be stored with the callback.
        """
        if not callable(callback):
            logger.error(f"Invalid callback provided: {callback}")
            raise ValueError("The 'callback' parameter must be callable.")
        self.callback: CallbackType = callback
        self.kwargs: Dict[str, Any] = kwargs

    def execute(self, **extra_kwargs: Any) -> Any:
        """
        Executes the stored callback function with the stored and additional keyword arguments.

        Args:
            **extra_kwargs (Any): Additional keyword arguments to pass to the callback.

        Returns:
            Any: The result of the callback function execution.
        """
        combined_kwargs = {**self.kwargs, **extra_kwargs}
        logger.debug(
            f"Executing callback {self.callback.__name__} with arguments: {combined_kwargs}"
        )
        return self.callback(**combined_kwargs)

    @final
    def __eq__(self, other: object) -> bool:
        """
        Checks if two HandlerManager instances are equal.

        Args:
            other (object): The other instance to compare with.

        Returns:
            bool: True if both instances are equal, False otherwise.
        """
        if not isinstance(other, HandlerManager):
            return False
        return self.callback == other.callback and self.kwargs == other.kwargs

    def __repr__(self) -> str:
        """
        Returns a string representation of the HandlerManager instance.

        Returns:
            str: The string representation of the instance.
        """
        return (
            f"HandlerManager(callback={self.callback.__name__}, kwargs={self.kwargs})"
        )
