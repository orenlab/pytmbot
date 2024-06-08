#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime
from typing import List, Dict

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

        # Initialize the registry digest
        self.registry_digest: None = None

        # Initialize the local image digest
        self.local_image_digest: None = None

        # Initialize the list of containers
        self.containers: None = None

        # Initialize the container
        self.container: None = None

    def _create_docker_client(self) -> docker.DockerClient:
        """
        Creates a Docker client instance if it doesn't exist.

        This method creates a Docker client instance using the Docker URL specified in the config.
        The client is cached using the `lru_cache` decorator, so subsequent calls to this method
        with the same arguments will return the cached client instance.

        Returns:
            docker.DockerClient: The Docker client instance.

        Raises:
            ConnectionAbortedError: If the connection to the Docker daemon is aborted.
            FileNotFoundError: If the Docker executable is not found.

        """
        try:
            # Log a debug message indicating the start of client creation
            bot_logger.debug("Creating Docker client instance...")

            # If the client instance is not already initialized, create it
            if self.client is None:
                bot_logger.debug("Client is None. Initializing Docker client instance...")
                self.client = docker.DockerClient(self.docker_url)

            # Log a debug message indicating the success of client creation
            bot_logger.debug("Success! Returning the Docker client instance.")

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
            return self._create_docker_client().ping()

        except (ConnectionAbortedError, FileNotFoundError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")
            return False

    def _containers_list(self):
        """
        List all docker containers.

        This function creates a Docker client instance and retrieves a list of all running containers.
        It then extracts the image tags from the container list and returns them as a list.

        Returns:
            list: A list of image tags of all running containers.

        Raises:
            FileNotFoundError: If the Docker executable is not found.
            ConnectionError: If there is an error connecting to the Docker daemon.
        """
        try:
            # Create a Docker client instance
            client = self._create_docker_client()

            # Retrieve a list of all running containers
            containers_raw = repr(client.containers.list())
            print(f"Raw container list: {containers_raw}")

            # If no containers are found, log a debug message
            if not containers_raw:
                bot_logger.debug('No containers found. Docker is run.')

            # Extract the image tags from the container list
            image_tag = []
            for container in containers_raw.split(', '):
                bot_logger.debug(f"Processing container: {container}")
                image_tag.append(
                    container.split(': ')[1].strip().split('>')[0].strip()
                )
                bot_logger.debug(f"Extracted image tag: {image_tag[-1]}")

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
            client = self._create_docker_client()

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

    @staticmethod
    def _container_stats(container_details) -> dict:
        """
        Retrieve the usage statistics of the specified Docker container.

        Args:
            container_details (docker.models.containers.Container): The container object.

        Returns:
            dict: A dictionary containing the usage statistics of the container.

        Raises:
            docker.errors.APIError: If there is an error while retrieving the container statistics.
        """
        # Log a message for debugging to indicate that container stats are being retrieved
        bot_logger.debug(f"Retrieving container stats for: {container_details.name}")

        # Retrieve the usage statistics of the container
        usage_stats = container_details.stats(decode=None, stream=False)

        # Log a message for debugging to indicate that usage stats have been successfully retrieved
        bot_logger.debug(f"Usage stats retrieved: {usage_stats}")

        # Return the retrieved usage statistics of the container
        return usage_stats

    def check_image_details(self) -> List[Dict[str, str]] | Dict[None, None]:
        """
        Check the details of Docker images and retrieve usage statistics.

        Retrieves the list of containers and their details. Returns a list of dictionaries containing the following
        details for each container:
        - 'name': The title-cased name of the container.
        - 'image': The image of the container.
        - 'created': The creation date and time of the container.
        - 'mem_usage': The memory usage of the container.
        - 'run_at': The run time of the container.
        - 'status': The status of the container.

        Returns:
            List[Dict[str, str]] | Dict[None, None]: A list of dictionaries containing the details of each Docker
            container, or a dictionary with an empty key if Docker is not available or there are no container.
        """
        try:
            # Check if Docker is available
            if not self._is_docker_available():
                # Log an error message and return an empty dictionary
                bot_logger.error("Docker is not available")
                return {}

            # Retrieve the list of containers
            containers = self._containers_list()
            if not containers:
                # Log an error message and return an empty dictionary
                bot_logger.error("No containers found")
                return {}

            details = []
            for container in containers:
                # Retrieve the details of the container
                container_details = self._container_details(container)

                # Retrieve the usage statistics of the container
                usage_stats = self._container_stats(container_details)

                # Extract the creation date and time from the container details
                created_at = datetime.fromisoformat(container_details.attrs['Created'])
                created_day = created_at.date()
                created_time = created_at.time().strftime("%H:%M:%S")

                # Append the container details to the list
                details.append({
                    'name': container_details.attrs['Name'].title().replace('/', ''),
                    'image': container_details.attrs['Config']['Image'],
                    'created': f'{created_day}, {created_time}',
                    'mem_usage': naturalsize(usage_stats['memory_stats']['usage']),
                    'run_at': naturaltime(
                        datetime.fromisoformat(
                            container_details.attrs['State']['StartedAt']
                        )),
                    'status': container_details.attrs['State']['Status']
                })

            # Log a debug message and return the generated container details
            bot_logger.debug("Generated container details successfully")
            return details

        except ValueError as e:
            # Log an error message and return an empty dictionary
            bot_logger.error(f"Failed at {__name__}: {e}")
            return {}
