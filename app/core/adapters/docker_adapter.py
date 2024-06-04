#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime
from functools import lru_cache

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

    @lru_cache(maxsize=None)
    def _create_docker_client(self) -> docker.DockerClient:
        """
        Creates a Docker client instance.

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
            # Create the Docker client instance using the Docker URL specified in the config
            self.client = docker.DockerClient(self.docker_url)

            # Log a debug message indicating that the Docker client was created successfully
            bot_logger.debug("Created docker client success")

            # Return the Docker client instance
            return self.client

        except (ConnectionAbortedError, FileNotFoundError) as e:
            # Log an error message indicating that an error occurred while creating the Docker client
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
            # Create a Docker client instance
            client = self._create_docker_client()

            # Ping the Docker daemon
            ping = client.ping()

            # Log a debug message indicating the Docker availability
            bot_logger.debug(f"Docker alive: {ping}")

            # Return the Docker availability
            return ping

        except (ConnectionAbortedError, FileNotFoundError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

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

            # If no containers are found, log a debug message
            if containers_raw == '[]':
                bot_logger.debug('No containers found. Docker is run.')
            else:
                # Extract the image tags from the container list
                image_tag = []
                for container in containers_raw.split(', '):
                    image_tag.append(
                        container.split(': ')[1].strip().split('>')[0].strip()
                    )

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

            # Get the container object
            container = client.containers.get(container_id)

            # Log the retrieved container details
            bot_logger.debug(f"Container details retrieved: {container}")

            # Return the container object
            return container

        except (ValueError, FileNotFoundError) as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    @staticmethod
    def _container_stats(container_details) -> dict:
        """
        Get docker container stats.

        Args:
            container_details (docker.models.containers.Container): The container object.

        Returns:
            dict: The usage statistics of the container.

        Raises:
            docker.errors.APIError: If there is an error retrieving the container stats.
        """
        # Retrieve the usage statistics of the container
        usage_stats = container_details.stats(decode=None, stream=False)

        # Log the generated container stats
        bot_logger.debug(f"Container stats generated: {usage_stats}")

        # Return the usage statistics of the container
        return usage_stats

    def check_image_details(self):
        """
        Check the details of Docker images.

        This function checks the details of Docker images by retrieving the list of containers,
        their details, and their usage statistics. If the Docker socket is available, it returns
        a list of dictionaries containing the name, image, creation date and time, memory usage,
        run time, and status of each container. If no containers are found, it returns an empty
        dictionary. If the Docker socket is not available, it returns an empty dictionary and logs
        an error message.

        Returns:
            list: A list of dictionaries containing the details of each Docker image.
        """
        try:
            # Check if the Docker socket is available
            if self._is_docker_available():
                # Get the list of containers
                self.containers = self._containers_list()
                details = []
                if self.containers:
                    # Iterate over each container
                    for container in self.containers:
                        # Get the details of the container
                        container_details = self._container_details(container)
                        # Get the usage statistics of the container
                        usage_stats = self._container_stats(container_details)
                        # Extract the creation date and time from the container details
                        created_day = datetime.fromisoformat(container_details.attrs['Created']).date()
                        created_time = datetime.fromisoformat(
                            container_details.attrs['Created']
                        ).time().strftime("%H:%M:%S")
                        # Append the container details to the list
                        details.append(
                            {
                                'name': container_details.attrs['Name'].title().replace('/', ''),
                                'image': container_details.attrs['Config']['Image'],
                                'created': f'{created_day}, {created_time}',
                                'mem_usage': naturalsize(usage_stats['memory_stats']['usage']),
                                'run_at': naturaltime(
                                    datetime.fromisoformat(
                                        container_details.attrs['State']['StartedAt']
                                    )
                                ),
                                'status': container_details.attrs['State']['Status']
                            }
                        )
                    # Log the generated container details
                    bot_logger.debug(f"Container image details append: {details}")
                    return details
                else:
                    # Log a message if no containers are found
                    bot_logger.debug('Docker image not found: see "docker ps" command')
                    return {}
            else:
                # Log an error message if the Docker socket is not available
                bot_logger.error('Docker socket not found. Check docker URL')
                return {}
        except ValueError as e:
            # Log an error message if an exception occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")
