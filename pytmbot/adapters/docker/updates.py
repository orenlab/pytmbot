import json
import re
from types import TracebackType
from typing import Dict, List, Union

import requests
from packaging import version

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import bot_logger
from pytmbot.models.docker_models import TagInfo, UpdateInfo


class DockerImageUpdater:
    """Class to check for updates for local Docker images by comparing their tags
    with the tags available on the Docker Hub repository. It also checks tag priorities
    and can parse versions of different formats.
    """

    def __init__(self) -> None:
        """Initializes DockerImageUpdater with a Docker client instance."""
        self.local_images = self._get_local_images()

    def __enter__(self) -> "DockerImageUpdater":
        """Support for context management protocol."""
        return self

    def __exit__(
            self, exc_type: type, exc_val: BaseException, exc_tb: TracebackType
    ) -> None:
        """Cleanup code for context management."""
        self.local_images = None

    @staticmethod
    def _get_local_images() -> Dict[str, List[Dict[str, Union[str, None]]]]:
        """Fetches all local Docker images and their associated tags.

        Returns:
            Dict[str, List[Dict[str, Union[str, None]]]]: A dictionary where the keys are image repositories
            and the values are lists of tags with their creation dates.
        """
        with DockerAdapter() as adapter:
            images = adapter.images.list(all=True)
        local_images = {}
        for image in images:
            for tag in image.tags:
                repo, tag_version = tag.split(":")
                if repo not in local_images:
                    local_images[repo] = []
                local_images[repo].append(
                    {"tag": tag_version, "created_at": image.attrs.get("Created")}
                )
        bot_logger.info(f"Fetched local images: {local_images}")
        return local_images

    @staticmethod
    def _get_remote_tags(repo: str) -> List[TagInfo]:
        """Fetches all available tags for a given repository from Docker Hub, along with the creation date.

        Args:
            repo (str): The name of the repository on Docker Hub.

        Returns:
            List[TagInfo]: A list of TagInfo objects containing tag names and creation dates.
        """
        urls = [
            f"https://registry.hub.docker.com/v2/repositories/{repo}/tags/",
            f"https://registry.hub.docker.com/v2/repositories/library/{repo}/tags/",
        ]
        tags_info = []
        for url in urls:
            try:
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
                tags_info.extend(
                    TagInfo(name=result["name"], created_at=result["tag_last_pushed"])
                    for result in data["results"]
                )
                bot_logger.info(f"Fetched tags from {url}")
                break
            except requests.exceptions.RequestException as e:
                bot_logger.error(f"Failed to fetch tags from {url}: {e}")
        return tags_info

    def _compare_versions(self, current_tag: str, remote_tag: str) -> bool:
        """Compares two tags by parsing version information if possible.

        Args:
            current_tag (str): The local tag of the image.
            remote_tag (str): The remote tag from the repository.

        Returns:
            bool: True if the remote tag is newer, otherwise False.
        """
        try:
            current_version = version.parse(self._extract_version(current_tag))
            remote_version = version.parse(self._extract_version(remote_tag))
            result = remote_version > current_version
            bot_logger.debug(
                f"Comparing versions: current={current_version}, remote={remote_version}, result={result}"
            )
            return result
        except Exception as e:
            bot_logger.debug(f"Version comparison error: {e}")
            return (
                    remote_tag > current_tag
            )  # Default to lexicographic comparison if version parsing fails

    @staticmethod
    def _extract_version(tag: str) -> str:
        """Extracts the version part from a tag, assuming the version is the leading part of the tag.

        Args:
            tag (str): The tag to extract the version from.

        Returns:
            str: The version part of the tag.
        """
        version_match = re.match(r"^v?(\d+(\.\d+)+)", tag)
        return version_match.group(1) if version_match else tag

    @staticmethod
    def _get_tag_priority(tag: str) -> int:
        """Assigns a priority to the tag based on common tag names like 'latest', 'stable', 'beta', etc.

        Args:
            tag (str): The Docker image tag.

        Returns:
            int: A numerical priority, lower values indicate higher priority.
        """
        priority_tags = {
            "latest": 0,
            "stable": 1,
            "beta": 2,
            "alpha": 3,
            "dev": 4,
            "pre-release": 5,
        }
        priority = priority_tags.get(
            tag.lower(), 100
        )  # 100 is the default priority for unknown tags
        bot_logger.debug(f"Tag '{tag}' has priority {priority}")
        return priority

    def _compare_priority(self, current_tag: str, remote_tag: str) -> bool:
        """Compares two tags based on their priority if they don't have version numbers.

        Args:
            current_tag (str): The local tag of the image.
            remote_tag (str): The remote tag from the repository.

        Returns:
            bool: True if the remote tag has higher priority, otherwise False.
        """
        current_priority = self._get_tag_priority(current_tag)
        remote_priority = self._get_tag_priority(remote_tag)
        result = remote_priority < current_priority
        bot_logger.debug(
            f"Comparing priorities: current_tag={current_tag} (priority={current_priority}), "
            f"remote_tag={remote_tag} (priority={remote_priority}), result={result}"
        )
        return result

    @staticmethod
    def _is_developer_tag(tag: str) -> bool:
        """Determines if a tag is a developer tag based on known tag types.

        Args:
            tag (str): The Docker image tag.

        Returns:
            bool: True if the tag is a developer tag, otherwise False.
        """
        developer_tags = {"dev", "development", "test", "alpha", "beta", "pre-release"}
        result = any(dev_tag in tag.lower() for dev_tag in developer_tags)
        bot_logger.debug(
            f"Tag '{tag}' is {'a developer tag' if result else 'not a developer tag'}"
        )
        return result

    def _check_updates(self) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
        """Checks all local images for updates by comparing their tags with the available remote tags.

        Returns:
            Dict[str, Dict[str, List[Dict[str, str]]]]: A dictionary with repositories as keys and their tags
            along with potential updates.
        """
        updates = {}
        for repo, tags in self.local_images.items():
            bot_logger.info(f"Checking updates for repository '{repo}'")
            remote_tags = self._get_remote_tags(repo)
            updates[repo] = {
                "current_tags": tags,
                "stable_updates": [],
                "developer_updates": [],
            }

            for tag_info in tags:
                tag = tag_info["tag"]
                for remote_tag_info in remote_tags:
                    remote_tag = remote_tag_info.name
                    if self._compare_versions(tag, remote_tag):
                        update_info = UpdateInfo(
                            current_tag=tag,
                            newer_tag=remote_tag,
                            created_at_local=tag_info["created_at"],
                            created_at_remote=remote_tag_info.created_at,
                        )
                        if self._is_developer_tag(remote_tag):
                            updates[repo]["developer_updates"].append(
                                update_info.to_dict()
                            )
                        else:
                            updates[repo]["stable_updates"].append(
                                update_info.to_dict()
                            )
                        bot_logger.info(f"Update found: {update_info.to_dict()}")

        # Sort and limit the developer updates
        for repo, info in updates.items():
            info["developer_updates"] = sorted(
                info["developer_updates"],
                key=lambda x: x["created_at_remote"],
                reverse=True,
            )[:3]
            bot_logger.info(
                f"Sorted developer updates for repository '{repo}': {info['developer_updates']}"
            )

        return updates

    def to_json(self) -> str:
        """Returns the update check result in JSON format.

        Returns:
            str: A JSON string containing the updates.
        """
        result = self._check_updates()
        bot_logger.info(f"Update check result: {result}")
        return json.dumps(result, indent=4)


if __name__ == "__main__":
    with DockerImageUpdater() as updater:
        print(updater.to_json())
