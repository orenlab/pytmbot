#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Union

from docker.errors import APIError, NotFound

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import bot_logger
from pytmbot.utils.utilities import set_naturaltime


def __fetch_containers_list() -> List[str]:
    """
    Retrieves a list of all running containers and returns their short IDs.

    Returns:
        List[str]: A list of short IDs of the running containers.

    Raises:
        FileNotFoundError: If the Docker client cannot be created.
        ConnectionError: If there is an error connecting to the Docker daemon.
    """
    try:
        with DockerAdapter() as adapter:
            bot_logger.debug("Retrieving list of running containers.")
            container_list = adapter.containers.list(all=True)

        return [container.short_id for container in container_list]

    except Exception as e:
        bot_logger.error(f"Failed to list containers: {e}")


def __get_container_attributes(container_id: str):
    """
    Retrieve the details of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        docker.models.containers.Container: The container object.

    Raises:
        ValueError: If the container ID is invalid.
        FileNotFoundError: If the Docker executable is not found.
    """
    if not container_id:
        raise ValueError("Invalid container ID")

    try:
        with DockerAdapter() as adapter:
            bot_logger.debug(f"Retrieving container details for ID: {container_id}.")
            return adapter.containers.get(container_id)
    except Exception as e:
        bot_logger.error(
            f"Failed to retrieve container details for ID: {container_id}. Error: {e}"
        )


def __aggregate_container_details(container_id: str) -> dict:
    """
    Aggregates details of a Docker container into a dictionary.

    Args:
        container_id (str): The ID of the container.

    Returns:
        dict: A dictionary containing the container's name, image, creation time,
              start time, and status.

    Raises:
        ValueError: If container details retrieval fails.
    """
    try:
        start_time = time.time()
        container_details = __get_container_attributes(container_id)
        attrs = container_details.attrs

        created_at = datetime.fromisoformat(attrs["Created"])
        created_day, created_time = created_at.date(), created_at.time().strftime(
            "%H:%M:%S"
        )

        container_context = {
            "name": attrs["Name"].strip("/").title(),
            "image": attrs.get("Config", {}).get("Image", "N/A"),
            "created": f"{created_day}, {created_time}",
            "run_at": (
                set_naturaltime(
                    datetime.fromisoformat(attrs["State"].get("StartedAt", ""))
                )
                if attrs["State"].get("StartedAt", "")
                else "N/A"
            ),
            "status": attrs.get("State", {}).get("Status", "N/A"),
        }

        bot_logger.debug(
            f"Time taken to build container details: {time.time() - start_time:.5f} seconds."
        )

        return container_context

    except Exception as e:
        bot_logger.error(f"Failed at @{__name__}: {e}")
        return {}


def retrieve_containers_stats() -> Union[List[Dict[str, str]], Dict[None, None]]:
    """
    Retrieves and returns details of Docker containers.

    This function checks for Docker availability, lists the containers, and retrieves details
    for each container using parallel processing with a ThreadPool.

    Returns:
        Union[List[Dict[str, str]], Dict[None, None]]: A list of container details or an empty dictionary if none found.

    Raises:
        ValueError: If an exception occurs during the retrieval process.
    """
    try:
        start_time = time.time()

        containers_id = __fetch_containers_list()

        if not containers_id:
            bot_logger.debug("No containers found. Returning empty dictionary.")
            return {}

        with ThreadPoolExecutor() as executor:
            details = list(executor.map(__aggregate_container_details, containers_id))

        bot_logger.debug(f"Returning container details: {details}.")
        bot_logger.debug(
            f"Done retrieving container details in {time.time() - start_time:.5f} seconds."
        )

        return details

    except Exception as e:
        bot_logger.error(f"Failed at {__name__}: {e}")
        return {}


def fetch_full_container_details(container_id: str):
    """
    Retrieves and returns the full attributes of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        dict: A dictionary containing the full attributes of the Docker container.
    """
    try:
        return __get_container_attributes(container_id)
    except NotFound:
        bot_logger.debug(f"Container {container_id} not found.")
        return {}


def fetch_container_logs(container_id: str):
    """
    Fetches and returns the logs of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        Union[str, dict]: The logs of the container as a string, or an empty string if none found.

    Raises:
        NotFound: If the container is not found.
        APIError: If there is an error with the Docker API.
    """
    try:
        container_details = __get_container_attributes(container_id)
        logs = container_details.logs(tail=50, stdout=True, stderr=True)
        cut_logs = logs.decode("utf-8", errors="ignore")[-3800:]
        return cut_logs if cut_logs else ""
    except (NotFound, APIError):
        bot_logger.error(f"Failed to fetch logs for container: {container_id}")
        return ""


def fetch_docker_counters():
    """
    Fetches and returns Docker counters containing the number of images and containers.

    Returns:
        Union[Dict[str, int], None]: A dictionary with 'images_count' and 'containers_count' or None if an error occurs.
    """
    try:
        with DockerAdapter() as adapter:
            images = adapter.images.list()
            containers = adapter.containers.list()

        return {"images_count": len(images), "containers_count": len(containers)}

    except (NotFound, APIError) as e:
        bot_logger.error(f"Failed to fetch Docker counters: {e}")
        return None


def get_container_state(container_id: str):
    """
    Retrieves and returns the status of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        str: The status of the container, or None if an error occurs.
    """
    try:
        with DockerAdapter() as adapter:
            container = adapter.containers.get(container_id)
            return container.status
    except Exception as e:
        bot_logger.error(f"Failed to get container state: {e}")
        return None
