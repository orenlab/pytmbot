#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime
from functools import lru_cache

import docker

from app.core import exceptions
from app import build_logger
from app.core.settings.bot_settings import DockerSettings
from app.utilities.utilities import format_datetime, pretty_date, format_bytes


class DockerAdapter:
    """Class to check if a docker image is update"""

    def __init__(self) -> None:
        """Initialize the DockerAdapter class"""
        self.docker_url: str = DockerSettings.docker_host
        self.client = docker.DockerClient(self.docker_url)
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
        except FileNotFoundError:
            raise exceptions.DockerAdapterException('No container found')
        except ConnectionError:
            self.log.debug('Auth error. Please check your internet connection and try again')
            raise exceptions.DockerAdapterException('Check auth credentials in Docker')

    def _container_details(self, container_id: str):
        """Get docker containers details"""
        container = self.client.containers.get(container_id)
        return container

    @lru_cache(maxsize=128)
    def _container_stats(self, container_details) -> dict:
        """Get docker container stats"""
        usage_stats = container_details.stats(decode=None, stream=False)
        return usage_stats

    def check_image_details(self):
        """Check docker image details"""
        try:
            self.containers = self._containers_list()
            details = []
            if self.containers:
                for container in self.containers:
                    container_details = self._container_details(container)
                    usage_stats = self._container_stats(container_details)
                    created_date_time = format_datetime(container_details.attrs['Created'])
                    details.append(
                        {
                            'name': container_details.attrs['Name'].title(),
                            'image': container_details.attrs['Config']['Image'],
                            'created': f'{created_date_time[0]}, {created_date_time[1]}',
                            'mem_usage': format_bytes(usage_stats['memory_stats']['usage']),
                            'uptime': pretty_date(
                                datetime.fromisoformat(
                                    container_details.attrs['State']['StartedAt']
                                ).astimezone(
                                    tz=None
                                ).replace(
                                    tzinfo=None
                                )
                            ),
                            'status': container_details.attrs['State']['Status']
                        }
                    )
                return details
            else:
                self.log.debug('Docker image not found: see "docker ps" command')
                return {}
        except ValueError:
            self.log.debug('Image value error')
            raise exceptions.DockerAdapterException('Image value error')
