#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from pydantic import BaseModel


class ContainersState:
    """Class for container states."""

    running = "running"
    paused = "paused"
    restarting = "restarting"
    stopped = "stopped"
    exited = "exited"
    dead = "dead"
    unknown = "unknown"


class DockerHubTag(BaseModel):
    """Model for DockerHub tags."""

    name: str
    last_pushed: str
