#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
from functools import lru_cache
from emoji import emojize as em_func


# Utility functions


@lru_cache
def get_emoji(emoji_name: str) -> str:
    """
    Return emoji
    @param: emoji_name: str
    @return: str
    """
    return em_func(f":{emoji_name}:")


def format_bytes(size: int) -> str:
    """
    Format size
    @param size: int
    @return: str
    """
    power = 2 ** 10
    n = 0
    power_labels = {0: '', 1: 'k', 2: 'm', 3: 'g', 4: 't'}
    while size > power:
        size /= power
        n += 1
    return_size = round(size, 2)
    return f"{return_size}{power_labels[n]}b"


def split_str(data: str, delimiter: str) -> list[str]:
    """
    Split data into glances API
    @param data: str
    @param delimiter: str
    @return: list[str]
    """
    split_data = data.split(delimiter)
    return split_data


def replace_symbol(data: str) -> list[str]:
    """
    Replace data to symbols
    @param data: str
    @return: str
    """
    replace_data = [item.replace("[", "").replace("]", "").replace('"', "").replace("'", "") for item in data]
    return replace_data


def round_up(n: float) -> float:
    """
    Round up a number
    @param: n- float
    @return: float
    """
    return round(n, 2)


def round_up_tuple(n: tuple) -> dict:
    """
    Round up a number
    @param: n- float
    @return: float
    """
    value: dict = {}
    i = 0
    for tuple_value in n:
        old_value = round(tuple_value, 2)
        value.update({i: old_value})
        i += 1
    return value
