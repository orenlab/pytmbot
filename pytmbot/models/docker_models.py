#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from enum import Enum
from typing import Dict, TypeAlias, TypedDict, Optional

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


class TagInfo(BaseModel):
    """Model for Docker tag information.

    Attributes:
        name (str): The name of the tag.
        created_at (str): The creation date of the tag in ISO 8601 format.
    """

    name: str
    created_at: str  # ISO 8601 date format
    digest: Optional[str]


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

    def to_dict(self) -> Dict[str, str]:
        """Converts UpdateInfo to a dictionary.

        Returns:
            Dict[str, str]: Dictionary representation of the UpdateInfo instance.
        """
        return self.model_dump()  # Convert UpdateInfo to a dictionary


ContainerId: TypeAlias = str | int
DockerResponse: TypeAlias = bool | None


class ContainerAction(str, Enum):
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


class ContainerConfig(TypedDict):
    new_container_name: str | None
