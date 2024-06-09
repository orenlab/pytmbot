#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
import argparse
from functools import cached_property
from typing import Any


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
