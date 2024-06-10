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
    """Class to adapt docker-py to pyTMbot.

    This class initializes the DockerAdapter with the necessary attributes.
    """

    def __init__(self) -> None:
        """Initialize the DockerAdapter.

        Initializes the DockerAdapter with the necessary attributes.
        """
        # Set the Docker URL from the config
        self.docker_url: str = config.docker_host

        # Initialize the Docker client
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
            # If the client instance is not already initialized, create it
            if self.client is None:
                bot_logger.debug("Client is None. Initializing Docker client instance...")
                self.client = docker.DockerClient(self.docker_url)

            # Log a debug message indicating the success of client creation
            bot_logger.debug("Returning the Docker client instance.")

            # Return the client instance
            return self.client

        # If an error occurs during client creation, log an error message
        except (ConnectionAbortedError, FileNotFoundError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def _is_docker_available(self) -> bool:
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
            return False

    def _list_containers(self) -> List[str]:
        """
        List all docker containers.

        This function creates a Docker client instance and retrieves a list of all running containers.
        It then extracts the image tags from the container list and returns them as a list.

        Returns:
            List[str]: A list of image tags of all running containers.

        Raises:
            FileNotFoundError: If the Docker executable is not found.
            ConnectionError: If there is an error connecting to the Docker daemon.
        """
        try:
            # Create a Docker client instance
            client = self.__create_docker_client()

            # Retrieve a list of all running containers
            containers_raw = client.containers.list()
            bot_logger.debug(f"Raw container list: {containers_raw}")

            # If no containers are found, log a debug message
            if not containers_raw:
                bot_logger.debug('No containers found. Docker is run.')

            # Process the containers and extract the image tags
            image_tag: List[str] = [container.short_id for container in containers_raw]

            # Log the created container list
            bot_logger.debug(f"Container list created: {image_tag}")

            # Return the list of image tags
            return image_tag

        except (FileNotFoundError, ConnectionError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def _container_details(self, container_id: str):
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

            # Log the creation of the Docker client
            bot_logger.debug(f"Created Docker client for container: {container_id}")

            # Get the container object
            container = client.containers.get(container_id)

            # Log the retrieved container details
            bot_logger.debug(f"Retrieved container object: {container}")

            # Return the container object
            return container

        except (ValueError, FileNotFoundError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def _aggregate_container_details(self, container: str) -> dict:
        """
        Get the details of a Docker container.

        Args:
            container (str): The ID of the container.

        Returns:
            dict: A dictionary containing various details of the container.

        Raises:
            ValueError: If there is an issue with retrieving container details.
        """
        # Get the container details
        container_details = self._container_details(container)

        # Get the usage statistics of the container
        usage_stats = container_details.stats(decode=None, stream=False)

        # Extract creation date and time
        created_at = datetime.fromisoformat(container_details.attrs['Created'])
        created_day = created_at.date()
        created_time = created_at.time().strftime("%H:%M:%S")

        # Return a dictionary with container details
        return {
            'name': container_details.attrs['Name'].title().replace('/', ''),
            'image': container_details.attrs['Config']['Image'],
            'created': f'{created_day}, {created_time}',
            'mem_usage': naturalsize(usage_stats['memory_stats']['usage']),
            'run_at': naturaltime(datetime.fromisoformat(container_details.attrs['State']['StartedAt'])),
            'status': container_details.attrs['State']['Status']
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
            if not self._is_docker_available():
                # Log a message if Docker is not available
                bot_logger.debug("Docker is not available. Returning empty dictionary.")
                return {}

            # Retrieve the list of containers
            bot_logger.debug("Retrieving list of containers...")
            containers = self._list_containers()

            if not containers:
                # Log a message if no containers are found
                bot_logger.debug("No containers found. Returning empty dictionary.")
                return {}

            # Retrieve details for each container
            bot_logger.debug("Retrieving details for each container...")
            details = [self._aggregate_container_details(container) for container in containers]

            # Log a message indicating successful retrieval of details
            bot_logger.debug("Details retrieved successfully. Returning list of details.")
            return details

        except ValueError as e:
            # Log an error if an exception occurs
            bot_logger.error(f"Failed at {__name__}: {e}")
            return {}
