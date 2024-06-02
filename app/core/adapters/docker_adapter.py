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
    """Class to adapt docker-py to pyTMbot"""

    def __init__(self) -> None:
        """Init docker-py adapter class"""
        self.docker_url: str = config.docker_host
        self.client = None
        self.registry_digest: None = None
        self.local_image_digest: None = None
        self.containers: None = None
        self.container: None = None

    @lru_cache(maxsize=None)
    def _create_docker_client(self) -> docker.DockerClient:
        """Creates the docker client instance"""
        try:
            self.client = docker.DockerClient(self.docker_url)
            bot_logger.debug("Created docker client success")
            return self.client
        except (ConnectionAbortedError, FileNotFoundError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def _is_docker_available(self) -> bool:
        """Check if the docker socket is available"""
        try:
            client = self._create_docker_client()
            ping = client.ping()
            bot_logger.debug(f"Docker alive: {ping}")
            return ping
        except (ConnectionAbortedError, FileNotFoundError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def _containers_list(self):
        """List all docker containers"""
        try:
            client = self._create_docker_client()
            containers_raw = repr(client.containers.list())
            if containers_raw == '[]':
                bot_logger.debug('No containers found. Docker is run.')
            else:
                image_tag = []
                for container in containers_raw.split(', '):
                    image_tag.append(
                        container.split(': ')[1].strip().split('>')[0].strip()
                    )
                bot_logger.debug(f"Container list created: {image_tag}")
                return image_tag
        except (FileNotFoundError, ConnectionError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def _container_details(self, container_id: str):
        """Get docker containers details"""
        try:
            client = self._create_docker_client()
            container = client.containers.get(container_id)
            bot_logger.debug(f"Container details retrieved: {container}")
            return container
        except (ValueError, FileNotFoundError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    @staticmethod
    def _container_stats(container_details) -> dict:
        """Get docker container stats"""
        usage_stats = container_details.stats(decode=None, stream=False)
        bot_logger.debug(f"Container stats generated: {usage_stats}")
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
                    bot_logger.debug(f"Container image details append: {details}")
                    return details
                else:
                    bot_logger.debug('Docker image not found: see "docker ps" command')
                    return {}
            else:
                bot_logger.error('Docker socket not found. Check docker URL')
                return {}
        except ValueError as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")
