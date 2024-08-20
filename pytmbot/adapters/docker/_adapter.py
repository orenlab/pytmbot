try:
    import docker
except ImportError:
    raise ImportError("Error loading 'docker' package. Install it!")

from pytmbot.globals import config
from pytmbot.logs import bot_logger


class DockerAdapter:
    """Class to handle Docker requests."""

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

    def __enter__(self):
        """
        Enter the runtime context for the Docker client.

        Returns:
            Docker client instance
        """
        try:
            # Initialize the Docker client
            self.client = docker.DockerClient(base_url=self.docker_url)
            bot_logger.debug("Docker client initialized.")
            return self.client
        except Exception as err:
            # Log the error
            bot_logger.error(f"Failed creating Docker client: {err}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context for the Docker client.

        Args:
            exc_type: The type of exception that occurred.
            exc_val: The value of the exception that occurred.
            exc_tb: The traceback of the exception that occurred.

        Returns:
            None
        """
        if self.client is not None:
            try:
                self.client.close()
                bot_logger.debug("Docker client closed.")
            except Exception as err:
                bot_logger.error(f"Failed closing Docker client: {err}")
