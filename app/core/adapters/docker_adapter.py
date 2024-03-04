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

log = build_logger(__name__)


class DockerImageUpdateChecker:
    """Class to check if a docker image is update"""

    def __init__(self, image_name: str | None = None) -> None:
        self.images_name = image_name
        self.docker_url: str = DockerSettings.docker_host
        self.client = docker.DockerClient(self.docker_url)
        self.registry_digest: None = None
        self.local_image_digest: None = None
        self.image_name: None = None

    def get_registry_digest(self) -> str:
        try:
            log.debug(f'Getting registry digest for {self.image_name}')
            registry_digest_raw = self.client.images.get_registry_data(self.image_name)
            self.registry_digest = repr(registry_digest_raw).split(" ")[1].replace(">", "")
            log.info(f"Registry image digest: {self.local_image_digest}")
            return self.registry_digest
        except ValueError as err:
            raise exceptions.DockerImageUpdateCheckerException("Check registry digest error") from err

    def get_local_digest(self) -> str:
        try:
            log.debug(f'Getting local digest for {self.image_name}')
            local_image_digest_raw = self.client.api.inspect_image(self.image_name)
            self.local_image_digest = repr(local_image_digest_raw["RepoDigests"]).split("@")[1].replace(">", "")[0:19]
            log.info(f"Local image digest: {self.local_image_digest}")
            return self.local_image_digest
        except ValueError as err:
            raise exceptions.DockerImageUpdateCheckerException("Check local digest error") from err

    def check_updates(self) -> dict:
        try:
            updates_list = {}
            for self.image_name['image_name'] in self.images_name:
                updates_list += {self.image_name}
                if self.get_registry_digest() == self.get_local_digest():
                    log.info(f"No updates found for local image {self.image_name}")
                    updates_list += {'update_available': False, self.image_name: self.registry_digest}
                else:
                    log.info(f"Updates found for local image {self.image_name}")
                    updates_list += {'update_available': True, self.image_name: self.registry_digest}
            return updates_list
        except self.client.ApiException as err:
            raise exceptions.DockerImageUpdateCheckerException("Check digest error") from err
