#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime
from typing import List, Dict, Union

import docker
from humanize import naturalsize, naturaltime

from app import config
from app.core.logs import bot_logger


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
        except (ConnectionAbortedError, FileNotFoundError) as e:
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

        except (ConnectionAbortedError, FileNotFoundError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    @staticmethod
    def _naturalsize(size: int) -> str:
        """
        Convert a size in bytes to a human-readable format.

        Args:
            size (int): The size in bytes.

        Returns:
            str: The size in a human-readable format.
        """
        return naturalsize(size, binary=True)

    @staticmethod
    def _naturaltime(timestamp: datetime) -> str:
        """
        Convert a timestamp to a human-readable format.

        Args:
            timestamp (datetime): The timestamp to convert.

        Returns:
            str: The timestamp in a human-readable format.
        """
        return naturaltime(timestamp)

    def __list_containers(self) -> List[str]:
        """
        List all docker containers.

        This function retrieves a list of all running containers and returns their image tags.

        Returns:
            List[str]: A list of image tags of all running containers.

        Raises:
            FileNotFoundError: If the Docker executable is not found.
            ConnectionError: If there is an error connecting to the Docker daemon.
        """
        try:
            # Create a Docker client instance
            client = self.__create_docker_client()

            # Retrieve a list of all running containers and extract the image tags
            containers_raw = client.containers.list(all=True)
            image_tags = [container.short_id for container in containers_raw]

            # Log the created container list
            bot_logger.debug(f"Container list created: {image_tags}")

            # Return the list of image tags
            return image_tags

        except (FileNotFoundError, ConnectionError) as e:
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
        try:
            # Create a Docker client
            client = self.__create_docker_client()

            # Get the container object
            container = client.containers.get(container_id)

            # Log the retrieved container details
            bot_logger.debug(f"Retrieved container object for container: {container_id}")

            # Return the container object
            return container

        except (ValueError, FileNotFoundError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def __aggregate_container_details(self, container_id: str) -> dict:
        """
        Retrieve details of a Docker container.

        Args:
            container_id (str): The ID of the container.

        Returns:
            dict: A dictionary containing container details.

        Raises:
            ValueError: If container details retrieval fails.

        """
        # Get the container details
        container_details = self.__get_container_details(container_id)

        # Extract the attributes and stats from the container details
        attrs = container_details.attrs
        stats = container_details.stats(decode=None, stream=False)

        # Convert the 'Created' attribute to a datetime object
        created_at = datetime.fromisoformat(attrs['Created'])

        # Extract the day and time from the datetime object
        created_day, created_time = created_at.date(), created_at.time().strftime("%H:%M:%S")

        # Return a dictionary containing the container details
        return {
            'name': attrs['Name'].title().replace('/', ''),
            'image': attrs['Config']['Image'],
            'created': f'{created_day}, {created_time}',
            'mem_usage': self._naturalsize(stats['memory_stats']['usage']),
            'run_at': self._naturaltime(datetime.fromisoformat(attrs['State']['StartedAt'])),
            'status': attrs['State']['Status'],
        }

    def retrieve_image_details(self) -> Union[List[Dict[str, str]], Dict[None, None]]:
        """
        Retrieve and return details of Docker images.

        Returns:
            Union[List[Dict[str, str]], Dict[None, None]]: A list of image details or an empty dictionary.

        Raises:
            ValueError: If an exception occurs during the retrieval process.
        """
        try:
            if not self.__is_docker_available():
                # Log a message if Docker is not available
                bot_logger.debug("Docker is not available. Returning empty dictionary.")
                return {}

            # Retrieve the list of containers
            bot_logger.debug("Retrieving list of containers...")
            containers = self.__list_containers()

            if not containers:
                # Log a message if no containers are found
                bot_logger.debug("No containers found. Returning empty dictionary.")
                return {}

            # Retrieve details for each container
            bot_logger.debug("Retrieving details for each container...")
            details = [self.__aggregate_container_details(container) for container in containers]

            # Log a message indicating successful retrieval of details
            bot_logger.debug(f"Details retrieved successfully: {details}")
            return details

        except ValueError as e:
            # Log an error if an exception occurs
            bot_logger.error(f"Failed at {__name__}: {e}")
            return {}
