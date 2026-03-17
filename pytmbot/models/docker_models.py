#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from enum import StrEnum

from pydantic import BaseModel


class ContainersState(StrEnum):
    """Container states with enum semantics for safer matching and typing."""

    running = "running"
    paused = "paused"
    restarting = "restarting"
    stopped = "stopped"
    exited = "exited"
    dead = "dead"
    unknown = "unknown"


class TagInfo(BaseModel):
    """Model for Docker tag information.

    Attributes:
        name (str): The name of the tag.
        created_at (str): The creation date of the tag in ISO 8601 format.
    """

    name: str
    created_at: str  # ISO 8601 date format
    digest: str | None = None


class UpdateInfo(BaseModel):
    """Model for update information between local and remote tags.

    Attributes:
        current_tag (str): The local tag of the image.
        newer_tag (str): The remote tag that is considered newer.
        created_at_local (str): The creation date of the local tag.
        created_at_remote (str): The creation date of the remote tag.
    """

    current_tag: str
    newer_tag: str
    created_at_local: str
    created_at_remote: str
    current_digest: str


type ContainerId = str | int
type DockerResponse = bool | None


class ContainerAction(StrEnum):
    START = "START"
    STOP = "STOP"
    RESTART = "RESTART"
    RENAME = "RENAME"

    @classmethod
    def from_str(cls, value: str) -> "ContainerAction":
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError(f"Invalid action: {value}")
