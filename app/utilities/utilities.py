#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
import argparse
from functools import lru_cache

from emoji import emojize as em_func


# Utility functions

def parse_cli_args() -> argparse.Namespace:
    """
    Parsing command line arguments

    Returns:
        object: CLI args
    """
    parser = argparse.ArgumentParser(description="PyTMBot CLI")
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        type=str,
        help="PyTMBot mode (dev or prod)",
        default="prod")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "ERROR"],
        type=str,
        help="Log level",
        default="CRITICAL")
    return parser.parse_args()


@lru_cache
def get_emoji(emoji_name: str) -> str:
    """
    Emoji for handlers

    Args:
        emoji_name (): str

    Returns:
        object: Emoji
    """
    return em_func(f":{emoji_name}:")


def round_up_tuple(n: tuple) -> dict:
    """
    Round up a number in tuple

    Args:
        n (): Number

    Returns: Dict

    """
    value: dict = {}
    i = 0
    for tuple_value in n:
        old_value = round(tuple_value, 2)
        value.update({i: old_value})
        i += 1
    return value


def find_in_args(args, target_type):
    """
    Find args in args tuple

    Args:
        args (): tuple[Any | None]
        target_type (): dict

    Returns: Arg: Any

    """
    for arg in args:
        if isinstance(arg, target_type):
            return arg


def find_in_kwargs(kwargs, target_type):
    """Find kwargs in kwargs dictionary

        Args:
        args (): tuple[Any | None]
        target_type (): dict

    Returns: Arg: Any
    """
    return find_in_args(kwargs.values(), target_type)
