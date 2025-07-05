import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum, auto
from typing import Dict, List, Optional, TypeAlias

import aiohttp
from aiohttp import ClientTimeout
from dateutil.parser import isoparse
from packaging import version

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import BaseComponent
from pytmbot.models.docker_models import TagInfo, UpdateInfo

# Type Aliases
LocalImageInfo: TypeAlias = Dict[str, List[Dict[str, Optional[str]]]]
UpdateResult: TypeAlias = Dict[str, Dict[str, List[dict]]]


class UpdaterStatus(Enum):
    SUCCESS = auto()
    RATE_LIMITED = auto()
    ERROR = auto()
    PARTIAL_SUCCESS = auto()


@dataclass(frozen=True, slots=True)
class UpdaterResponse:
    status: UpdaterStatus
    message: str
    data: Optional[Dict] = None
    metrics: Optional[Dict] = None


@dataclass(frozen=True, slots=True)
class UpdaterConfig:
    max_concurrent_requests: int = 5
    request_timeout: int = 10
    cache_ttl_hours: int = 1
    max_retries: int = 3
    include_prereleases: bool = False
    max_updates_per_repo: int = 5
    only_stable_versions: bool = True
    retry_delay: float = 1.0
    max_retry_delay: float = 60.0


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
    is_stable: bool = True

    @property
    def name(self) -> str:
        return self.tag_info.name

    @property
    def created_at(self) -> str:
        return self.tag_info.created_at

    @property
    def digest(self) -> Optional[str]:
        return self.tag_info.digest


@dataclass
class CachedTags:
    tags: List[EnhancedTagInfo]
    cached_at: datetime
    ttl: timedelta

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.cached_at > self.ttl


@dataclass
class UpdaterMetrics:
    total_repositories: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    rate_limited_checks: int = 0
    total_updates_found: int = 0
    execution_time: float = 0.0
    cached_requests: int = 0
    api_requests: int = 0


class RegistryAdapter(ABC):
    """Abstract adapter for working with various container registries."""

    def __init__(self, name: str, base_url: str):
        self.name = name
        self.base_url = base_url

    @abstractmethod
    async def fetch_tags(
        self, session: aiohttp.ClientSession, repo: str
    ) -> List[TagInfo]:
        """Retrieve the list of tags for a repository."""
        pass

    @abstractmethod
    def get_repository_urls(self, repo: str) -> List[str]:
        """Get a list of URLs to check for a given repository."""
        pass


class DockerHubAdapter(RegistryAdapter):
    """Adapter for Docker Hub."""

    def __init__(self):
        super().__init__("Docker Hub", "https://registry.hub.docker.com")

    def get_repository_urls(self, repo: str) -> List[str]:
        return [
            f"{self.base_url}/v2/repositories/{repo}/tags/",
            f"{self.base_url}/v2/repositories/library/{repo}/tags/",
        ]

    async def fetch_tags(
        self, session: aiohttp.ClientSession, repo: str
    ) -> List[TagInfo]:
        """Fetch tags from Docker Hub."""
        urls = self.get_repository_urls(repo)

        for url in urls:
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", "3600"))
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=429,
                            message=f"Rate limit exceeded, retry after {retry_after} seconds",
                        )

                    response.raise_for_status()
                    data = await response.json()

                    return [
                        TagInfo(
                            name=result["name"],
                            created_at=result.get("tag_last_pushed", ""),
                            digest=result.get("digest"),
                        )
                        for result in data.get("results", [])
                    ]

            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    raise
                continue
            except (aiohttp.ClientError, json.JSONDecodeError):
                continue

        return []


class TagAnalyzer:
    """Analyzes and categorizes Docker image tags."""

    SEMVER_PATTERN = re.compile(
        r"^v?(\d+\.\d+\.\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
    )
    DATE_PATTERN = re.compile(
        r"^\d{4}(?:[-_.]\d{2}){2}(?:[-_.]?\d{2}(?:[-_.]\d{2}){2})?$"
    )
    SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
    UNSTABLE_MARKERS = ["alpha", "beta", "rc", "dev", "snapshot", "pre", "test"]

    @classmethod
    def analyze_tag(cls, tag_info: TagInfo) -> EnhancedTagInfo:
        """Analyzes a tag and returns extended information about it."""
        tag_name = tag_info.name.lower()
        is_stable = not any(marker in tag_name for marker in cls.UNSTABLE_MARKERS)

        if tag_name == "latest":
            return EnhancedTagInfo(tag_info, TagType.LATEST, is_stable=is_stable)

        if cls.SHA_PATTERN.match(tag_name):
            return EnhancedTagInfo(tag_info, TagType.SHA, is_stable=is_stable)

        if semver_match := cls.SEMVER_PATTERN.match(tag_name):
            try:
                ver = version.parse(semver_match.group(1))
                return EnhancedTagInfo(
                    tag_info, TagType.SEMVER, version_info=ver, is_stable=is_stable
                )
            except version.InvalidVersion:
                pass

        if date_match := cls.DATE_PATTERN.match(tag_name):
            try:
                clean_date = re.sub(r"[-_.]", "", date_match.group(0))
                if len(clean_date) == 8:  # YYYYMMDD
                    date = datetime.strptime(clean_date, "%Y%m%d")
                else:  # YYYYMMDDhhmmss
                    date = datetime.strptime(clean_date, "%Y%m%d%H%M%S")
                return EnhancedTagInfo(
                    tag_info, TagType.DATE, date_info=date, is_stable=is_stable
                )
            except ValueError:
                pass

        return EnhancedTagInfo(tag_info, TagType.CUSTOM, is_stable=is_stable)

    @classmethod
    def is_patch_update(
        cls, local_tag: EnhancedTagInfo, remote_tag: EnhancedTagInfo
    ) -> bool:
        """Checks whether the update is a patch-level update."""
        if (
            local_tag.tag_type != TagType.SEMVER
            or remote_tag.tag_type != TagType.SEMVER
        ):
            return False

        local_ver = local_tag.version_info
        remote_ver = remote_tag.version_info

        return (
            local_ver.major == remote_ver.major
            and local_ver.minor == remote_ver.minor
            and remote_ver.micro > local_ver.micro
        )

    @classmethod
    def is_security_update(cls, remote_tag: EnhancedTagInfo) -> bool:
        """Checks whether the update is related to security."""
        security_markers = ["security", "sec", "cve", "vuln", "fix"]
        tag_name = remote_tag.name.lower()
        return any(marker in tag_name for marker in security_markers)


class DockerImageUpdater(BaseComponent):
    """Advanced class for checking updates of local Docker images."""

    def __init__(self, config: Optional[UpdaterConfig] = None) -> None:
        super().__init__("DockerImageUpdater")
        self.config = config or UpdaterConfig()
        self.local_images: LocalImageInfo = {}
        self.tag_cache: Dict[str, CachedTags] = {}
        self.analyzer = TagAnalyzer()
        self.metrics = UpdaterMetrics()

        self.registry_adapters = [
            DockerHubAdapter(),
        ]

    def initialize(self) -> None:
        """Initializes the updater by retrieving local Docker images."""
        with self._log.context(action="initialize"):
            start_time = time.time()
            self.local_images = self._get_local_images()
            init_time = time.time() - start_time

            self._log.info(
                f"Initialized with {len(self.local_images)} repositories",
                extra={
                    "total_repositories": len(self.local_images),
                    "total_tags": sum(len(tags) for tags in self.local_images.values()),
                    "initialization_time": round(init_time, 2),
                },
            )

    @staticmethod
    def _validate_repo_name(repo: str) -> bool:
        """Validates the repository name."""
        if not repo or len(repo) > 255:
            return False

        pattern = re.compile(r"^[a-zA-Z0-9._/-]+$")
        return bool(pattern.match(repo))

    def _get_local_images(self) -> LocalImageInfo:
        """
        Retrieves all local Docker images and their associated tags.

        Returns:
            LocalImageInfo: A dictionary mapping repository names to lists of tag info.
        """
        local_images: LocalImageInfo = {}

        try:
            with DockerAdapter() as adapter:
                images = adapter.images.list(all=False)
                self._log.debug(f"Found {len(images)} local Docker images")

                for image in images:
                    repo_tags = image.tags

                    if not repo_tags:
                        self._log.debug(f"Skipping image without tags: {image.id[:12]}")
                        continue

                    digest = None
                    if repo_digests := image.attrs.get("RepoDigests"):
                        try:
                            digest = repo_digests[0].split("@")[1]
                        except (IndexError, ValueError):
                            self._log.debug(
                                f"Could not parse RepoDigests for image {image.id[:12]}"
                            )

                    for tag in repo_tags:
                        try:
                            repo, tag_version = (
                                tag.rsplit(":", 1) if ":" in tag else (tag, "latest")
                            )

                            # Validate repository name
                            if not self._validate_repo_name(repo):
                                self._log.warning(f"Invalid repository name: {repo}")
                                continue

                            created_at = image.attrs.get("Created")
                            if isinstance(created_at, (int, float)):
                                created_at = datetime.fromtimestamp(
                                    created_at, tz=timezone.utc
                                ).isoformat()
                            elif not isinstance(created_at, str):
                                self._log.warning(
                                    f"Unexpected created_at format for {tag}: {created_at}"
                                )
                                created_at = None

                            local_images.setdefault(repo, []).append(
                                {
                                    "tag": tag_version,
                                    "created_at": created_at,
                                    "digest": digest,
                                }
                            )

                        except ValueError as e:
                            self._log.warning(f"Invalid tag format '{tag}': {e}")
                            continue

        except Exception as e:
            self._log.error(f"Error fetching local Docker images: {e}")
            raise

        return local_images

    async def _fetch_remote_tags_with_retry(
        self, session: aiohttp.ClientSession, repo: str
    ) -> List[EnhancedTagInfo]:
        """Fetches remote tags with retry mechanism."""
        cache_key = repo

        # Check cache
        if cached_tags := self.tag_cache.get(cache_key):
            if not cached_tags.is_expired:
                self.metrics.cached_requests += 1
                self._log.debug(f"Using cached tags for repository {repo}")
                return cached_tags.tags

        # Try fetching tags using registry adapters
        for adapter in self.registry_adapters:
            for attempt in range(self.config.max_retries):
                try:
                    self.metrics.api_requests += 1
                    tags_info = await adapter.fetch_tags(session, repo)

                    if tags_info:
                        enhanced_tags = [
                            self.analyzer.analyze_tag(tag) for tag in tags_info
                        ]

                        if self.config.only_stable_versions:
                            enhanced_tags = [
                                tag for tag in enhanced_tags if tag.is_stable
                            ]

                        # Cache the result
                        self.tag_cache[cache_key] = CachedTags(
                            tags=enhanced_tags,
                            cached_at=datetime.now(timezone.utc),
                            ttl=timedelta(hours=self.config.cache_ttl_hours),
                        )

                        self._log.debug(
                            f"Successfully fetched {len(enhanced_tags)} tags for {repo} from {adapter.name}"
                        )
                        return enhanced_tags

                except aiohttp.ClientResponseError as e:
                    if e.status == 429:
                        self.metrics.rate_limited_checks += 1
                        raise

                    if attempt < self.config.max_retries - 1:
                        delay = min(
                            self.config.retry_delay * (2**attempt),
                            self.config.max_retry_delay,
                        )
                        self._log.warning(
                            f"Request failed for {repo} (attempt {attempt + 1}), retrying in {delay}s: {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        self._log.error(
                            f"Failed to fetch tags for {repo} after {self.config.max_retries} attempts: {e}"
                        )

                except Exception as e:
                    self._log.warning(f"Unexpected error fetching tags for {repo}: {e}")
                    break

        return []

    @staticmethod
    def _compare_versions(
        local_tag: EnhancedTagInfo, remote_tag: EnhancedTagInfo
    ) -> bool:
        """Compares two tags to determine if the remote one is newer."""
        if local_tag.tag_type != remote_tag.tag_type:
            return False

        if local_tag.tag_type == TagType.SEMVER:
            return remote_tag.version_info > local_tag.version_info

        if local_tag.tag_type == TagType.DATE:
            return remote_tag.date_info > local_tag.date_info

        # Fallback: compare creation timestamps
        if local_tag.created_at and remote_tag.created_at:
            return isoparse(remote_tag.created_at) > isoparse(local_tag.created_at)

        return False

    def _prioritize_updates(self, updates: List[UpdateInfo]) -> List[UpdateInfo]:
        """Prioritizes updates based on importance."""

        def priority_key(update: UpdateInfo) -> tuple:
            temp_tag = EnhancedTagInfo(
                tag_info=TagInfo(
                    name=update.newer_tag,
                    created_at=update.created_at_remote,
                    digest=update.current_digest,
                ),
                tag_type=TagType.CUSTOM,
            )

            is_security = self.analyzer.is_security_update(temp_tag)
            is_patch = "patch" in update.newer_tag.lower()

            return is_security, is_patch, update.created_at_remote

        return sorted(updates, key=priority_key, reverse=True)

    async def _find_compatible_updates(
        self, local_tag: EnhancedTagInfo, remote_tags: List[EnhancedTagInfo]
    ) -> List[UpdateInfo]:
        """Finds compatible updates for a given local tag."""
        updates = []
        compatible_tags = [
            tag for tag in remote_tags if tag.tag_type == local_tag.tag_type
        ]

        if local_tag.tag_type == TagType.SEMVER:
            major_version = local_tag.version_info.major
            compatible_tags = [
                tag
                for tag in compatible_tags
                if tag.version_info.major == major_version
                and self._compare_versions(local_tag, tag)
            ]

        for remote_tag in compatible_tags:
            if self._compare_versions(local_tag, remote_tag):
                updates.append(
                    UpdateInfo(
                        current_tag=local_tag.name,
                        newer_tag=remote_tag.name,
                        created_at_local=local_tag.created_at,
                        created_at_remote=remote_tag.created_at,
                        current_digest=remote_tag.digest,
                    )
                )

        return updates

    async def _check_repository_updates(
        self, session: aiohttp.ClientSession, repo: str, local_tags: List[Dict]
    ) -> List[UpdateInfo]:
        """Checks for updates for a specific repository."""
        try:
            remote_tags = await self._fetch_remote_tags_with_retry(session, repo)
            if not remote_tags:
                return []

            repo_updates = []
            for local_tag_info in local_tags:
                local_enhanced = self.analyzer.analyze_tag(
                    TagInfo(
                        name=local_tag_info["tag"],
                        created_at=local_tag_info["created_at"],
                        digest=local_tag_info["digest"],
                    )
                )

                compatible_updates = await self._find_compatible_updates(
                    local_enhanced, remote_tags
                )
                repo_updates.extend(compatible_updates)

            # Prioritize and limit the number of updates
            repo_updates = self._prioritize_updates(repo_updates)
            repo_updates = repo_updates[: self.config.max_updates_per_repo]

            self.metrics.successful_checks += 1
            self.metrics.total_updates_found += len(repo_updates)

            return repo_updates

        except aiohttp.ClientResponseError as e:
            if e.status == 429:
                raise
            self.metrics.failed_checks += 1
            self._log.error(f"Failed to check updates for {repo}: {e}")
            return []

        except Exception as e:
            self.metrics.failed_checks += 1
            self._log.error(f"Unexpected error checking updates for {repo}: {e}")
            return []

    async def _check_updates(self) -> UpdaterResponse:
        """Checks for updates across all repositories."""
        start_time = time.time()

        with self._log.context(action="check_updates"):
            try:
                self.metrics = UpdaterMetrics()
                self.metrics.total_repositories = len(self.local_images)

                semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
                timeout = ClientTimeout(total=self.config.request_timeout)

                async with aiohttp.ClientSession(timeout=timeout) as session:

                    async def check_repo(repo: str, local_tags: List[Dict]) -> tuple:
                        async with semaphore:
                            updates = await self._check_repository_updates(
                                session, repo, local_tags
                            )
                            return repo, updates

                    tasks = [
                        check_repo(repo, local_tags)
                        for repo, local_tags in self.local_images.items()
                    ]

                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    updates = {}
                    has_rate_limit = False

                    for result in results:
                        if isinstance(result, Exception):
                            if (
                                isinstance(result, aiohttp.ClientResponseError)
                                and result.status == 429
                            ):
                                has_rate_limit = True
                            continue

                        repo, repo_updates = result
                        updates[repo] = {
                            "updates": [update.to_dict() for update in repo_updates]
                        }

                self.metrics.execution_time = time.time() - start_time
                self._log_metrics()

                if has_rate_limit:
                    status = UpdaterStatus.RATE_LIMITED
                    message = (
                        "Some checks were rate limited. Results may be incomplete."
                    )
                elif self.metrics.failed_checks > 0:
                    status = UpdaterStatus.PARTIAL_SUCCESS
                    message = f"Completed with {self.metrics.failed_checks} failures"
                else:
                    status = UpdaterStatus.SUCCESS
                    message = "Successfully checked for updates"

                return UpdaterResponse(
                    status=status,
                    message=message,
                    data=updates,
                    metrics=self._get_metrics_dict(),
                )

            except Exception as e:
                self.metrics.execution_time = time.time() - start_time
                self._log.error(f"Error checking for updates: {e}")
                return UpdaterResponse(
                    status=UpdaterStatus.ERROR,
                    message=f"Error checking for updates: {str(e)}",
                    metrics=self._get_metrics_dict(),
                )

    def _log_metrics(self) -> None:
        """Logs execution metrics."""
        self._log.info(
            "Update check completed",
            extra={
                "total_repositories": self.metrics.total_repositories,
                "successful_checks": self.metrics.successful_checks,
                "failed_checks": self.metrics.failed_checks,
                "rate_limited_checks": self.metrics.rate_limited_checks,
                "total_updates_found": self.metrics.total_updates_found,
                "execution_time": round(self.metrics.execution_time, 2),
                "cached_requests": self.metrics.cached_requests,
                "api_requests": self.metrics.api_requests,
                "cache_hit_rate": round(
                    self.metrics.cached_requests
                    / max(1, self.metrics.cached_requests + self.metrics.api_requests)
                    * 100,
                    2,
                ),
            },
        )

    def _get_metrics_dict(self) -> Dict:
        """Returns metrics as a dictionary."""
        return {
            "total_repositories": self.metrics.total_repositories,
            "successful_checks": self.metrics.successful_checks,
            "failed_checks": self.metrics.failed_checks,
            "rate_limited_checks": self.metrics.rate_limited_checks,
            "total_updates_found": self.metrics.total_updates_found,
            "execution_time": round(self.metrics.execution_time, 2),
            "cached_requests": self.metrics.cached_requests,
            "api_requests": self.metrics.api_requests,
            "cache_hit_rate": round(
                self.metrics.cached_requests
                / max(1, self.metrics.cached_requests + self.metrics.api_requests)
                * 100,
                2,
            ),
        }

    def clear_cache(self) -> None:
        """Clears the tag cache."""
        self.tag_cache.clear()
        self._log.info("Tag cache cleared")

    def get_cache_stats(self) -> Dict:
        """Returns cache statistics."""
        total_entries = len(self.tag_cache)
        expired_entries = sum(
            1 for cache_entry in self.tag_cache.values() if cache_entry.is_expired
        )

        return {
            "total_entries": total_entries,
            "expired_entries": expired_entries,
            "active_entries": total_entries - expired_entries,
        }

    def to_json(self) -> str:
        """
        Returns the update check results as a JSON string.

        Returns:
            str: JSON string with update results or error information.
        """
        with self._log.context(action="to_json"):
            result = asyncio.run(self._check_updates())
            return json.dumps(
                {
                    "status": result.status.name,
                    "message": result.message,
                    "data": result.data,
                    "metrics": result.metrics,
                },
                indent=4,
            )
