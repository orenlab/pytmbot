#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import argparse
from datetime import datetime
from functools import cached_property
from typing import Any

from humanize import naturalsize, naturaltime
from telebot.types import CallbackQuery, Message


# Utility functions

def parse_cli_args() -> argparse.Namespace:
    """
    Parses command line arguments.

    This function uses the `argparse` module to define and parse command line arguments.
    It has two optional arguments: `--mode` and `--log-level`.

    Returns:
        argparse.Namespace: The parsed command line arguments.

    """
    # Create an ArgumentParser object
    parser = argparse.ArgumentParser(description="PyTMBot CLI")

    # Add the '--mode' argument
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],  # Only 'dev' and 'prod' are valid choices
        type=str,  # The argument should be a string
        help="PyTMBot mode (dev or prod)",  # Help message for the argument
        default="prod"  # Default value for the argument
    )

    # Add the '--log-level' argument
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "ERROR"],  # Only 'DEBUG', 'INFO', and 'ERROR' are valid choices
        type=str,  # The argument should be a string
        help="Log level",  # Help message for the argument
        default="INFO"  # Default value for the argument
    )

    # Parse the command line arguments
    return parser.parse_args()


def round_up_tuple(numbers: tuple) -> dict:
    """
    Round up numbers in a tuple.

    Args:
        numbers (tuple): The numbers to round up.

    Returns:
        dict: A dictionary mapping the index of each number to its rounded value.

    This function takes in a tuple of numbers and rounds each number to two decimal places. It then returns a dictionary
    where the keys are the indices of the input numbers and the values are the rounded numbers.

    Example:
        >>> round_up_tuple((1.2345, 2.3456, 3.4567))
        {0: 1.23, 1: 2.35, 2: 3.46}
    """
    # Use a dictionary comprehension to round each number in the input tuple and map the index to the rounded number
    return {i: round(num, 2) for i, num in enumerate(numbers)}


def find_in_args(args: tuple, target_type: type) -> Any:
    """
    Find the first occurrence of an argument of the specified type in a tuple.

    Args:
        args (tuple): The tuple to search in.
        target_type (type): The type of argument to search for.

    Returns:
        Any: The first occurrence of an argument of the specified type, or None if not found.

    """
    # Filter the elements of the tuple based on type
    found_args = [arg for arg in args if isinstance(arg, target_type)]

    # Return the first element of the filtered list, or None if the list is empty
    return found_args[0] if found_args else None


def find_in_kwargs(kwargs, target_type):
    """
    Find the first occurrence of an argument of the specified type in the values of a dictionary.

    Args:
        kwargs (dict): The dictionary to search in.
        target_type (type): The type of argument to search for.

    Returns:
        Any: The first occurrence of an argument of the specified type, or None if not found.
    """
    # Use a generator expression to filter values of the dictionary
    # based on whether they are an instance of the target type
    # The `next` function is used to get the first value that matches the condition
    # If no value is found, `None` is returned
    found_value = next((value for value in kwargs.values() if isinstance(value, target_type)), None)

    return found_value


def set_naturalsize(size: int) -> str:
    """
    A function that converts a size in bytes to a human-readable format.

    Args:
        size (int): The size in bytes.

    Returns:
        str: The size in a human-readable format.
    """
    return naturalsize(size, binary=True)


def set_naturaltime(timestamp: datetime) -> str:
    """
    Convert a timestamp to a human-readable format.

    Args:
        timestamp (datetime): The timestamp to convert.

    Returns:
        str: The timestamp in a human-readable format.
    """
    return naturaltime(timestamp)


class EmojiConverter:
    """
    A class to convert emoji names to emoji characters.

    Methods:
        get_emoji(self, emoji_name: str)
    """

    @cached_property
    def emoji_library(self):
        """
        Returns the emoji library module.

        The emoji library is imported using the `__import__` function.

        Returns:
            module: The emoji library module.
        """
        return __import__('emoji')

    def get_emoji(self, emoji_name: str) -> str:
        """
        Get the emoji corresponding to the given emoji name.

        Args:
            emoji_name (str): The name of the emoji to retrieve.

        Returns:
            str: The emoji character corresponding to the given emoji name.
        """
        # Construct the emoji string using the emoji name
        emoji_str = f":{emoji_name}:"

        # Use the emoji library to convert the emoji string to the corresponding emoji character
        return self.emoji_library.emojize(emoji_str)


def extract_container_name(data: str, prefix: str) -> str:
    """
    Extracts the container name from data based on the provided prefix.

    Args:
        data (str): The data containing the container name.
        prefix (str): The prefix to identify the container name.

    Returns:
        str: The extracted container name in lowercase.

    This function splits the data string at the prefix and extracts the container name.
    The extracted name is then converted to lowercase and returned.
    """
    # Split the data at the prefix and extract the second element
    container_name = data.split(prefix)[1]

    # Convert the extracted name to lowercase
    container_name = container_name.lower()

    return container_name


def sanitize_logs(container_logs: str, callback_query: CallbackQuery, token: str) -> str:
    """
    Sanitizes the logs of a Docker container by replacing sensitive user information with asterisks.

    Args:
        container_logs (str): The logs of the container.
        callback_query (CallbackQuery): The message object.
        token (str): The token of the bot.

    Returns:
        str: The sanitized logs.
    """
    # Extract user information from the callback query and the token
    user_info = [
        str(callback_query.from_user.username),
        str(callback_query.from_user.first_name),
        str(callback_query.from_user.last_name),
        str(callback_query.message.from_user.id),
        token
    ]

    # Replace each user information with asterisks
    for value in user_info:
        container_logs = container_logs.replace(value, '*' * len(value))

    return container_logs


def get_message_full_info(*args, **kwargs):
    """
    Get full info for inline handlers logs.

    Args:
        *args (): Any
        **kwargs (): Any

    Returns:
        Tuple[Union[str, None], Union[int, None], Union[str, None], Union[bool, None], Union[str, None]]:
            Objects to write to the logs. Returns a tuple containing the username, user ID, language code,
            is_bot flag, and text of the message. If the message is not found in args or kwargs, returns
            "None" for all values.
    """

    message = find_in_args(args, Message) or find_in_kwargs(kwargs, Message)
    if message is not None:
        user = message.from_user
        return (
            user.username,
            user.id,
            user.language_code,
            user.is_bot,
            message.text
        )

    return "None", "None", "None", "None", "None"


def get_inline_message_full_info(*args, **kwargs):
    """
    Get full info for inline handlers logs.

    Args:
        *args (Any): Variable length argument list.
        **kwargs (Any): Arbitrary keyword arguments.

    Returns:
        Tuple[Union[str, None], Union[int, None], Union[bool, None]]:
            A tuple containing the username, user ID, and is_bot flag of the message sender.
            If the message is not found in args or kwargs, returns "None" for all values.
    """
    # Find message in args or kwargs
    message = find_in_args(args, CallbackQuery) or find_in_kwargs(kwargs, CallbackQuery)

    if message is not None:
        user = message.message.from_user
        return user.username, user.id, user.is_bot

    return "None", "None", "None"
