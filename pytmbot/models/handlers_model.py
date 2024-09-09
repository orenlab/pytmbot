#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Callable, Any, Dict


class HandlerManager:
    """Class for storing and managing callback functions and keyword arguments."""

    def __init__(self, callback: Callable[..., Any], **kwargs: Any) -> None:
        """
        Initializes the HandlerManager with a callback and keyword arguments.

        Args:
            callback (Callable[..., Any]): The callback function to be stored.
            **kwargs (Any): Keyword arguments to be stored with the callback.
        """
        if not callable(callback):
            raise ValueError("The 'callback' parameter must be callable.")
        self.callback: Callable[..., Any] = callback
        self.kwargs: Dict[str, Any] = kwargs

    def execute(self) -> Any:
        """
        Executes the stored callback function with the stored keyword arguments.

        Returns:
            Any: The result of the callback function execution.
        """
        return self.callback(**self.kwargs)

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
