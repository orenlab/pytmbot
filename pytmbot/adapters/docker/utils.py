#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time

from pytmbot.adapters.docker.containers_info import get_container_state
from pytmbot.logs import bot_logger
from pytmbot.models.containers_model import ContainersState


def check_container_state(container_name: str, target_state: str = "running") -> str:
    """
    Checks the state of a Docker container.
    target_state: str = "running", "exited", "stopped"

    Args:
        container_name (str): The name of the Docker container to check.
        target_state (str, optional): The target state of the container. Defaults to "running".

    Returns:
        str: The state of the container.
    """

    containers_state = ContainersState()

    if target_state not in containers_state.__dict__.values():
        raise ValueError(f"Target state must be one of {containers_state.__dict__.values()}")
    attempt = 0
    max_attempts = 3
    interval = 1.5
    state = None

    while attempt < max_attempts and state != target_state:
        bot_logger.info(
            f"Checking state of {container_name}: state: {state}. Target state: {target_state}. Attempt {attempt}/{max_attempts}")
        state = get_container_state(container_name)
        attempt += 1
        if state != "running":
            time.sleep(interval)

    return state