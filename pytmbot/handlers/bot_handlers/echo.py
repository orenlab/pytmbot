#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from pytmbot.globals import get_emoji_converter
from pytmbot.logs import Logger

logger = Logger()
em = get_emoji_converter()


# func=lambda message: True
