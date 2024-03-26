#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
from functools import lru_cache
from emoji import emojize as em_func
from datetime import datetime


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


# Deprecated func
def split_str(data: str, delimiter: str) -> list[str]:
    """
    Split data
    @param data: str
    @param delimiter: str
    @return: list[str]
    """
    split_data = data.split(delimiter)
    return split_data


# Deprecated func
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


def format_datetime(date: str) -> tuple:
    """
    Formate date and time
    @param: date- str in UNIX format
    @return: tuple[date, time]
    """
    date_time = datetime.fromisoformat(date)
    time = date_time.time().strftime("%H:%M:%S")
    return date_time.date(), time


def pretty_date(time=False):
    """
    Get a datetime object or int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now'
    Original code: https://stackoverflow.com/questions/1551382/user-friendly-time-format-in-python
    """
    diff = ''
    now = datetime.fromisoformat(str(datetime.now()))
    if isinstance(time, int):
        diff = now - datetime.fromtimestamp(time)
    elif isinstance(time, datetime):
        diff = now - time
    elif not time:
        diff = 0
    second_diff = diff.seconds
    day_diff = diff.days

    if day_diff < 0:
        return ''

    if day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return str(second_diff) + " secs"
        if second_diff < 120:
            return "a min"
        if second_diff < 3600:
            return str(second_diff // 60) + " mins"
        if second_diff < 7200:
            return "an hour"
        if second_diff < 86400:
            return str(second_diff // 3600) + " hours"
    if day_diff == 1:
        return "yesterday"
    if day_diff < 7:
        return str(day_diff) + " days"
    if day_diff < 31:
        return str(day_diff // 7) + " weeks"
    if day_diff < 365:
        return str(day_diff // 30) + " months"
    return str(day_diff // 365) + " years"
