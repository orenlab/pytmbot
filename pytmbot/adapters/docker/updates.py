from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Dict, List, Optional
import asyncio
import json
import re
from packaging import version
import aiohttp
from dateutil.parser import isoparse

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import Logger
from pytmbot.models.docker_models import TagInfo, UpdateInfo

logger = Logger()


class TagType(Enum):
    SEMVER = auto()
    DATE = auto()
    LATEST = auto()
    SHA = auto()
    CUSTOM = auto()


@dataclass
class EnhancedTagInfo:
    tag_info: TagInfo
    tag_type: TagType
    version_info: Optional[version.Version] = None
    date_info: Optional[datetime] = None

    @property
    def name(self) -> str:
        return self.tag_info.name

    @property
    def created_at(self) -> str:
        return self.tag_info.created_at

    @property
    def digest(self) -> Optional[str]:
        return self.tag_info.digest


class TagAnalyzer:
    """Analyzes and categorizes Docker image tags."""

    SEMVER_PATTERN = re.compile(
        r'^v?(\d+\.\d+\.\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$')
    DATE_PATTERN = re.compile(r'^\d{4}(?:[-_.]\d{2}){2}(?:[-_.]?\d{2}(?:[-_.]\d{2}){2})?$')
    SHA_PATTERN = re.compile(r'^[0-9a-f]{7,40}$')

    @classmethod
    def analyze_tag(cls, tag_info: TagInfo) -> EnhancedTagInfo:
        """Analyzes a tag and returns enhanced information about it."""
        tag_name = tag_info.name.lower()

        if tag_name == "latest":
            return EnhancedTagInfo(tag_info, TagType.LATEST)

        if cls.SHA_PATTERN.match(tag_name):
            return EnhancedTagInfo(tag_info, TagType.SHA)

        if semver_match := cls.SEMVER_PATTERN.match(tag_name):
            try:
                ver = version.parse(semver_match.group(1))
                return EnhancedTagInfo(tag_info, TagType.SEMVER, version_info=ver)
            except version.InvalidVersion:
                pass

        if date_match := cls.DATE_PATTERN.match(tag_name):
            try:
                # Handle different date formats
                clean_date = re.sub(r'[-_.]', '', date_match.group(0))
                if len(clean_date) == 8:  # YYYYMMDD
                    date = datetime.strptime(clean_date, '%Y%m%d')
                else:  # YYYYMMDDhhmmss
                    date = datetime.strptime(clean_date, '%Y%m%d%H%M%S')
                return EnhancedTagInfo(tag_info, TagType.DATE, date_info=date)
            except ValueError:
                pass

        return EnhancedTagInfo(tag_info, TagType.CUSTOM)


class DockerImageUpdater:
    """Enhanced class to check for updates for local Docker images."""

    def __init__(self) -> None:
        self.local_images: Dict[str, List[Dict[str, Optional[str]]]] = {}
        self.tag_cache: Dict[str, List[EnhancedTagInfo]] = {}
        self.analyzer = TagAnalyzer()

    def initialize(self) -> None:
        """Initialize the updater by fetching local images."""
        self.local_images = self._get_local_images()

    @staticmethod
    def _get_local_images() -> Dict[str, List[Dict[str, Optional[str]]]]:
        """
        Fetches all local Docker images and their associated tags.

        Returns:
            Dict[str, List[Dict[str, Optional[str]]]]: A dictionary mapping repository names to lists of
            tag information dictionaries. Each tag dictionary contains 'tag', 'created_at', and 'digest' keys.

        Raises:
            DockerError: If there's an error communicating with Docker daemon
        """
        local_images: Dict[str, List[Dict[str, Optional[str]]]] = {}

        try:
            with DockerAdapter() as adapter:
                images = adapter.images.list(all=False)
                logger.debug(f"Found {len(images)} local Docker images")

                for image in images:
                    repo_tags = image.tags

                    if not repo_tags:
                        logger.debug(f"Skipping image without tags: {image.id[:12]}")
                        continue

                    # Extract image digest from RepoDigests or calculate from ID
                    digest = None
                    if repo_digests := image.attrs.get('RepoDigests'):
                        # Take the first digest if available
                        try:
                            digest = repo_digests[0].split('@')[1]
                        except (IndexError, ValueError):
                            logger.debug(f"Could not parse RepoDigests for image {image.id[:12]}")


                    for tag in repo_tags:
                        try:
                            repo, tag_version = tag.rsplit(":", 1) if ":" in tag else (tag, "latest")

                            # Handle creation time
                            created_at = image.attrs.get("Created")
                            if isinstance(created_at, (int, float)):
                                created_at = datetime.fromtimestamp(
                                    created_at, tz=timezone.utc
                                ).isoformat()
                            elif not isinstance(created_at, str):
                                logger.warning(f"Unexpected created_at format for {tag}: {created_at}")
                                created_at = None

                            local_images.setdefault(repo, []).append(
                                {
                                    "tag": tag_version,
                                    "created_at": created_at,
                                    "digest": digest,
                                }
                            )

                        except ValueError as e:
                            logger.warning(f"Invalid tag format '{tag}': {e}")
                            continue

        except Exception as e:
            logger.error(f"Error fetching local Docker images: {e}")
            raise

        logger.info(
            f"Successfully processed {sum(len(tags) for tags in local_images.values())} tags from {len(local_images)} repositories")
        return local_images

    async def _fetch_remote_tags(
            self, session: aiohttp.ClientSession, repo: str
    ) -> List[EnhancedTagInfo]:
        """Fetches and analyzes available tags from Docker Hub."""
        if cached_tags := self.tag_cache.get(repo):
            return cached_tags

        base_urls = [
            f"https://registry.hub.docker.com/v2/repositories/{repo}/tags/",
            f"https://registry.hub.docker.com/v2/repositories/library/{repo}/tags/",
        ]

        tags_info: List[EnhancedTagInfo] = []

        async def fetch_with_pagination(_url: str) -> None:
            try:
                while _url:
                    async with session.get(url, timeout=10) as response:
                        if response.status == 429:
                            retry_after = int(response.headers.get("Retry-After", "5"))
                            await asyncio.sleep(retry_after)
                            continue

                        response.raise_for_status()
                        data = await response.json()

                        new_tags = [
                            self.analyzer.analyze_tag(TagInfo(
                                name=result["name"],
                                created_at=result.get("tag_last_pushed", ""),
                                digest=result.get("digest")
                            ))
                            for result in data.get("results", [])
                        ]
                        tags_info.extend(new_tags)

                        _url = data.get("next")

            except (aiohttp.ClientError, json.JSONDecodeError) as e:
                logger.warning(f"Error fetching tags from {url}: {e}")

        for url in base_urls:
            await fetch_with_pagination(url)
            if tags_info:
                self.tag_cache[repo] = tags_info
                break

        return tags_info

    @staticmethod
    def _compare_versions(
            local_tag: EnhancedTagInfo, remote_tag: EnhancedTagInfo
    ) -> bool:
        """Compare two tags to determine if remote is newer."""
        if local_tag.tag_type != remote_tag.tag_type:
            return False

        if local_tag.tag_type == TagType.SEMVER:
            return remote_tag.version_info > local_tag.version_info

        if local_tag.tag_type == TagType.DATE:
            return remote_tag.date_info > local_tag.date_info

        # For other types, compare creation dates
        return isoparse(remote_tag.created_at) > isoparse(local_tag.created_at)

    async def _find_compatible_updates(
            self, local_tag: EnhancedTagInfo, remote_tags: List[EnhancedTagInfo]
    ) -> List[UpdateInfo]:
        """Find compatible updates for a given local tag."""
        updates = []

        # Filter compatible remote tags
        compatible_tags = [
            tag for tag in remote_tags
            if tag.tag_type == local_tag.tag_type
        ]

        if local_tag.tag_type == TagType.SEMVER:
            # For semver, find updates with same major version
            major_version = local_tag.version_info.major
            compatible_tags = [
                tag for tag in compatible_tags
                if tag.version_info.major == major_version
                   and self._compare_versions(local_tag, tag)
            ]

        for remote_tag in compatible_tags:
            updates.append(UpdateInfo(
                current_tag=local_tag.name,
                newer_tag=remote_tag.name,
                created_at_local=local_tag.created_at,
                created_at_remote=remote_tag.created_at,
                current_digest=remote_tag.digest
            ))

        return updates

    async def _check_updates(self) -> Dict[str, Dict[str, List[dict]]]:
        """Check for updates across all repositories."""
        updates: Dict[str, Dict[str, List[dict]]] = {}

        async with aiohttp.ClientSession() as session:
            for repo, local_tags in self.local_images.items():
                remote_tags = await self._fetch_remote_tags(session, repo)

                repo_updates = []
                for local_tag_info in local_tags:
                    local_enhanced = self.analyzer.analyze_tag(TagInfo(
                        name=local_tag_info["tag"],
                        created_at=local_tag_info["created_at"],
                        digest=local_tag_info["digest"]
                    ))

                    compatible_updates = await self._find_compatible_updates(
                        local_enhanced, remote_tags
                    )
                    repo_updates.extend(compatible_updates)

                # Sort updates by creation date and limit to 5
                repo_updates.sort(
                    key=lambda x: isoparse(x.created_at_remote),
                    reverse=True
                )
                updates[repo] = {
                    "updates": [update.to_dict() for update in repo_updates[:5]]
                }

        return updates

    def to_json(self) -> str:
        """Returns the update check result in JSON format."""
        result = asyncio.run(self._check_updates())
        return json.dumps(result, indent=4)

if __name__ == "__main__":
    updater = DockerImageUpdater()
    print(updater.to_json())
