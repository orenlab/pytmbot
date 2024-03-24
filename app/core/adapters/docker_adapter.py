#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import docker

from app.core import exceptions
from app import build_logger
from app.core.settings.bot_settings import DockerSettings
from app.utilities.utilities import split_str, replace_symbol


class DockerAdapter:
    """Class to check if a docker image is update"""

    def __init__(self) -> None:
        """Initialize the DockerImageUpdateChecker class"""
        self.docker_url: str = DockerSettings.docker_host
        self.client = docker.DockerClient(self.docker_url)
        self.split_str = split_str
        self.replace_symbol = replace_symbol
        self.registry_digest: None = None
        self.local_image_digest: None = None
        self.containers: None = None
        self.container: None = None
        self.log = build_logger(__name__)

    def _containers_list(self):
        """List all docker containers"""
        try:
            containers_raw = repr(self.client.containers.list())
            if containers_raw == '[]':
                self.log.debug('No containers found. Docker is run.')
            else:
                image_tag = []
                for container in containers_raw.split(', '):
                    image_tag.append(
                        container.split(': ')[1].strip().split('>')[0].strip()
                    )
                return image_tag
        except exceptions.DockerImageUpdateCheckerException:
            raise exceptions.DockerImageUpdateCheckerException('No container found')
        except ConnectionError:
            self.log.debug('Auth error. Please check your internet connection and try again')
            raise exceptions.DockerImageUpdateCheckerException('Check auth credentials in Docker')

    def _container_details(self, container_id: str):
        """Get docker containers details"""
        container = self.client.containers.get(container_id)
        return container.attrs

    def check_image_details(self):
        """Check docker image details"""
        try:
            self.containers = self._containers_list()
            details = []
            if self.containers:
                for container in self.containers:
                    container_details = self._container_details(container)
                    created_date = self.split_str(container_details['Created'], 'T')
                    created_time = self.split_str(created_date[1], '.')
                    start_data = self.split_str(container_details['State']['StartedAt'], 'T')
                    start_time = self.split_str(start_data[1], '.')
                    details.append(
                        {
                            'name': container_details['Name'].title(),
                            'image': container_details['Config']['Image'],
                            'created': f"{created_date[0]}, {created_time[0]}",
                            'status': container_details['State']['Status'],
                            'started': f"{start_data[0]}, {start_time[0]}",
                        }
                    )
                return details
            else:
                self.log.debug('Docker image not found: see "docker ps" command')
                return {}
        except ValueError:
            self.log.debug('Image value error')
            raise exceptions.DockerImageUpdateCheckerException('Image value error')
