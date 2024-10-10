import traceback

import docker
import docker.errors

from pytmbot.globals import settings
from pytmbot.logs import bot_logger


class DockerAdapter:
    """Class to handle Docker requests."""

    def __init__(self) -> None:
        """
        Initialize the DockerAdapter.

        Sets the Docker URL from the config and initializes the Docker client as None.

        Returns:
            None
        """
        self.docker_url: str = settings.docker.host[0]
        self.client = None

        if not self.docker_url:
            raise ValueError("Docker URL is not set in the configuration.")

    def __enter__(self) -> docker.DockerClient:
        """
        Enter the runtime context for the Docker client.

        Initializes and returns the Docker client.

        Returns:
            Docker client instance

        Raises:
            Exception: If the Docker client fails to initialize.
        """
        try:
            self.client = docker.DockerClient(base_url=self.docker_url)
            if settings.docker.debug_docker_client:
                bot_logger.debug(f"Docker client initialized with URL: {self.docker_url}")
            return self.client
        except docker.errors.DockerException as err:
            bot_logger.error(f"Failed creating Docker client at {self.docker_url}: {err}")
            raise
        except Exception as err:
            bot_logger.error(f"Unexpected error when initializing Docker client: {err}")
            raise

    def __exit__(self, exc_type: type, exc_val: Exception, exc_tb: traceback) -> None:
        """
        Exit the runtime context for the Docker client.

        Closes the Docker client if it was initialized.

        Args:
            exc_type: The type of exception that occurred.
            exc_val: The value of the exception that occurred.
            exc_tb: The traceback of the exception that occurred.

        Returns:
            None
        """
        if self.client:
            try:
                self.client.close()
                if settings.docker.debug_docker_client:
                    bot_logger.debug("Docker client successfully closed.")
            except docker.errors.DockerException as err:
                bot_logger.error(f"Failed closing Docker client: {err}")
                raise
            except Exception as err:
                bot_logger.error(f"Unexpected error when closing Docker client: {err}")
                raise
