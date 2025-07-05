import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Dict, List, Optional, TypeAlias

import aiohttp
from aiohttp import ClientTimeout
from dateutil.parser import isoparse
from packaging import version

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import BaseComponent
from pytmbot.models.docker_models import TagInfo, UpdateInfo

# Type Alias
LocalImageInfo: TypeAlias = Dict[str, List[Dict[str, Optional[str]]]]
UpdateResult: TypeAlias = Dict[str, Dict[str, List[dict]]]


class UpdaterStatus(Enum):
    SUCCESS = auto()
    RATE_LIMITED = auto()
    ERROR = auto()


@dataclass(frozen=True, slots=True)
class UpdaterResponse:
    status: UpdaterStatus
    message: str
    data: Optional[Dict] = None


class TagType(Enum):
    SEMVER = auto()
    DATE = auto()
    LATEST = auto()
    SHA = auto()
    CUSTOM = auto()


@dataclass(frozen=True, slots=True)
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
        r"^v?(\d+\.\d+\.\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
    )
    DATE_PATTERN = re.compile(
        r"^\d{4}(?:[-_.]\d{2}){2}(?:[-_.]?\d{2}(?:[-_.]\d{2}){2})?$"
    )
    SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")

    @classmethod
    def analyze_tag(cls, tag_info: TagInfo) -> EnhancedTagInfo:
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
                clean_date = re.sub(r"[-_.]", "", date_match.group(0))
                if len(clean_date) == 8:
                    date = datetime.strptime(clean_date, "%Y%m%d")
                else:
                    date = datetime.strptime(clean_date, "%Y%m%d%H%M%S")
                return EnhancedTagInfo(tag_info, TagType.DATE, date_info=date)
            except ValueError:
                pass

        return EnhancedTagInfo(tag_info, TagType.CUSTOM)


def normalize_created_at(created) -> Optional[str]:
    if isinstance(created, (int, float)):
        return datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
    if isinstance(created, str):
        return created
    return None


def dict_to_tag_info(info: dict) -> TagInfo:
    return TagInfo(
        name=info["tag"],
        created_at=info["created_at"],
        digest=info["digest"],
    )


class DockerImageUpdater(BaseComponent):
    """Enhanced class to check for updates for local Docker images."""

    def __init__(self) -> None:
        super().__init__("DockerImageUpdater")
        self.local_images: LocalImageInfo = {}
        self.tag_cache: Dict[str, List[EnhancedTagInfo]] = {}
        self.analyzer = TagAnalyzer()

    def initialize(self) -> None:
        with self._log.context(action="initialize"):
            self.local_images = self._get_local_images()

    def _get_local_images(self) -> LocalImageInfo:
        local_images: LocalImageInfo = {}

        try:
            with DockerAdapter() as adapter:
                images = adapter.images.list(all=False)
                self._log.debug(f"Found {len(images)} local Docker images")

                for image in images:
                    if not image.tags:
                        self._log.debug(f"Skipping image without tags: {image.id[:12]}")
                        continue

                    digest = self._extract_digest(image)
                    self._process_image_tags(image, digest, local_images)

        except Exception as e:
            self._log.error(f"Error fetching local Docker images: {e}")
            raise

        self._log.info(
            f"Processed {sum(len(tags) for tags in local_images.values())} tags from {len(local_images)} repositories"
        )
        return local_images

    def _extract_digest(self, image) -> Optional[str]:
        """Extract digest from image repo digests."""
        repo_digests = image.attrs.get("RepoDigests")
        if not repo_digests:
            return None

        try:
            return repo_digests[0].split("@")[1]
        except (IndexError, ValueError):
            self._log.debug(f"Could not parse digest for {image.id[:12]}")
            return None

    def _process_image_tags(
        self, image, digest: Optional[str], local_images: LocalImageInfo
    ) -> None:
        """Process all tags for a single image."""
        created_at = normalize_created_at(image.attrs.get("Created"))

        for tag in image.tags:
            try:
                repo, tag_version = self._parse_tag(tag)
                local_images.setdefault(repo, []).append(
                    {
                        "tag": tag_version,
                        "created_at": created_at,
                        "digest": digest,
                    }
                )
            except ValueError as e:
                self._log.warning(f"Invalid tag format '{tag}': {e}")

    @staticmethod
    def _parse_tag(tag: str) -> tuple[str, str]:
        """Parse tag into repository and version components."""
        return tag.rsplit(":", 1) if ":" in tag else (tag, "latest")

    async def _fetch_remote_tags(
        self, session: aiohttp.ClientSession, repo: str
    ) -> List[EnhancedTagInfo]:
        with self._log.context(action="fetch_remote_tags", repository=repo):
            if cached_tags := self.tag_cache.get(repo):
                self._log.debug(f"Using cached tags for {repo}")
                return cached_tags

            base_urls = [
                f"https://registry.hub.docker.com/v2/repositories/{repo}/tags/",
                f"https://registry.hub.docker.com/v2/repositories/library/{repo}/tags/",
            ]

            tags_info: List[EnhancedTagInfo] = []

            async def fetch_tags(_url: str) -> Optional[bool]:
                try:
                    async with session.get(_url, timeout=ClientTimeout(10)) as response:
                        if response.status == 429:
                            retry_after = int(
                                response.headers.get("Retry-After", "3600")
                            )
                            raise aiohttp.ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=429,
                                message=f"Rate limit exceeded, retry after {retry_after}",
                            )

                        response.raise_for_status()
                        data = await response.json()
                        results = data.get("results", [])

                        tags_info.extend(
                            [
                                self.analyzer.analyze_tag(
                                    TagInfo(
                                        name=entry["name"],
                                        created_at=entry.get("tag_last_pushed", ""),
                                        digest=entry.get("digest"),
                                    )
                                )
                                for entry in results
                            ]
                        )
                        self._log.debug(f"Fetched {len(results)} tags from {_url}")
                        return True

                except aiohttp.ClientResponseError as e:
                    if e.status == 429:
                        raise
                    self._log.warning(f"Failed to fetch tags from {_url}: {e}")
                except (aiohttp.ClientError, json.JSONDecodeError) as e:
                    self._log.warning(f"Fetch error from {_url}: {e}")

                return None

            for url in base_urls:
                await fetch_tags(url)
                if tags_info:
                    self.tag_cache[repo] = tags_info
                    break

            return tags_info

    @staticmethod
    def _compare_versions(
        local_tag: EnhancedTagInfo, remote_tag: EnhancedTagInfo
    ) -> bool:
        if local_tag.tag_type != remote_tag.tag_type:
            return False
        if local_tag.tag_type == TagType.SEMVER:
            return remote_tag.version_info > local_tag.version_info
        if local_tag.tag_type == TagType.DATE:
            return remote_tag.date_info > local_tag.date_info
        return isoparse(remote_tag.created_at) > isoparse(local_tag.created_at)

    def _find_compatible_updates(
        self, local_tag: EnhancedTagInfo, remote_tags: List[EnhancedTagInfo]
    ) -> List[UpdateInfo]:
        with self._log.context(
            action="find_updates", tag=local_tag.name, tag_type=local_tag.tag_type.name
        ):
            compatible_tags = [
                tag for tag in remote_tags if tag.tag_type == local_tag.tag_type
            ]

            if local_tag.tag_type == TagType.SEMVER:
                compatible_tags = [
                    tag
                    for tag in compatible_tags
                    if tag.version_info.major == local_tag.version_info.major
                    and self._compare_versions(local_tag, tag)
                ]
            else:
                compatible_tags = [
                    tag
                    for tag in compatible_tags
                    if self._compare_versions(local_tag, tag)
                ]

            return [
                UpdateInfo(
                    current_tag=local_tag.name,
                    newer_tag=tag.name,
                    created_at_local=local_tag.created_at,
                    created_at_remote=tag.created_at,
                    current_digest=tag.digest,
                )
                for tag in compatible_tags
            ]

    async def _check_updates(self) -> UpdaterResponse:
        with self._log.context(action="check_updates"):
            try:
                async with aiohttp.ClientSession(timeout=ClientTimeout(10)) as session:
                    updates = {}

                    for repo, local_tags in self.local_images.items():
                        try:
                            remote_tags = await self._fetch_remote_tags(session, repo)
                        except aiohttp.ClientResponseError as e:
                            if e.status == 429:
                                return UpdaterResponse(
                                    status=UpdaterStatus.RATE_LIMITED,
                                    message="Docker Hub API rate limit exceeded.",
                                    data={"retry_after": "3600"},
                                )
                            raise

                        repo_updates = []
                        for tag_dict in local_tags:
                            local_tag = self.analyzer.analyze_tag(
                                dict_to_tag_info(tag_dict)
                            )
                            updates_found = self._find_compatible_updates(
                                local_tag, remote_tags
                            )
                            repo_updates.extend(updates_found)

                        repo_updates.sort(
                            key=lambda x: isoparse(x.created_at_remote), reverse=True
                        )
                        updates[repo] = {
                            "updates": [u.to_dict() for u in repo_updates[:5]]
                        }

                    return UpdaterResponse(
                        status=UpdaterStatus.SUCCESS,
                        message="Successfully checked for updates",
                        data=updates,
                    )

            except Exception as e:
                self._log.error(f"Error checking for updates: {e}")
                return UpdaterResponse(
                    status=UpdaterStatus.ERROR,
                    message=f"Error checking for updates: {e}",
                )

    def to_json(self) -> str:
        with self._log.context(action="to_json"):
            result = asyncio.run(self._check_updates())
            return json.dumps(
                {
                    "status": result.status.name,
                    "message": result.message,
                    "data": result.data,
                },
                indent=4,
            )


if __name__ == "__main__":
    updater = DockerImageUpdater()
    print(updater.to_json())
