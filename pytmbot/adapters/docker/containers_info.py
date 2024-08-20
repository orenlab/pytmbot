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

    # Check if the container ID is valid
    if not container_id:
        raise ValueError("Invalid container ID")

    try:
        with DockerAdapter() as adapter:
            bot_logger.debug(f"Retrieving container details for ID: {container_id}.")
            return adapter.containers.get(container_id)
    except Exception as e:
        # Log the failure to retrieve container details
        bot_logger.error(f"Failed to retrieve container details for ID: {container_id}. Error: {e}")


def __aggregate_container_details(container_id: str) -> dict:
    """
    Retrieve details of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        dict: A dictionary containing container details. The dictionary contains the following keys:
            - 'name' (str): The name of the container.
            - 'image' (str): The image used by the container.
            - 'created' (str): The date and time the container was created.
            - 'run_at' (str): The date and time the container was started.
            - 'status' (str): The status of the container.

    Raises:
        ValueError: If container details retrieval fails.

    """
    try:
        start_time = time.time()
        container_details = __get_container_attributes(container_id)
        attrs = container_details.attrs

        created_at = datetime.fromisoformat(attrs['Created'])
        created_day, created_time = created_at.date(), created_at.time().strftime("%H:%M:%S")

        container_context = {
            'name': attrs['Name'].strip("/").title(),
            'image': attrs.get('Config', {}).get('Image', 'N/A'),
            'created': f"{created_day}, {created_time}",
            'run_at': set_naturaltime(datetime.fromisoformat(attrs['State'].get('StartedAt', ''))),
            'status': attrs.get('State', {}).get('Status', 'N/A'),
        }

        bot_logger.debug(f"Time taken to build container details: {time.time() - start_time:.5f} seconds.")

        return container_context

    except Exception as e:
        bot_logger.error(f"Failed at @{__name__}: {e}")
        return {}


def retrieve_containers_stats() -> Union[List[Dict[str, str]], Dict[None, None]]:
    """
    Retrieve and return details of Docker images.

    This function first checks if Docker is available. If not, it logs a debug message and returns an empty
    dictionary.
    It then lists the containers and retrieves details for each container using ThreadPool for parallel processing.
    The details of each container are aggregated using the __aggregate_container_details method.

    Returns:
        Union[List[Dict[str, str]], Dict[None, None]]: A list of image details or an empty dictionary.

    Raises:
        ValueError: If an exception occurs during the retrieval process.
    """
    try:
        start_time = time.time()  # Start timer for performance measurement

        # List containers
        containers_id = __fetch_containers_list()

        # If no containers found, return empty dictionary
        if not containers_id:
            bot_logger.debug("No containers found. Returning empty dictionary.")
            return {}

        # Retrieve container details for each container using ThreadPool for parallel processing
        with ThreadPoolExecutor() as executor:
            details = list(executor.map(__aggregate_container_details, containers_id))

        bot_logger.debug(f"Returning image details: {details}.")  # Log the details

        finish_time = time.time()  # End timer for performance measurement

        bot_logger.debug(f"Done retrieving image details in {finish_time - start_time:.5f} seconds.")

        return details

    except Exception as e:
        bot_logger.error(f"Failed at {__name__}: {e}")
        return {}


def fetch_full_container_details(container_id: str):
    """
    Retrieve and return the attributes of a Docker container as a dictionary.

    Args:
        container_id (str): The ID of the container.

    Returns:
        dict: A dictionary containing the attributes of the Docker container.
    """
    try:
        return __get_container_attributes(container_id)
    except NotFound:
        bot_logger.debug(f"Container {container_id} not found.")
        return {}


def fetch_container_logs(container_id: str):
    """
    Fetches the logs of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        Union[str, dict]: The logs of the container as a string, or an empty string if
        the container or logs are not found.

    Raises:
        NotFound: If the container is not found.
        APIError: If there is an error with the Docker API.
    """
    try:
        # Retrieve the details of the container
        container_details = __get_container_attributes(container_id)

        # Fetch the logs of the container
        logs = container_details.logs(tail=50, stdout=True, stderr=True)

        # Sanitize the logs by decoding them and taking the last 3000 characters
        cut_logs = logs.decode("utf-8", errors="ignore")[-3800:]

        # Return the sanitized logs if they exist, otherwise return an empty string
        return cut_logs if cut_logs else ""
    except (NotFound, APIError):
        bot_logger.error(f"Failed to fetch logs for container: {container_id}")
        # Return an empty string if the container or logs are not found
        return ""


def fetch_docker_counters():
    """
    Fetches a dictionary of Docker counters containing the number of images and containers.

    Returns:
        Union[Dict[str, int], None]: A dictionary with keys 'images_count' and 'containers_count' containing
        the respective counts, or None if no counters are found or an error occurs.
    """
    try:
        with DockerAdapter() as adapter:
            images = adapter.images.list()
            containers = adapter.containers.list()

        return {"images_count": len(images), "containers_count": len(containers)}

    except (NotFound, APIError) as e:
        # Log an error message if an exception occurs
        bot_logger.error(f"Failed to fetch Docker counters: {e}")

        # Return None if an exception occurs
        return None