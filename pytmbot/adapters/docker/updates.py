import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp
from dateutil.parser import isoparse

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import Logger
from pytmbot.models.docker_models import TagInfo, UpdateInfo

logger = Logger()


class DockerImageUpdater:
    """Class to check for updates for local Docker images by comparing their tags
    with the tags available on the Docker Hub repository."""

    def __init__(self) -> None:
        """Initializes DockerImageUpdater with a Docker client instance."""
        self.local_images: Dict[str, List[Dict[str, Optional[str]]]] = {}
        self.local_patterns: Dict[str, Dict[str, Optional[str]]] = {}
        self.tag_cache: Dict[str, List[TagInfo]] = {}

    def initialize(self):
        """Initialization to fetch local images and determine patterns."""
        self.local_images = self._get_local_images()

    @staticmethod
    def _get_local_images() -> Dict[str, List[Dict[str, Optional[str]]]]:
        """Fetches all local Docker images and their associated tags."""
        with DockerAdapter() as adapter:
            images = adapter.images.list(all=False)
            logger.info(f"Fetched images from Docker: {images}")

        local_images: Dict[str, List[Dict[str, Optional[str]]]] = {}

        for image in images:
            repo_tags = image.tags

            if not repo_tags:
                logger.warning(f"Image doesn't have any 'RepoTags': {image}")
                continue  # Skip this image if RepoTags is empty

            for tag in repo_tags:
                if ":" not in tag:
                    logger.warning(f"Invalid tag format: {tag}")
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

        logger.info(f"Fetched local images: {local_images}")
        return local_images

    async def _fetch_remote_tags(
            self, session: aiohttp.ClientSession, repo: str
    ) -> List[TagInfo]:
        """Fetches available tags for a repository from Docker Hub asynchronously."""
        cached_tags = self.tag_cache.get(repo)
        if cached_tags:
            logger.info(f"Using cached tags for repository: {repo}")
            return cached_tags

        base_urls = [
            f"https://registry.hub.docker.com/v2/repositories/{repo}/tags/",
            f"https://registry.hub.docker.com/v2/repositories/library/{repo}/tags/",
        ]
        tags_info: List[TagInfo] = []
        for url in base_urls:
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", "5"))
                        logger.warning(
                            f"Rate limit reached for {repo}, retrying after {retry_after} seconds"
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    response.raise_for_status()
                    data = await response.json()
                    if not data.get("results"):
                        logger.warning(f"No tags found for repo '{repo}' at {url}")
                        continue

                    tags_info.extend(
                        TagInfo(name=result["name"], created_at=result.get("tag_last_pushed", ""))
                        for result in data["results"]
                    )
                    # Cache and break if successful
                    self.tag_cache[repo] = tags_info
                    logger.info(f"Fetched tags for {repo} from {url}")
                    break
            except aiohttp.ClientError as e:
                logger.warning(f"Failed to fetch tags from {url}: {e}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON response from {url}: {e}")
        return tags_info

    async def _get_remote_tags(self, repo: str) -> List[TagInfo]:
        """Asynchronously fetches remote tags for a repository."""
        async with aiohttp.ClientSession() as session:
            return await self._fetch_remote_tags(session, repo)

    @staticmethod
    def _extract_version(tag: str) -> str:
        """Extracts the most likely version pattern from a tag."""
        # Match semantic versions or timestamps
        version_match = re.match(r"^v?(\d+(\.\d+)+)", tag)
        if version_match:
            return version_match.group(1)

        # Check for a date-based tag (e.g., 2023.09.01)
        date_match = re.match(r"^\d{4}(\.\d{1,2}){2}$", tag)
        if date_match:
            return tag  # Return directly for date-based tags

        # Return the tag itself if no match is found
        return tag

    @staticmethod
    def _filter_tags(tags: List[TagInfo], include_pre_release: bool = False, allow_latest: bool = True) -> List[
        TagInfo]:
        """
        Filters tags based on rules (e.g., pre-release, alpha, beta).
        Includes an option to keep or exclude 'latest'.
        """
        filtered_tags = []
        pre_release_pattern = re.compile(r"(alpha|beta|rc|pre)", re.IGNORECASE)

        for tag_info in tags:
            if tag_info.name == "latest" and not allow_latest:
                # Skip 'latest' if it's disabled explicitly
                continue

            # Skip pre-release versions unless explicitly included
            if not include_pre_release and pre_release_pattern.search(tag_info.name):
                continue

            # Skip invalid or empty tags
            if not tag_info.name or not tag_info.created_at:
                continue

            filtered_tags.append(tag_info)

        # Optional: Sort tags by created_at to prioritize newest updates
        filtered_tags.sort(key=lambda tag: isoparse(tag.created_at), reverse=True)
        return filtered_tags

    @staticmethod
    def _is_remote_tag_newer(local_tag_date: Optional[str], remote_tag_info: TagInfo) -> bool:
        """Compares the date of local tag with remote tag."""
        try:
            # Convert dates from strings to datetime objects
            local_date = isoparse(local_tag_date) if isinstance(local_tag_date, str) else None
            remote_date = isoparse(remote_tag_info.created_at)

            if not local_date:
                # If local date is missing, assume the remote tag is newer
                return True

            # Compare dates
            return local_date < remote_date
        except Exception as e:
            logger.error(f"Error comparing dates: {e}")
            return False

    async def _check_updates(self) -> Dict[str, Dict[str, List[UpdateInfo]]]:
        """Checks for updates by comparing local and remote tag creation dates."""
        updates: Dict[str, Dict[str, List[UpdateInfo]]] = {}

        tasks = []
        for repo, tags in self.local_images.items():
            logger.info(f"Checking updates for repository '{repo}'")
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

        # Filter and sort remote tags before comparison
        remote_tags = self._filter_tags(remote_tags, include_pre_release=False)

        repo_updates = {"updates": []}

        all_updates = []

        for local_tag_info in tags:
            local_tag = local_tag_info["tag"]
            local_tag_date = local_tag_info["created_at"]

            # 0. Special handling for 'latest'
            if local_tag == "latest":
                logger.info(f"Checking updates specifically for the 'latest' tag in repository '{repo}'")
                # Find remote `latest`
                remote_latest = next((tag for tag in remote_tags if tag.name == "latest"), None)
                if not remote_latest:
                    logger.warning(f"No 'latest' tag found for repository '{repo}'")
                    continue

                # Check if remote `latest` is newer than local `latest`
                if self._is_remote_tag_newer(local_tag_date, remote_latest):
                    all_updates.append(UpdateInfo(
                        current_tag="latest",
                        newer_tag="latest",
                        created_at_local=local_tag_date,
                        created_at_remote=remote_latest.created_at,
                        current_digest=remote_latest.digest
                    ))
                continue

            # 1. Check for updates specifically for the current local tag
            specific_updates = [
                UpdateInfo(
                    current_tag=local_tag,
                    newer_tag=remote_tag_info.name,
                    created_at_local=local_tag_date,
                    created_at_remote=remote_tag_info.created_at,
                    current_digest=remote_tag_info.digest,
                )
                for remote_tag_info in remote_tags
                if remote_tag_info.name == local_tag
                   and self._is_remote_tag_newer(local_tag_date, remote_tag_info)
            ]

            # 2. Add updates for other newer tags
            other_updates = [
                UpdateInfo(
                    current_tag=local_tag,
                    newer_tag=remote_tag_info.name,
                    created_at_local=local_tag_date,
                    created_at_remote=remote_tag_info.created_at,
                    current_digest=remote_tag_info.digest,
                )
                for remote_tag_info in remote_tags
                if remote_tag_info.name != local_tag
                   and self._is_remote_tag_newer(local_tag_date, remote_tag_info)
            ]

            # Combine specific and other updates
            all_updates.extend(specific_updates + other_updates)

        # Sort updates by remote tag creation date in descending order (newest first)
        all_updates.sort(key=lambda x: isoparse(x.created_at_remote), reverse=True)

        # Limit updates to the first 5
        repo_updates["updates"] = [update.to_dict() for update in all_updates[:5]]

        updates[repo] = repo_updates

    def to_json(self) -> str:
        """Returns the update check result in JSON format."""
        result = asyncio.run(self._check_updates())
        logger.info(f"Update check result: {result}")
        return json.dumps(result, indent=4)
