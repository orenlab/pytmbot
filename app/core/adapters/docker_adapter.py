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


class DockerImageUpdateChecker:
    """Class to check if a docker image is update"""

    def __init__(self) -> None:
        """Initialize the DockerImageUpdateChecker class"""
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
        except exceptions.DockerImageUpdateCheckerException:
            raise exceptions.DockerImageUpdateCheckerException('No container found')
        except ConnectionError:
            self.log.debug('Auth error. Please check your internet connection and try again')
            raise exceptions.DockerImageUpdateCheckerException('Check auth credentials in Docker')

    def _container_details(self, container_id: str):
        """Get docker containers details"""
        container = self.client.containers.get(container_id)
        return container.attrs['Config']['Image']

    def check_image_details(self):
        """Check docker image details"""
        try:
            self.containers = self._containers_list()
            details = []
            updates = []
            if self.containers:
                for container in self.containers:
                    details.append(self._container_details(container))
                for image in details:
                    print(self.get_registry_digest(image[0].split(':')[0].strip()))
                    if image is not None:
                        updates.append({image: self.get_registry_digest(image[0].split(':')[0].strip())})
                    else:
                        updates.append({image: "No registry data"})
                print(updates)
            else:
                self.log.debug('Docker image not found: see docker ps')
                raise exceptions.DockerImageUpdateCheckerException('Docker image not found: see docker ps')
        except ValueError:
            self.log.debug('Image value error')
            raise exceptions.DockerImageUpdateCheckerException('Image value error')

    def get_registry_digest(self, image_name: str) -> str:
        try:
            self.log.debug(f'Getting registry digest for {image_name}')
            registry_digest_raw = self.client.images.get_registry_data(image_name)
            print(registry_digest_raw)
            self.registry_digest = repr(registry_digest_raw).split(" ")[1].replace(">", "")
            self.log.info(f"Registry image digest: {self.local_image_digest}")
            return self.registry_digest
        except ValueError as err:
            raise exceptions.DockerImageUpdateCheckerException("Check registry digest error") from err

    def get_local_digest(self, image_name: str) -> str:
        try:
            self.log.debug(f'Getting local digest for {image_name}')
            local_image_digest_raw = self.client.api.inspect_image(image_name)
            self.local_image_digest = repr(local_image_digest_raw["RepoDigests"]).split("@")[1].replace(">", "")[0:19]
            self.log.info(f"Local image digest: {self.local_image_digest}")
            return self.local_image_digest
        except ValueError as err:
            raise exceptions.DockerImageUpdateCheckerException("Check local digest error") from err
