#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
import argparse
from functools import lru_cache
from typing import Any

from emoji import emojize as em_func


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


@lru_cache
def get_emoji(emoji_name: str) -> str:
    """
    Get the emoji corresponding to the given emoji name.

    Args:
        emoji_name (str): The name of the emoji.

    Returns:
        str: The emoji corresponding to the given emoji name.

    Note:
        This function uses the `emoji` library to convert the emoji name into the actual emoji.
        The `lru_cache` decorator is used to cache the results of this function, so that subsequent calls
        with the same emoji name don't need to recompute the emoji.
    """
    # Construct the emoji string by adding colons around the emoji name
    emoji_str = f":{emoji_name}:"

    # Use the `emojize` function from the `emoji` library to convert the emoji string into the actual emoji
    return em_func(emoji_str)


def round_up_tuple(numbers: tuple) -> dict:
    """
    Round up numbers in a tuple.

    Args:
        numbers (tuple): The numbers to round up.

    Returns:
        dict: A dictionary mapping the index of each number to its rounded value.
    """
    rounded_values = {i: round(num, 2) for i, num in enumerate(numbers)}
    return rounded_values


def find_in_args(args: tuple, target_type: type) -> Any:
    """
    Find the first occurrence of an argument of the specified type in a tuple.

    Args:
        args (tuple): The tuple to search in.
        target_type (type): The type of argument to search for.

    Returns:
        Any: The first occurrence of an argument of the specified type, or None if not found.

    """
    # Iterate over each element in the tuple
    for arg in args:
        # Check if the argument is an instance of the target type
        if isinstance(arg, target_type):
            # Return the first occurrence of the argument
            return arg
    # Return None if the argument is not found
    return None


def find_in_kwargs(kwargs, target_type):
    """Find the first occurrence of an argument of the specified type in the values of a dictionary.

    Args:
        kwargs (dict): The dictionary to search in.
        target_type (type): The type of argument to search for.

    Returns:
        Any: The first occurrence of an argument of the specified type, or None if not found.
    """
    # Iterate over the values of the dictionary
    for value in kwargs.values():
        # Check if the value is an instance of the target type
        if isinstance(value, target_type):
            return value
    # Return None if the argument is not found
    return None
