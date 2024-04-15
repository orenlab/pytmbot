#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime
from humanize import naturalsize, naturaltime
import docker

from app.core import exceptions
from app import bot_logger
from app.core.settings.bot_settings import DockerSettings


class DockerAdapter:
    """Class to adapt docker-py to ptmbot"""

    def __init__(self) -> None:
        """Init docker-py adapter class"""
        self.docker_url: str = DockerSettings.docker_host
        self.client = None
        self.registry_digest: None = None
        self.local_image_digest: None = None
        self.containers: None = None
        self.container: None = None
        self.log = bot_logger

    def _create_docker_client(self) -> docker.DockerClient:
        """Creates the docker client instance"""
        try:
            self.client = docker.DockerClient(self.docker_url)
            return self.client
        except ConnectionError:
            self.log.error("Can't connect to docker sock")

    def _is_docker_available(self) -> bool:
        """Check if the docker socket is available"""
        client = self._create_docker_client()
        ping = client.ping()
        return ping

    def _containers_list(self):
        """List all docker containers"""
        try:
            client = self._create_docker_client()
            containers_raw = repr(client.containers.list())
            if containers_raw == '[]':
                self.log.debug('No containers found. Docker is run.')
            else:
                image_tag = []
                for container in containers_raw.split(', '):
                    image_tag.append(
                        container.split(': ')[1].strip().split('>')[0].strip()
                    )
                return image_tag
        except FileNotFoundError:
            raise exceptions.DockerAdapterException('No container found')
        except ConnectionError:
            self.log.debug('Auth error. Please check your internet connection and try again')
            raise exceptions.DockerAdapterException('Check auth credentials in Docker')

    def _container_details(self, container_id: str):
        """Get docker containers details"""
        client = self._create_docker_client()
        container = client.containers.get(container_id)
        return container

    @staticmethod
    def _container_stats(container_details) -> dict:
        """Get docker container stats"""
        usage_stats = container_details.stats(decode=None, stream=False)
        return usage_stats

    def check_image_details(self):
        """Check docker image details"""
        try:
            if self._is_docker_available():
                self.containers = self._containers_list()
                details = []
                if self.containers:
                    for container in self.containers:
                        container_details = self._container_details(container)
                        usage_stats = self._container_stats(container_details)
                        created_day = datetime.fromisoformat(container_details.attrs['Created']).date()
                        created_time = datetime.fromisoformat(
                            container_details.attrs['Created']
                        ).time().strftime("%H:%M:%S")
                        details.append(
                            {
                                'name': container_details.attrs['Name'].title(),
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
                    return details
                else:
                    self.log.debug('Docker image not found: see "docker ps" command')
                    return {}
            else:
                self.log.error('Docker socket not found. Check docker URL')
                return {}
        except ValueError:
            self.log.debug('Image value error')
            raise exceptions.DockerAdapterException('Image value error')
