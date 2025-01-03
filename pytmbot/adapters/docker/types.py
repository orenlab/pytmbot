from enum import Enum
from typing import TypeAlias, TypedDict

ContainerId: TypeAlias = str | int
DockerResponse: TypeAlias = bool | None


class ContainerAction(str, Enum):
    START = "START"
    STOP = "STOP"
    RESTART = "RESTART"
    RENAME = "RENAME"

    @classmethod
    def from_str(cls, value: str) -> 'ContainerAction':
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError(f"Invalid action: {value}")


class ContainerConfig(TypedDict):
    new_container_name: str | None