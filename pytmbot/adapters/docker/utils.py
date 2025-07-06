#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from dataclasses import dataclass
from enum import Enum
from time import sleep
from typing import TypeAlias

from pytmbot.adapters.docker.containers_info import get_container_state
from pytmbot.logs import Logger
from pytmbot.models.docker_models import ContainersState

logger = Logger()

ContainerName: TypeAlias = str


class ContainerState(str, Enum):
    RUNNING = "running"
    EXITED = "exited"
    STOPPED = "stopped"

    @classmethod
    def from_str(cls, value: str) -> "ContainerState":
        try:
            return cls(value.lower())
        except ValueError:
            valid_states = [state.value for state in cls]
            raise ValueError(f"State must be one of: {valid_states}")


@dataclass(frozen=True)
class StateCheckConfig:
    max_attempts: int = 3
    interval: float = 1.5


def check_container_state(
    container_name: ContainerName,
    target_state: str = ContainerState.RUNNING,
    config: StateCheckConfig = StateCheckConfig(),
) -> ContainerState | None:
    """
    Checks if container reaches target state within configured attempts.

    Args:
        container_name: Container identifier
        target_state: Desired container state
        config: Check configuration parameters

    Returns:
        Final container state or None on error

    Raises:
        ValueError: If target state is invalid
    """
    try:
        target = ContainerState.from_str(target_state)
        containers_state = ContainersState()

        if target.value not in containers_state.__dict__.values():
            raise ValueError(f"Invalid state: {target}")

        for attempt in range(1, config.max_attempts + 1):
            log_context = {
                "container": container_name,
                "target": target.value,
                "attempt": attempt,
                "max_attempts": config.max_attempts,
            }

            logger.info(
                f"Checking state (attempt {attempt}/{config.max_attempts})",
                extra=log_context,
            )

            try:
                current_state = ContainerState.from_str(
                    get_container_state(container_name)
                )
                log_context["state"] = current_state.value

                if current_state == target:
                    logger.info("Target state reached", extra=log_context)
                    return current_state

                logger.warning(
                    f"State mismatch: {current_state.value}, retrying in {config.interval}s",
                    extra=log_context,
                )
                sleep(config.interval)

            except Exception as e:
                logger.error(
                    "State check failed",
                    extra={
                        **log_context,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                return None

        logger.warning(
            "Failed to reach target state",
            extra={
                "container": container_name,
                "target": target.value,
                "attempts": config.max_attempts,
            },
        )
        return current_state

    except ValueError as e:
        logger.error(
            "Invalid target state",
            extra={"container": container_name, "state": target_state, "error": str(e)},
        )
        raise
