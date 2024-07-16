#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime
from typing import List, Dict, Union

import docker
from docker.errors import NotFound, APIError

from app import config
from app.core.logs import bot_logger
from app.utilities.utilities import set_naturalsize, set_naturaltime


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

    def __list_containers(self) -> List[str]:
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
            client = self.__create_docker_client()

            # Retrieve a list of all running containers and extract their short IDs in one line
            containers_id = [container.short_id for container in client.containers.list(all=True)]

            # Log the created container list
            bot_logger.debug(f"Container list created: {containers_id}")

            # Return the list of short IDs
            return containers_id

        except Exception as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def __get_container_details(self, container_id: str):
        """
        Get the details of a Docker container.

        Args:
            container_id (str): The ID of the container.

        Returns:
            docker.models.containers.Container: The container object.

        Raises:
            ValueError: If the container ID is invalid.
            FileNotFoundError: If the Docker executable is not found.
        """
        # Create a Docker client
        client = self.__create_docker_client()

        try:
            # Check if the container ID is valid
            if not container_id:
                raise ValueError("Invalid container ID")

            # Get the container object
            container_full_info = client.containers.get(container_id)

            # Log the retrieved container details
            bot_logger.debug(f"Retrieved container object for container: {container_id}")

            # Return the container object
            return container_full_info

        except docker.api_errors.NotFound as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

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
                - 'mem_usage' (str): The memory usage of the container.
                - 'run_at' (str): The date and time the container was started.
                - 'status' (str): The status of the container.

        Raises:
            ValueError: If container details retrieval fails.

        """
        try:
            # Retrieve container details
            container_details = self.__get_container_details(container_id)
            attrs = container_details.attrs
            stats = container_details.stats(decode=None, stream=False)

            # Extract creation date and time
            created_at = datetime.fromisoformat(attrs['Created'])
            created_day, created_time = created_at.date(), created_at.time().strftime("%H:%M:%S")

            # Create container details dictionary
            # See: https://github.com/orenlab/pytmbot/issues/55
            container_details = {
                'name': attrs['Name'].strip("/").title(),
                'image': attrs.get('Config', {}).get('Image', 'N/A'),
                'created': f"{created_day}, {created_time}",
                'mem_usage': set_naturalsize(stats.get('memory_stats', {}).get('usage', 0)),
                'run_at': set_naturaltime(datetime.fromisoformat(attrs['State'].get('StartedAt', ''))),
                'status': attrs.get('State', {}).get('Status', 'N/A'),
            }

            return container_details

        except Exception as e:
            # Log error if details retrieval fails
            bot_logger.error(f"Failed at @{__name__}: {e}")
            return {}

    def retrieve_image_details(self) -> Union[List[Dict[str, str]], Dict[None, None]]:
        """
        Retrieve and return details of Docker images.

        Returns:
            Union[List[Dict[str, str]], Dict[None, None]]: A list of image details or an empty dictionary.

        Raises:
            ValueError: If an exception occurs during the retrieval process.
        """
        try:
            # Check if Docker is available
            if not self.__is_docker_available():
                # Log a message if Docker is not available
                bot_logger.debug("Docker is not available. Returning empty dictionary.")
                return {}

            # Retrieve the list of containers
            bot_logger.debug("Retrieving list of containers...")
            containers_id = self.__list_containers()

            # Check if any containers are found
            if not containers_id:
                # Log a message if no containers are found
                bot_logger.debug("No containers found. Returning empty dictionary.")
                return {}

            # Retrieve details for each container
            bot_logger.debug("Retrieving details for each container...")
            details = list(map(self.__aggregate_container_details, containers_id))

            # Log a message indicating successful retrieval of details
            bot_logger.debug(f"Details retrieved successfully: {details}")
            return details

        except Exception as e:
            # Log an error if an exception occurs
            bot_logger.error(f"Failed at {__name__}: {e}")
            return {}

    def get_full_container_details(self, container_id: str):
        """
        Retrieve and return the attributes of a Docker container as a dictionary.

        Args:
            container_id (str): The ID of the container.

        Returns:
            dict: A dictionary containing the attributes of the Docker container.
        """
        try:
            return self.__get_container_details(container_id)
        except NotFound:
            return {}

    def fetch_container_logs(self, container_id: str) -> Union[str, dict]:
        """
        Fetches and returns the logs of a Docker container.

        Args:
            container_id (str): The ID of the container.

        Returns:
            Union[str, dict]: The logs of the Docker container, or an empty dictionary if logs are not found.
        """
        try:
            container_details = self.__get_container_details(container_id)
            logs = container_details.logs(tail=150).decode("utf-8")[-4300:]
            return logs if logs else {}
        except (NotFound, APIError):
            return {}
