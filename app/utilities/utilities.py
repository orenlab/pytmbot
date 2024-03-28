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


def split_str(data: str, delimiter: str) -> list[str]:
    """
    Split data
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


def round_up_tuple(n: tuple) -> dict:
    """
    Round up a number in tuple
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
