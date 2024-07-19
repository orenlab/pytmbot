#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import time
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Union, Optional, Any

import docker
from docker.errors import NotFound, APIError

from app import config
from app.core.logs import bot_logger
from app.utilities.utilities import (
    set_naturalsize,
    set_naturaltime
)


class DockerAdapter:
    """Class to adapt docker-py to pyTMbot."""

    def __init__(self) -> None:
        """
        Initialize the DockerCustomClient.

        This method sets the Docker URL from the config and initializes the Docker client.

        Returns:
            None
        """
        # The Docker URL is obtained from the config module
        self.docker_url: str = config.docker_host

        # The Docker client is initialized as None
        self.client = None

    def __create_docker_client(self) -> docker.DockerClient:
        """
        Create and return a Docker client instance.

        This function initializes the Docker client if it hasn't been initialized yet.
        It logs debug messages at the start and end of the client creation process.

        Returns:
            docker.DockerClient: The Docker client instance.

        Raises:
            ConnectionAbortedError: If an error occurs during client creation.
            FileNotFoundError: If the Docker executable is not found.
        """
        try:
            # Check if the Docker client instance is not already initialized
            if self.client is None:
                # Log a debug message indicating the start of client creation
                bot_logger.debug("Initializing Docker client instance...")

                # Create the Docker client instance
                self.client = docker.DockerClient(self.docker_url)

                # Log a debug message indicating the success of client creation
                bot_logger.debug("Returning the Docker client instance.")

            # Return the client instance
            return self.client

        # If an error occurs during client creation, log an error message
        except Exception as e:
            # Log an error message with the exception details
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def __is_docker_available(self) -> bool:
        """
        Check if the Docker socket is available.

        This function creates a Docker client instance and pings the Docker daemon.
        If the ping is successful, it returns True. Otherwise, it returns False.

        Returns:
            bool: True if the Docker socket is available, False otherwise.
        """
        try:
            # Ping the Docker daemon and return the result
            return self.__create_docker_client().ping()

        except Exception as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def __fetch_containers_list(self) -> List[str]:
        """
        Retrieves a list of all running containers and returns their short IDs.

        Returns:
            List[str]: A list of short IDs of the running containers.

        Raises:
            FileNotFoundError: If the Docker client cannot be created.
            ConnectionError: If there is an error connecting to the Docker daemon.
        """
        try:
            # Create a Docker client instance
            docker_client = self.__create_docker_client()

            # Retrieve a list of running containers' short IDs
            list_containers = [container.short_id for container in docker_client.containers.list(all=True)]

            return list_containers

        except Exception as e:
            # Log an error message if listing containers fails
            bot_logger.error(f"Failed to list containers: {e}")

    def __get_container_attributes(self, container_id: str):
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
        # Create a Docker client
        docker_client = self.__create_docker_client()

        try:
            # Check if the container ID is valid
            if not container_id:
                raise ValueError("Invalid container ID")

            # Retrieve the container details
            container = docker_client.containers.get(container_id)

            # Log the successful retrieval of container details
            bot_logger.debug(f"Retrieved container details for ID: {container_id}.")

            # Return the container object
            return container

        except NotFound as e:
            # Log the failure to retrieve container details
            bot_logger.error(f"Failed to retrieve container details for ID: {container_id}. Error: {e}")

    def __aggregate_container_details(self, container_id: str) -> dict:
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
            container_details = self.__get_container_attributes(container_id)
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

    def retrieve_containers_stats(self) -> Union[List[Dict[str, str]], Dict[None, None]]:
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

            # Check if Docker is available
            if not self.__is_docker_available():
                bot_logger.debug("Docker is not available. Returning empty dictionary.")
                return {}

            # List containers
            containers_id = self.__fetch_containers_list()

            # If no containers found, return empty dictionary
            if not containers_id:
                bot_logger.debug("No containers found. Returning empty dictionary.")
                return {}

            # Retrieve container details for each container using ThreadPool for parallel processing
            with ThreadPoolExecutor() as executor:
                details = list(executor.map(self.__aggregate_container_details, containers_id))

            bot_logger.debug(f"Returning image details: {details}.")  # Log the details

            finish_time = time.time()  # End timer for performance measurement

            bot_logger.debug(f"Done retrieving image details in {finish_time - start_time:.5f} seconds.")

            return details

        except Exception as e:
            # Log error if details retrieval fails
            bot_logger.error(f"Failed at {__name__}: {e}")
            return {}

    def fetch_full_container_details(self, container_id: str):
        """
        Retrieve and return the attributes of a Docker container as a dictionary.

        Args:
            container_id (str): The ID of the container.

        Returns:
            dict: A dictionary containing the attributes of the Docker container.
        """
        try:
            return self.__get_container_attributes(container_id)
        except NotFound:
            bot_logger.debug(f"Container {container_id} not found.")
            return {}

    def fetch_container_logs(self, container_id: str) -> Union[str, dict]:
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
            container_details = self.__get_container_attributes(container_id)

            # Fetch the logs of the container
            logs = container_details.logs(tail=50, stdout=True, stderr=True)

            # Sanitize the logs by decoding them and taking the last 3000 characters
            cut_logs = logs.decode("utf-8", errors="ignore")[-3000:]

            # Return the sanitized logs if they exist, otherwise return an empty string
            return cut_logs if cut_logs else ""
        except (NotFound, APIError):
            bot_logger.error(f"Failed to fetch logs for container: {container_id}")
            # Return an empty string if the container or logs are not found
            return ""

    def fetch_registry_data(self, image_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the registry data for a given image.

        Args:
            image_name (str): The name of the image to fetch registry data for.

        Returns:
            Optional[Dict[str, Any]]: The registry data as a dictionary, or None if the data is not found.
        """
        docker_client = self.__create_docker_client()
        try:
            return docker_client.images.get_registry_data(image_name)
        except (NotFound, APIError) as e:
            bot_logger.error(f"Failed to fetch registry data for image: {image_name}: {e}")
            return None

    def fetch_docker_counters(self) -> Union[Dict[str, int], None]:
        """
        Fetches a dictionary of Docker counters containing the number of images and containers.

        Returns:
            Union[Dict[str, int], None]: A dictionary with keys 'images_count' and 'containers_count' containing
            the respective counts, or None if no counters are found or an error occurs.
        """
        try:
            client = self.__create_docker_client()
            # Fetch the number of Docker images and containers in one call
            images = client.images.list()
            containers = client.containers.list()

            # Return a dictionary with the counts
            return {"images_count": len(images), "containers_count": len(containers)}

        except (NotFound, APIError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed to fetch Docker counters: {e}")

            # Return None if an exception occurs
            return None

    def fetch_image_details(self):
        try:
            docker_client = self.__create_docker_client()
            images = docker_client.images.list(all=True)

            image_details = [
                {
                    'id': image.short_id,
                    'name': image.attrs.get('RepoTags', "N/A"),
                    'tags': image.tags or "N/A",
                    'architecture': image.attrs.get('Architecture', "N/A"),
                    'os': image.attrs.get('Os', "N/A"),
                    'size': set_naturalsize(image.attrs.get('Size', 0)),
                    'created': set_naturaltime(datetime.fromisoformat(image.attrs.get('Created'))) or "N/A",
                }
                for image in images
            ]

            return image_details

        except Exception as e:
            bot_logger.error(f"Failed to fetch image details: {e}")
            return None
