#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from podman import PodmanClient


class PodmanAdapter:
    """
    Class to adapt podman-py to pyTMbot.

    This class initializes a PodmanClient instance with a specified URI.
    """

    def __init__(self):
        """
        Initialize the PodmanAdapter class.

        This method initializes the PodmanAdapter instance with a URI and creates
        a PodmanClient instance with that URI.
        """
        # Set the URI for the PodmanClient instance
        self.uri = "unix:///run/user/1000/podman/podman.sock"

        # Create a PodmanClient instance with the specified URI
        self.client = PodmanClient(base_url=self.uri)

    def get_podman_version(self):
        """
        Get the version of the Podman client.

        Returns:
            str: The version of the Podman client.
        """
        # Get the version of the Podman client using the client instance
        return self.client.version()

    def ping_podman(self) -> bool:
        """
        Ping the Podman client to check if it is available.

        Returns:
            bool: True if the Podman client is available, False otherwise.
        """
        # Ping the Podman client using the client instance
        return self.client.ping()
