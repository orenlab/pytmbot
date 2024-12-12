import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp
from dateutil.parser import isoparse

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import bot_logger
from pytmbot.models.docker_models import TagInfo, UpdateInfo


class DockerImageUpdater:
    """Class to check for updates for local Docker images by comparing their tags
    with the tags available on the Docker Hub repository."""

    def __init__(self) -> None:
        """Initializes DockerImageUpdater with a Docker client instance."""
        self.local_images: Dict[str, List[Dict[str, Optional[str]]]] = {}
        self.local_patterns: Dict[str, Dict[str, Optional[str]]] = {}

    def initialize(self):
        """Initialization to fetch local images and determine patterns."""
        self.local_images = self._get_local_images()

    @staticmethod
    def _get_local_images() -> Dict[str, List[Dict[str, Optional[str]]]]:
        """Fetches all local Docker images and their associated tags."""
        with DockerAdapter() as adapter:
            images = adapter.images.list(all=False)
            bot_logger.info(f"Fetched images from Docker: {images}")

        local_images: Dict[str, List[Dict[str, Optional[str]]]] = {}

        for image in images:
            repo_tags = image.tags

            if not repo_tags:
                bot_logger.warning(f"Image doesn't have any 'RepoTags': {image}")
                continue  # Skip this image if RepoTags is empty

            for tag in repo_tags:
                if ":" not in tag:
                    bot_logger.warning(f"Invalid tag format: {tag}")
                    continue
                repo, tag_version = tag.split(":", 1)

                created_at = image.attrs.get("Created")
                if isinstance(created_at, int):
                    created_at = datetime.fromtimestamp(
                        created_at, tz=timezone.utc
                    ).isoformat()

                local_images.setdefault(repo, []).append(
                    {
                        "tag": tag_version,
                        "created_at": created_at,
                    }
                )

        bot_logger.info(f"Fetched local images: {local_images}")
        return local_images

    @staticmethod
    async def _fetch_remote_tags(
        session: aiohttp.ClientSession, repo: str
    ) -> List[TagInfo]:
        """Fetches available tags for a repository from Docker Hub asynchronously."""
        if not repo:
            bot_logger.error("The repository name must be specified")

        urls = [
            f"https://registry.hub.docker.com/v2/repositories/{repo}/tags/",
            f"https://registry.hub.docker.com/v2/repositories/library/{repo}/tags/",
        ]
        tags_info: List[TagInfo] = []

        for url in urls:
            try:
                async with session.get(url, timeout=10) as response:
                    response.raise_for_status()
                    data = await response.json()
                    if not data.get("results"):
                        bot_logger.warning(f"No tags found for repo '{repo}'")
                        continue
                    tags_info.extend(
                        TagInfo(
                            name=result["name"],
                            created_at=result.get("tag_last_pushed", ""),
                        )
                        for result in data.get("results", [])
                    )
                    bot_logger.info(f"Fetched tags from {url}")
                    break
            except aiohttp.ClientError as e:
                bot_logger.warning(f"Failed to fetch tags from {url}: {e}")
            except json.JSONDecodeError as e:
                bot_logger.error(f"Failed to decode JSON response from {url}: {e}")
        return tags_info

    async def _get_remote_tags(self, repo: str) -> List[TagInfo]:
        """Asynchronously fetches remote tags for a repository."""
        async with aiohttp.ClientSession() as session:
            return await self._fetch_remote_tags(session, repo)

    @staticmethod
    def _extract_version(tag: str) -> str:
        """Extracts the version number from a tag, handling common patterns."""
        version_match = re.match(r"^v?(\d+(\.\d+)+)", tag)
        return version_match.group(1) if version_match else tag

    @staticmethod
    def _is_remote_tag_newer(local_tag_date, remote_tag_info):
        """Compares the date of local tag with remote tag."""
        try:
            if isinstance(local_tag_date, int):
                local_tag_date = datetime.fromtimestamp(
                    local_tag_date, tz=timezone.utc
                ).isoformat()

            if isinstance(local_tag_date, str):
                local_date = isoparse(local_tag_date)
            else:
                return False

            remote_date = isoparse(remote_tag_info.created_at)
            return local_date < remote_date

        except Exception as e:
            bot_logger.error(f"Error comparing dates: {e}")
            return False

    async def _check_updates(self) -> Dict[str, Dict[str, List[UpdateInfo]]]:
        """Checks for updates by comparing local and remote tag creation dates."""
        updates: Dict[str, Dict[str, List[UpdateInfo]]] = {}

        tasks = []
        for repo, tags in self.local_images.items():
            bot_logger.info(f"Checking updates for repository '{repo}'")
            tasks.append(self._check_repo_updates(repo, tags, updates))

        await asyncio.gather(*tasks)
        return updates

    async def _check_repo_updates(
        self,
        repo: str,
        tags: List[Dict[str, Optional[str]]],
        updates: Dict[str, Dict[str, List[UpdateInfo]]],
    ):
        """Helper function to check for updates for a specific repository."""
        remote_tags = await self._get_remote_tags(repo)
        repo_updates = {"updates": []}

        all_updates = []

        for local_tag_info in tags:
            local_tag_date = local_tag_info["created_at"]
            for remote_tag_info in remote_tags:
                if self._is_remote_tag_newer(local_tag_date, remote_tag_info):
                    update_info = UpdateInfo(
                        current_tag=local_tag_info["tag"],
                        newer_tag=remote_tag_info.name,
                        created_at_local=local_tag_date,
                        created_at_remote=remote_tag_info.created_at,
                    )
                    all_updates.append(update_info)
                    bot_logger.info(f"Update found for {repo}: {update_info.to_dict()}")

        # Sort updates by remote tag creation date in descending order (newest first)
        all_updates.sort(key=lambda x: isoparse(x.created_at_remote), reverse=True)

        # Limit updates to the first 5
        repo_updates["updates"] = [update.to_dict() for update in all_updates[:5]]

        updates[repo] = repo_updates

    def to_json(self) -> str:
        """Returns the update check result in JSON format."""
        result = asyncio.run(self._check_updates())
        bot_logger.info(f"Update check result: {result}")
        return json.dumps(result, indent=4)
