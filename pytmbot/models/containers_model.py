#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""


class ContainersState:
    """Class for container states."""
    running = "running"
    paused = "paused"
    restarting = "restarting"
    stopped = "stopped"