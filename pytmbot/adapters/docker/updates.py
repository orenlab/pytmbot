import json
import re
from datetime import datetime
from typing import List, Dict, Optional

import requests
from docker import DockerClient
from packaging.version import parse as parse_version, InvalidVersion

from pytmbot.logs import bot_logger
from pytmbot.models.containers_model import DockerHubTag


class DockerImageUpdater:
    def __init__(self, _docker_client: DockerClient):
        self.docker_client = _docker_client

    def get_local_images(self) -> List[str]:
        """
        Retrieves a list of all local Docker images in use.

        Returns:
            List[str]: A list of image repository names and tags.
        """
        bot_logger.debug("Retrieving local Docker images.")
        try:
            images = self.docker_client.images.list()
            local_images = [
                tag for image in images for tag in image.tags
            ]  # Flatten the list of tags
            bot_logger.debug(f"Local images retrieved: {local_images}")
            return local_images
        except Exception as e:
            bot_logger.error(f"Failed to retrieve local images: {e}")
            return []

    @staticmethod
    def get_docker_hub_tags(image_name: str) -> List[DockerHubTag]:
        """
        Retrieves the list of tags and their last pushed times for a given image from Docker Hub.

        Args:
            image_name (str): The name of the image repository.

        Returns:
            List[DockerHubTag]: A list of DockerHubTag models, each containing tag information.
        """
        bot_logger.debug(f"Fetching tags from Docker Hub for image {image_name}.")
        try:
            urls = [
                f"https://registry.hub.docker.com/v2/repositories/{image_name}/tags/",
                f"https://registry.hub.docker.com/v2/repositories/library/{image_name}/tags/",
            ]
            docker_tags = []
            for url in urls:
                response = requests.get(url)
                if response.status_code == 404:
                    continue  # Try the next URL
                response.raise_for_status()
                tags = response.json().get("results", [])
                docker_tags.extend(
                    DockerHubTag(name=tag["name"], last_pushed=tag["tag_last_pushed"])
                    for tag in tags
                )
                # Handle pagination
                while "Link" in response.headers:
                    next_page = response.headers.get("Link", "").split(";").strip("<>")
                    if not next_page:
                        break
                    response = requests.get(next_page)
                    response.raise_for_status()
                    tags = response.json().get("results", [])
                    docker_tags.extend(
                        DockerHubTag(
                            name=tag["name"], last_pushed=tag["tag_last_pushed"]
                        )
                        for tag in tags
                    )
            bot_logger.debug(f"Tags retrieved from Docker Hub: {docker_tags}")
            return docker_tags
        except requests.RequestException as e:
            bot_logger.error(
                f"Failed to fetch or validate tags from Docker Hub for image {image_name}: {e}"
            )
            return []

    def get_latest_stable_tag(self, tags: List[DockerHubTag]) -> Optional[str]:
        """
        Determines the latest stable tag from a list of tags based on last pushed time and stability.

        Args:
            tags (List[DockerHubTag]): The list of tag dictionaries with 'name' and 'last_pushed'.

        Returns:
            Optional[str]: The latest stable tag or None if no stable tag is found.
        """
        bot_logger.debug("Determining the latest stable tag.")
        if not tags:
            bot_logger.debug("No tags available for determining latest stable tag.")
            return None

        stable_tags = [tag for tag in tags if not self.is_beta_or_alpha(tag.name)]
        bot_logger.debug(f"Stable tags: {stable_tags}")

        if not stable_tags:
            bot_logger.info("No stable tags found.")
            return None

        # Filter out invalid versions
        valid_tags = []
        for tag in stable_tags:
            try:
                parse_version(tag.name)
                valid_tags.append(tag)
            except InvalidVersion:
                bot_logger.warning(f"Invalid version found and ignored: {tag.name}")

        if not valid_tags:
            bot_logger.info("No valid stable tags found.")
            return None

        tags_sorted = sorted(
            valid_tags,
            key=lambda x: (
                parse_version(x.name),
                datetime.fromisoformat(x.last_pushed.replace("Z", "+00:00")),
            ),
            reverse=True,
        )

        latest_tag = tags_sorted[0].name
        bot_logger.debug(f"Latest stable tag determined: {latest_tag}")
        return latest_tag

    @staticmethod
    def is_beta_or_alpha(tag_name: str) -> bool:
        """
        Determines if a tag is a beta or alpha version based on its name.

        Args:
            tag_name (str): The name of the tag.

        Returns:
            bool: True if the tag is beta or alpha, False otherwise.
        """
        is_beta_or_alpha = any(
            keyword in tag_name for keyword in ["beta", "alpha", "dev"]
        )
        bot_logger.debug(f"Tag {tag_name} is beta or alpha: {is_beta_or_alpha}")
        return is_beta_or_alpha

    @staticmethod
    def get_similar_tags(tags: List[str], current_tag: str) -> List[str]:
        """
        Finds similar tags based on naming patterns.

        Args:
            tags (List[str]): A list of tag names.
            current_tag (str): The current tag name.

        Returns:
            List[str]: A list of similar tags.
        """
        bot_logger.debug(f"Finding similar tags for current tag {current_tag}.")
        pattern = re.compile(rf"{re.escape(current_tag.split('-')[0])}")
        similar_tags = [tag for tag in tags if pattern.match(tag)]
        bot_logger.debug(f"Similar tags found: {similar_tags}")
        return similar_tags

    def check_for_updates(self) -> Dict[str, Dict[str, str]]:
        """
        Checks for updates for all local Docker images by comparing with Docker Hub.

        Returns:
            Dict[str, Dict[str, str]]: A dictionary with image names as keys. Each value is another dictionary containing update status, last stable tag, and last unstable tag.
        """
        bot_logger.debug("Checking for updates.")
        updates = {}
        local_images = self.get_local_images()

        for image in local_images:
            repo, tag = image.split(":", 1) if ":" in image else (image, "latest")
            bot_logger.debug(f"Checking image {repo} with tag {tag}.")
            latest_tags = self.get_docker_hub_tags(repo)

            if not latest_tags:
                bot_logger.info(f"No tags found for image {repo}.")
                continue

            latest_stable_tag = self.get_latest_stable_tag(latest_tags)
            last_unstable_tag = self.get_last_unstable_tag(latest_tags)

            # Directly use the string value for comparison
            if latest_stable_tag and parse_version(latest_stable_tag) > parse_version(
                tag
            ):
                update_info = {
                    "update_status": f"Update available: {latest_stable_tag}",
                    "last_stable_tag": latest_stable_tag,
                    "last_stable_tag_last_pushed": self.get_tag_last_pushed(
                        latest_tags, latest_stable_tag
                    ),
                }

                if last_unstable_tag and parse_version(
                    last_unstable_tag.name
                ) > parse_version(latest_stable_tag):
                    update_info["last_unstable_tag"] = {
                        "name": last_unstable_tag.name,
                        "last_pushed": last_unstable_tag.last_pushed,
                    }

                updates[image] = update_info
                bot_logger.info(
                    f"Update available for image {image}: {latest_stable_tag}"
                )

        if not updates:
            bot_logger.info("All images are up-to-date.")
        else:
            bot_logger.info(f"Update checks complete: {updates}")

        return updates

    def get_last_unstable_tag(self, tags: List[DockerHubTag]) -> Optional[DockerHubTag]:
        """
        Retrieves the last unstable tag from a list of tags.

        Args:
            tags (List[DockerHubTag]): The list of tag dictionaries with 'name' and 'last_pushed'.

        Returns:
            Optional[DockerHubTag]: The last unstable tag or None if no unstable tag is found.
        """
        bot_logger.debug("Determining the last unstable tag.")
        unstable_tags = [tag for tag in tags if self.is_beta_or_alpha(tag.name)]
        bot_logger.debug(f"Unstable tags: {unstable_tags}")

        if not unstable_tags:
            bot_logger.info("No unstable tags found.")
            return None

        # Filter out invalid versions
        valid_tags = []
        for tag in unstable_tags:
            try:
                parse_version(tag.name)
                valid_tags.append(tag)
            except InvalidVersion:
                bot_logger.warning(f"Invalid version found and ignored: {tag.name}")

        if not valid_tags:
            bot_logger.info("No valid unstable tags found.")
            return None

        last_unstable_tag = max(
            valid_tags,
            key=lambda x: (
                parse_version(x.name),
                datetime.fromisoformat(x.last_pushed.replace("Z", "+00:00")),
            ),
        )
        bot_logger.debug(f"Last unstable tag determined: {last_unstable_tag.name}")
        return last_unstable_tag

    @staticmethod
    def get_tag_last_pushed(tags: List[DockerHubTag], tag_name: str) -> Optional[str]:
        """
        Retrieves the last pushed date for a specific tag.

        Args:
            tags (List[DockerHubTag]): The list of tag dictionaries with 'name' and 'last_pushed'.
            tag_name (str): The tag name.

        Returns:
            Optional[str]: The last pushed date or None if the tag is not found.
        """
        for tag in tags:
            if tag.name == tag_name:
                return tag.last_pushed
        return None


if __name__ == "__main__":
    docker_client = DockerClient(
        base_url="unix://Users/denroznovskiy/.docker/run/docker.sock"
    )
    updater = DockerImageUpdater(docker_client)
    is_updates_available = updater.check_for_updates()
    print(json.dumps(is_updates_available, indent=4))
