#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""


class HandlerManager:
    """Class for storing callback functions and keyword arguments."""

    def __init__(self, callback, **kwargs):
        self.callback = callback
        self.kwargs = kwargs
