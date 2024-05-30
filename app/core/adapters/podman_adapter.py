#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from podman import PodmanClient


class PodmanAdapter:
    """Class to adapt podman-py to pyTMbot"""

    def __init__(self):
        """Init podman-py adapter class"""
        self.uri = "unix:///run/user/1000/podman/podman.sock"
        self.client = PodmanClient(base_url=self.uri)

    def get_podman_version(self):
        return self.client.version()

    def ping_podman(self):
        return self.client.ping()
