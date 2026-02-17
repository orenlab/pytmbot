#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import asyncio
import json
import re
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from threading import RLock
from typing import Any, Final

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout
from dateutil.parser import ParserError, isoparse  # type: ignore[import-untyped]
from packaging import version
from packaging.version import InvalidVersion

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.logs import BaseComponent
from pytmbot.models.docker_models import TagInfo, UpdateInfo
from pytmbot.utils import sanitize_exception

# Type Aliases
type LocalImageInfo = dict[str, list[dict[str, str | None]]]
type UpdateResult = dict[str, dict[str, list[dict]]]

# Module constants for better maintainability
DEFAULT_TIMEOUT: Final[int] = 15
MAX_TIMEOUT: Final[int] = 60
MAX_RETRIES: Final[int] = 3  # Only for transient errors (5xx, timeouts, network issues)
RATE_LIMIT_BACKOFF: Final[int] = 300  # 5 minutes
CACHE_TTL: Final[int] = 3600  # 1 hour
MAX_CONCURRENT_REPOS: Final[int] = 5
MAX_TAGS_PER_REPO: Final[int] = 100
MAX_UPDATES_PER_REPO: Final[int] = 10

# HTTP status codes that should NOT be retried (client errors)
NON_RETRYABLE_STATUS_CODES: Final[set[int]] = {
    400,  # Bad Request - malformed request
    401,  # Unauthorized - authentication required
    403,  # Forbidden - access denied
    404,  # Not Found - repository doesn't exist
    405,  # Method Not Allowed
    406,  # Not Acceptable
    410,  # Gone - resource permanently removed
    422,  # Unprocessable Entity - validation failed
}


class UpdaterStatus(Enum):
    """Enhanced status enumeration with more granular states."""

    SUCCESS = auto()
    PARTIAL_SUCCESS = auto()
    RATE_LIMITED = auto()
    NETWORK_ERROR = auto()
    DOCKER_ERROR = auto()
    VALIDATION_ERROR = auto()
    ERROR = auto()

    @property
    def is_success(self) -> bool:
        """Check if status indicates successful operation."""
        return self in {self.SUCCESS, self.PARTIAL_SUCCESS}

    @property
    def is_error(self) -> bool:
        """Check if status indicates error condition."""
        return self in {
            self.NETWORK_ERROR,
            self.DOCKER_ERROR,
            self.VALIDATION_ERROR,
            self.ERROR,
        }


@dataclass(frozen=True, slots=True)
class UpdaterResponse:
    """Enhanced response with additional metadata."""

    status: UpdaterStatus
    message: str
    data: dict | None = None
    metadata: dict | None = field(default_factory=dict)
    execution_time: float | None = None
    repositories_processed: int = 0
    repositories_failed: int = 0

    def to_dict(self) -> dict:
        """Convert response to dictionary for serialization."""
        return {
            "status": self.status.name,
            "message": self.message,
            "data": self.data,
            "metadata": self.metadata,
            "execution_time": self.execution_time,
            "repositories_processed": self.repositories_processed,
            "repositories_failed": self.repositories_failed,
        }


class TagType(Enum):
    """Enhanced tag type classification."""

    SEMVER = auto()
    DATE = auto()
    LATEST = auto()
    SHA = auto()
    CUSTOM = auto()
    INVALID = auto()

    @property
    def is_versionable(self) -> bool:
        """Check if tag type supports version comparison."""
        return self in {self.SEMVER, self.DATE}

    @property
    def priority(self) -> int:
        """Get priority for update comparison (higher is better)."""
        return {
            self.SEMVER: 100,
            self.DATE: 80,
            self.LATEST: 60,
            self.SHA: 40,
            self.CUSTOM: 20,
            self.INVALID: 0,
        }.get(self, 0)


@dataclass(frozen=True, slots=True)
class EnhancedTagInfo:
    """Enhanced tag information with validation and comparison support."""

    tag_info: TagInfo
    tag_type: TagType
    version_info: version.Version | None = None
    date_info: datetime | None = None
    parse_error: str | None = None

    @property
    def name(self) -> str:
        return self.tag_info.name

    @property
    def created_at(self) -> str:
        return self.tag_info.created_at

    @property
    def digest(self) -> str | None:
        return self.tag_info.digest

    @property
    def is_valid(self) -> bool:
        """Check if tag information is valid for comparison."""
        return self.tag_type != TagType.INVALID and not self.parse_error

    def __lt__(self, other: "EnhancedTagInfo") -> bool:
        """Enhanced comparison for sorting."""
        if not isinstance(other, EnhancedTagInfo):
            return NotImplemented

        # Compare by type priority first
        if self.tag_type.priority != other.tag_type.priority:
            return self.tag_type.priority < other.tag_type.priority

        # Same type comparison
        if self.tag_type == TagType.SEMVER and self.version_info and other.version_info:
            return self.version_info < other.version_info
        elif self.tag_type == TagType.DATE and self.date_info and other.date_info:
            return self.date_info < other.date_info
        else:
            # Fall back to creation time comparison
            try:
                left_date = isoparse(self.created_at)
                right_date = isoparse(other.created_at)
                if isinstance(left_date, datetime) and isinstance(right_date, datetime):
                    return left_date < right_date
                return self.name < other.name
            except (ParserError, ValueError):
                return self.name < other.name


class TagAnalyzer:
    """Enhanced analyzer with better pattern matching and validation."""

    # Enhanced regex patterns with more comprehensive matching
    SEMVER_PATTERN = re.compile(
        r"^v?(\d+\.\d+\.\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
    )
    DATE_PATTERN = re.compile(
        r"^(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})(?:[-_.]?(\d{2})[-_.]?(\d{2})[-_.]?(\d{2}))?$"
    )
    SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")

    # Additional patterns for common tag formats
    NUMERIC_PATTERN = re.compile(r"^\d+(\.\d+)*$")
    RELEASE_PATTERN = re.compile(
        r"^(release|rel|r)[-_.]?v?(\d+(?:\.\d+)*)$", re.IGNORECASE
    )

    @classmethod
    def analyze_tag(cls, tag_info: TagInfo) -> EnhancedTagInfo:
        """Enhanced tag analysis with comprehensive error handling."""
        if not tag_info or not tag_info.name:
            return EnhancedTagInfo(
                tag_info=tag_info,
                tag_type=TagType.INVALID,
                parse_error="Empty or invalid tag info",
            )

        tag_name = tag_info.name.strip()
        if not tag_name:
            return EnhancedTagInfo(
                tag_info=tag_info,
                tag_type=TagType.INVALID,
                parse_error="Empty tag name",
            )

        tag_lower = tag_name.lower()

        try:
            # Latest tag
            if tag_lower in {"latest", "current", "stable", "main", "master"}:
                return EnhancedTagInfo(tag_info, TagType.LATEST)

            # SHA pattern
            if cls.SHA_PATTERN.match(tag_lower):
                return EnhancedTagInfo(tag_info, TagType.SHA)

            # SEMVER pattern
            if semver_match := cls.SEMVER_PATTERN.match(tag_name):
                try:
                    ver = version.parse(semver_match.group(1))
                    return EnhancedTagInfo(tag_info, TagType.SEMVER, version_info=ver)
                except InvalidVersion as e:
                    return EnhancedTagInfo(
                        tag_info, TagType.CUSTOM, parse_error=f"Invalid semver: {e}"
                    )

            # Release pattern (e.g., release-1.2.3, rel1.0)
            if release_match := cls.RELEASE_PATTERN.match(tag_name):
                try:
                    ver = version.parse(release_match.group(2))
                    return EnhancedTagInfo(tag_info, TagType.SEMVER, version_info=ver)
                except InvalidVersion:
                    pass

            # Numeric pattern (e.g., 1.2.3, 1.0)
            if cls.NUMERIC_PATTERN.match(tag_name):
                try:
                    ver = version.parse(tag_name)
                    return EnhancedTagInfo(tag_info, TagType.SEMVER, version_info=ver)
                except InvalidVersion:
                    pass

            # Date pattern
            if date_match := cls.DATE_PATTERN.match(tag_name):
                try:
                    groups = date_match.groups()
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])

                    # Validate date ranges
                    if not (
                        2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31
                    ):
                        raise ValueError("Date out of valid range")

                    if groups[3] and groups[4] and groups[5]:  # Has time
                        hour, minute, second = (
                            int(groups[3]),
                            int(groups[4]),
                            int(groups[5]),
                        )
                        if not (
                            0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59
                        ):
                            raise ValueError("Time out of valid range")
                        date_obj = datetime(
                            year, month, day, hour, minute, second, tzinfo=UTC
                        )
                    else:
                        date_obj = datetime(year, month, day, tzinfo=UTC)

                    return EnhancedTagInfo(tag_info, TagType.DATE, date_info=date_obj)

                except (ValueError, OverflowError) as e:
                    return EnhancedTagInfo(
                        tag_info, TagType.CUSTOM, parse_error=f"Invalid date: {e}"
                    )

            # Default to custom
            return EnhancedTagInfo(tag_info, TagType.CUSTOM)

        except Exception as e:
            return EnhancedTagInfo(
                tag_info, TagType.INVALID, parse_error=f"Analysis error: {e}"
            )


def normalize_created_at(created: Any) -> str | None:
    """Enhanced timestamp normalization with validation."""
    try:
        if isinstance(created, (int, float)):
            # Validate timestamp range (1970 to 2100)
            if not (0 <= created <= 4102444800):  # 2100-01-01
                return None
            return datetime.fromtimestamp(created, tz=UTC).isoformat()
        elif isinstance(created, str):
            if created.strip():
                # Validate ISO format
                try:
                    parsed_date = isoparse(created)
                    if isinstance(parsed_date, datetime):
                        return parsed_date.isoformat()
                    return str(parsed_date)
                except (ParserError, ValueError):
                    return created  # Return as-is if can't parse
            return None
        return None
    except Exception:
        return None


def dict_to_tag_info(info: dict) -> TagInfo:
    """Enhanced conversion with validation."""
    if not isinstance(info, dict):
        raise ValueError("Info must be a dictionary")

    required_fields = ["tag", "created_at", "digest"]
    for field_name in required_fields:
        if field_name not in info:
            raise ValueError(f"Missing required field: {field_name}")

    return TagInfo(
        name=str(info["tag"]) if info["tag"] is not None else "",
        created_at=info["created_at"] or "",
        digest=info["digest"],
    )


class RateLimitHandler:
    """Handle Docker Hub rate limiting with intelligent backoff."""

    def __init__(self) -> None:
        self._last_rate_limit: float = 0.0
        self._consecutive_limits: int = 0
        self._lock = RLock()

    def should_skip_request(self) -> bool:
        """Check if we should skip requests due to rate limiting."""
        with self._lock:
            if self._consecutive_limits > 5:  # Too many consecutive limits
                return time.time() - self._last_rate_limit < RATE_LIMIT_BACKOFF * 2
            return time.time() - self._last_rate_limit < RATE_LIMIT_BACKOFF

    def handle_rate_limit(self, retry_after: int | None = None) -> None:
        """Record rate limit event."""
        with self._lock:
            self._last_rate_limit = time.time()
            self._consecutive_limits += 1

    def handle_success(self) -> None:
        """Record successful request."""
        with self._lock:
            self._consecutive_limits = 0


class DockerImageUpdater(BaseComponent):
    """
    Enhanced Docker image updater with comprehensive error handling,
    rate limiting, and performance optimizations.
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        super().__init__("DockerImageUpdater")

        # Validate timeout
        if not isinstance(timeout, int) or timeout <= 0:
            timeout = DEFAULT_TIMEOUT
        self._timeout = min(timeout, MAX_TIMEOUT)

        self.local_images: LocalImageInfo = {}
        self.tag_cache: dict[str, tuple[list[EnhancedTagInfo], float]] = {}
        self.analyzer = TagAnalyzer()
        self.rate_limiter = RateLimitHandler()
        self._cache_lock = RLock()

        # Performance metrics
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "api_calls": 0,
            "rate_limits": 0,
            "errors": 0,
        }

    def initialize(self) -> None:
        """Initialize with enhanced error handling."""
        start_time = time.time()

        with self._log.context(action="initialize"):
            try:
                self.local_images = self._get_local_images()
                execution_time = time.time() - start_time

                self._log.info(
                    "docker.updates.image.updater.ok",
                    execution_time=f"{execution_time:.2f}s",
                    repositories_count=len(self.local_images),
                    total_tags=sum(len(tags) for tags in self.local_images.values()),
                )

            except Exception as e:
                execution_time = time.time() - start_time
                self._log.error(
                    "docker.updates.initialize.image.fail",
                    error=sanitize_exception(e),
                    execution_time=f"{execution_time:.2f}s",
                )
                raise

    def _get_local_images(self) -> LocalImageInfo:
        """Enhanced local image retrieval with better error handling."""
        local_images: LocalImageInfo = {}
        processed_count = 0
        skipped_count = 0

        try:
            with DockerAdapter() as adapter:
                images = adapter.images.list(all=False)
                self._log.debug("docker.updates.found.local.debug")

                for image in images:
                    try:
                        if not image.tags:
                            skipped_count += 1
                            self._log.debug(
                                "docker.updates.skipping.image.debug"
                            )
                            continue

                        digest = self._extract_digest(image)
                        self._process_image_tags(image, digest, local_images)
                        processed_count += 1

                    except Exception as e:
                        skipped_count += 1
                        self._log.warning(
                            "docker.updates.image.fail",
                            error=sanitize_exception(e),
                        )
                        continue

        except Exception:
            self._log.error(
                "docker.updates.fetch.local.fail"
            )
            raise

        total_tags = sum(len(tags) for tags in local_images.values())
        self._log.info(
            "docker.updates.processed.images.info",
            repositories=len(local_images),
            total_tags=total_tags,
        )

        return local_images

    def _extract_digest(self, image: Any) -> str | None:
        """Enhanced digest extraction with validation."""
        try:
            repo_digests = image.attrs.get("RepoDigests", [])
            if not repo_digests or not isinstance(repo_digests, list):
                return None

            for digest_entry in repo_digests:
                if isinstance(digest_entry, str) and "@sha256:" in digest_entry:
                    parts = digest_entry.split("@", 1)
                    if len(parts) == 2 and parts[1].startswith("sha256:"):
                        digest = parts[1]
                        # Validate SHA256 format
                        if re.match(r"^sha256:[a-f0-9]{64}$", digest):
                            return digest

            return None

        except Exception:
            self._log.debug("docker.updates.could.not.debug")
            return None

    def _process_image_tags(
        self, image: Any, digest: str | None, local_images: LocalImageInfo
    ) -> None:
        """Enhanced tag processing with validation."""
        created_at = normalize_created_at(image.attrs.get("Created"))

        for tag in image.tags:
            try:
                if not isinstance(tag, str) or not tag.strip():
                    continue

                repo, tag_version = self._parse_tag(tag.strip())

                # Validate repository name
                if not repo or len(repo) > 255:  # Docker registry limit
                    continue

                local_images.setdefault(repo, []).append(
                    {
                        "tag": tag_version,
                        "created_at": created_at,
                        "digest": digest,
                    }
                )

            except ValueError:
                self._log.warning("docker.updates.invalid.tag.warn")
            except Exception:
                self._log.warning(
                    "docker.updates.processing.tag.fail"
                )

    @staticmethod
    def _parse_tag(tag: str) -> tuple[str, str]:
        """Enhanced tag parsing with validation."""
        if not tag or not isinstance(tag, str):
            raise ValueError("Tag must be a non-empty string")

        tag = tag.strip()
        if not tag:
            raise ValueError("Tag cannot be empty after stripping")

        # Handle registry prefixes (e.g., docker.io/library/nginx:latest)
        if tag.count("/") >= 2:
            # Extract just the repository and tag part
            parts = tag.split("/")
            if len(parts) >= 3:
                repo_tag = "/".join(parts[-2:])  # Take last two parts
            else:
                repo_tag = tag
        else:
            repo_tag = tag

        if ":" in repo_tag:
            repo, version = repo_tag.rsplit(":", 1)
            if not repo or not version:
                raise ValueError(f"Invalid tag format: {tag}")
            return repo, version
        else:
            return repo_tag, "latest"

    async def _fetch_remote_tags(
        self, session: ClientSession, repo: str
    ) -> list[EnhancedTagInfo]:
        """Enhanced remote tag fetching with comprehensive error handling."""

        # Check rate limiting
        if self.rate_limiter.should_skip_request():
            self._log.warning("docker.updates.skipping.due.warn")
            return []

        # Check cache
        with self._cache_lock:
            if repo in self.tag_cache:
                cached_tags, timestamp = self.tag_cache[repo]
                if time.time() - timestamp < CACHE_TTL:
                    self._stats["cache_hits"] += 1
                    self._log.debug("docker.updates.using.cached.debug")
                    return cached_tags
                else:
                    # Remove expired cache
                    del self.tag_cache[repo]

        self._stats["cache_misses"] += 1

        # Docker Hub API endpoints - try official repo first, then library
        base_urls = [
            f"https://registry.hub.docker.com/v2/repositories/{repo}/tags/",
            f"https://registry.hub.docker.com/v2/repositories/library/{repo}/tags/",
        ]

        tags_info: list[EnhancedTagInfo] = []
        last_error: Exception | None = None

        for url in base_urls:
            # Extract the actual repository name from URL for proper context logging
            url_parts = (
                url.split("/repositories/")[1].split("/tags/")[0]
                if "/repositories/" in url
                else repo
            )

            with self._log.context(
                action="fetch_remote_tags", repository=repo, url_repo=url_parts
            ):
                try:
                    result = await self._fetch_tags_from_url(session, url, repo)
                    if result:
                        tags_info = result
                        self.rate_limiter.handle_success()
                        self._log.debug(
                            "docker.updates.fetch.tags.ok"
                        )
                        break

                except ClientResponseError as e:
                    last_error = e
                    if e.status == 429:  # Rate limited
                        self._stats["rate_limits"] += 1
                        headers = e.headers
                        retry_after = int(
                            headers.get("Retry-After", "3600") if headers else "3600"
                        )
                        self.rate_limiter.handle_rate_limit(retry_after)
                        self._log.warning(
                            "docker.updates.rate.limited.warn"
                        )
                        raise  # Re-raise to handle at higher level
                    elif e.status == 404:
                        self._log.debug("docker.updates.repository.not.debug")
                        continue  # Try next URL
                    else:
                        self._log.warning("docker.updates.http.fail")
                        continue

                except Exception as e:
                    last_error = e
                    self._stats["errors"] += 1
                    self._log.warning(
                        "docker.updates.fetch.fail"
                    )
                    continue

        # Cache results (even empty results to avoid repeated failures)
        if tags_info or last_error:
            with self._cache_lock:
                self.tag_cache[repo] = (tags_info, time.time())

        if not tags_info and last_error:
            self._log.warning(
                "docker.updates.fetch.tags.fail"
            )

        return tags_info

    async def _fetch_tags_from_url(
        self, session: ClientSession, url: str, repo: str
    ) -> list[EnhancedTagInfo] | None:
        """Fetch tags from specific URL with intelligent retry logic."""

        # Extract the actual repository path from URL for logging
        (
            url.split("/repositories/")[1].split("/tags/")[0]
            if "/repositories/" in url
            else repo
        )

        for attempt in range(MAX_RETRIES):
            try:
                self._stats["api_calls"] += 1

                async with session.get(
                    url, timeout=ClientTimeout(self._timeout)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    results = data.get("results", [])
                    if not results:
                        return []

                    # Limit results to prevent memory issues
                    if len(results) > MAX_TAGS_PER_REPO:
                        self._log.warning(
                            "docker.updates.too.many.warn"
                        )
                        results = results[:MAX_TAGS_PER_REPO]

                    tags_info = []
                    for entry in results:
                        try:
                            if not isinstance(entry, dict):
                                continue

                            tag_info = TagInfo(
                                name=entry.get("name", ""),
                                created_at=entry.get("tag_last_pushed", ""),
                                digest=entry.get("digest"),
                            )

                            enhanced_tag = self.analyzer.analyze_tag(tag_info)
                            if enhanced_tag.is_valid:
                                tags_info.append(enhanced_tag)

                        except Exception:
                            self._log.debug(
                                "docker.updates.tag.entry.fail"
                            )
                            continue

                    self._log.debug(
                        "docker.updates.fetch.valid.debug"
                    )
                    return tags_info

            except ClientResponseError as e:
                # Don't retry on client errors (4xx) - they won't succeed
                if 400 <= e.status < 500:
                    if e.status == 404:
                        self._log.debug("docker.updates.repository.not.debug")
                    elif e.status == 403:
                        self._log.warning("docker.updates.access.forbidden.warn")
                    elif e.status == 429:
                        self._log.warning("docker.updates.rate.limited.warn")
                    else:
                        self._log.warning("docker.updates.client.fail")
                    raise  # Don't retry, re-raise immediately

                # Retry on server errors (5xx) only
                elif e.status >= 500:
                    if attempt < MAX_RETRIES - 1:
                        wait_time = 2**attempt
                        self._log.debug(
                            "docker.updates.server.fail"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        raise
                else:
                    # Other status codes, don't retry
                    raise

            except TimeoutError:
                # Only retry timeouts
                if attempt < MAX_RETRIES - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    self._log.debug("docker.updates.timeout.retry.debug")
                    await asyncio.sleep(wait_time)
                else:
                    raise

            except (ClientError, json.JSONDecodeError):
                # Network/parsing errors - retry these
                if attempt < MAX_RETRIES - 1:
                    wait_time = 2**attempt
                    self._log.debug(
                        "docker.updates.network.parsing.fail"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise

            except Exception:
                # Unknown errors - don't retry to avoid infinite loops
                self._log.warning(
                    "docker.updates.unexpected.fail"
                )
                raise

        return None

    @staticmethod
    def _compare_versions(
        local_tag: EnhancedTagInfo, remote_tag: EnhancedTagInfo
    ) -> bool:
        """Enhanced version comparison with better logic."""
        if local_tag.tag_type != remote_tag.tag_type:
            return False

        try:
            if local_tag.tag_type == TagType.SEMVER:
                if remote_tag.version_info is None or local_tag.version_info is None:
                    return False
                return remote_tag.version_info > local_tag.version_info
            elif local_tag.tag_type == TagType.DATE:
                if remote_tag.date_info is None or local_tag.date_info is None:
                    return False
                return remote_tag.date_info > local_tag.date_info
            else:
                # Fall back to creation time comparison
                try:
                    local_time = isoparse(local_tag.created_at)
                    remote_time = isoparse(remote_tag.created_at)
                    if isinstance(local_time, datetime) and isinstance(
                        remote_time, datetime
                    ):
                        return remote_time > local_time
                    return False
                except (ParserError, ValueError):
                    return False

        except Exception:
            return False

    @staticmethod
    def _digests_equal(local_tag: EnhancedTagInfo, remote_tag: EnhancedTagInfo) -> bool:
        """Compare digests when both are available."""
        if not local_tag.digest or not remote_tag.digest:
            return False
        return local_tag.digest == remote_tag.digest

    def _find_compatible_updates(
        self, local_tag: EnhancedTagInfo, remote_tags: list[EnhancedTagInfo]
    ) -> list[UpdateInfo]:
        """Enhanced update finding with better compatibility checking."""

        with self._log.context(
            action="find_updates", tag=local_tag.name, tag_type=local_tag.tag_type.name
        ):
            if not local_tag.is_valid:
                return []

            compatible_tags = []

            for remote_tag in remote_tags:
                if not remote_tag.is_valid:
                    continue

                # Same tag name: treat as update only when digest changed explicitly.
                # This avoids false positives caused by registry push timestamps.
                if local_tag.name == remote_tag.name:
                    if self._digests_equal(local_tag, remote_tag):
                        continue

                    if local_tag.digest and remote_tag.digest:
                        compatible_tags.append(remote_tag)
                    continue

                # For SEMVER, only compare within same major version
                if (
                    local_tag.tag_type == TagType.SEMVER
                    and remote_tag.tag_type == TagType.SEMVER
                ):
                    if (
                        local_tag.version_info
                        and remote_tag.version_info
                        and local_tag.version_info.major
                        == remote_tag.version_info.major
                        and self._compare_versions(local_tag, remote_tag)
                    ):
                        compatible_tags.append(remote_tag)

                # For other types, just compare if same type and newer
                elif (
                    local_tag.tag_type == remote_tag.tag_type
                    and self._compare_versions(local_tag, remote_tag)
                ):
                    compatible_tags.append(remote_tag)

            # Sort by priority and limit results
            compatible_tags.sort(reverse=True)
            limited_tags = compatible_tags[:MAX_UPDATES_PER_REPO]

            updates = []
            for tag in limited_tags:
                try:
                    update = UpdateInfo(
                        current_tag=local_tag.name,
                        newer_tag=tag.name,
                        created_at_local=local_tag.created_at,
                        created_at_remote=tag.created_at,
                        current_digest=local_tag.digest or "",
                    )
                    updates.append(update)
                except Exception:
                    self._log.warning("docker.updates.create.update.fail")
                    continue

            return updates

    async def _check_updates(self) -> UpdaterResponse:
        """Enhanced update checking with comprehensive error handling."""
        start_time = time.time()

        with self._log.context(action="check_updates"):
            if not self.local_images:
                return UpdaterResponse(
                    status=UpdaterStatus.VALIDATION_ERROR,
                    message="No local images found to check for updates",
                    execution_time=time.time() - start_time,
                )

            try:
                connector = aiohttp.TCPConnector(
                    limit=MAX_CONCURRENT_REPOS,
                    limit_per_host=2,
                    ttl_dns_cache=300,
                    use_dns_cache=True,
                )

                timeout = ClientTimeout(total=self._timeout)

                async with ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers={"User-Agent": "pyTMBot/1.0"},
                ) as session:
                    updates = {}
                    repositories_processed = 0
                    repositories_failed = 0
                    rate_limited_repos = []

                    # Process repositories with concurrency control
                    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REPOS)

                    async def process_repo(
                        repo: str, local_tags: list[dict]
                    ) -> tuple[str, dict]:
                        async with semaphore:
                            try:
                                remote_tags = await self._fetch_remote_tags(
                                    session, repo
                                )

                                if not remote_tags:
                                    return repo, {
                                        "updates": [],
                                        "error": "No remote tags found",
                                    }

                                repo_updates = []
                                for tag_dict in local_tags:
                                    try:
                                        local_tag = self.analyzer.analyze_tag(
                                            dict_to_tag_info(tag_dict)
                                        )

                                        if local_tag.is_valid:
                                            updates_found = (
                                                self._find_compatible_updates(
                                                    local_tag, remote_tags
                                                )
                                            )
                                            repo_updates.extend(updates_found)
                                    except Exception:
                                        self._log.warning(
                                            "docker.updates.processing.local.fail"
                                        )
                                        continue

                                # Sort and limit updates
                                repo_updates.sort(
                                    key=lambda x: isoparse(x.created_at_remote)
                                    if x.created_at_remote
                                    else datetime.min,
                                    reverse=True,
                                )

                                limited_updates = repo_updates[:MAX_UPDATES_PER_REPO]

                                return repo, {
                                    "updates": [u.to_dict() for u in limited_updates],
                                    "total_found": len(repo_updates),
                                    "remote_tags_count": len(remote_tags),
                                }

                            except ClientResponseError as e:
                                if e.status == 429:
                                    rate_limited_repos.append(repo)
                                    return repo, {
                                        "updates": [],
                                        "error": "Rate limited",
                                        "status_code": 429,
                                    }
                                elif e.status == 404:
                                    return repo, {
                                        "updates": [],
                                        "error": "Repository not found",
                                        "status_code": 404,
                                    }
                                elif e.status == 403:
                                    return repo, {
                                        "updates": [],
                                        "error": "Access forbidden",
                                        "status_code": 403,
                                    }
                                else:
                                    return repo, {
                                        "updates": [],
                                        "error": f"HTTP {e.status}: {e.message}",
                                        "status_code": e.status,
                                    }
                            except Exception as e:
                                return repo, {
                                    "updates": [],
                                    "error": f"Processing failed: {sanitize_exception(e)}",
                                }

                    # Execute all repository processing tasks
                    tasks: list[Coroutine[Any, Any, tuple[str, dict[str, Any]]]] = [
                        process_repo(repo, local_tags)
                        for repo, local_tags in self.local_images.items()
                    ]

                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)

                        for result in results:
                            if isinstance(result, BaseException):
                                repositories_failed += 1
                                self._log.error(
                                    "docker.updates.repository.processing.fail"
                                )
                                continue

                            repo, repo_data = result
                            updates[repo] = repo_data

                            if repo_data.get("error"):
                                repositories_failed += 1
                            else:
                                repositories_processed += 1

                    except Exception as e:
                        self._log.error(
                            "docker.updates.parallel.processing.fail"
                        )
                        return UpdaterResponse(
                            status=UpdaterStatus.ERROR,
                            message=f"Failed during parallel processing: {e}",
                            execution_time=time.time() - start_time,
                        )

            except Exception as e:
                self._log.error("docker.updates.update.check.fail")
                return UpdaterResponse(
                    status=UpdaterStatus.ERROR,
                    message=f"Error checking for updates: {e}",
                    execution_time=time.time() - start_time,
                )

            execution_time = time.time() - start_time

            # Determine response status
            if rate_limited_repos:
                status = UpdaterStatus.RATE_LIMITED
                message = f"Rate limited for {len(rate_limited_repos)} repositories"
            elif repositories_failed > 0 and repositories_processed == 0:
                status = UpdaterStatus.ERROR
                message = "All repositories failed to process"
            elif repositories_failed > 0:
                status = UpdaterStatus.PARTIAL_SUCCESS
                message = f"Processed {repositories_processed} repositories, {repositories_failed} failed"
            else:
                status = UpdaterStatus.SUCCESS
                message = "Successfully checked for updates"

            return UpdaterResponse(
                status=status,
                message=message,
                data=updates,
                metadata={
                    "stats": self._stats.copy(),
                    "rate_limited_repos": rate_limited_repos,
                    "cache_size": len(self.tag_cache),
                },
                execution_time=execution_time,
                repositories_processed=repositories_processed,
                repositories_failed=repositories_failed,
            )

    def to_dict(self) -> dict[str, Any]:
        """Run update check and return dictionary response."""
        with self._log.context(action="to_dict"):
            try:
                result = asyncio.run(self._check_updates())
                return result.to_dict()
            except Exception as e:
                error_response = UpdaterResponse(
                    status=UpdaterStatus.ERROR,
                    message=f"Failed to generate response: {sanitize_exception(e)}",
                    execution_time=0.0,
                )
                return error_response.to_dict()

    def to_json(self) -> str:
        """Return JSON representation of update check response."""
        with self._log.context(action="to_json"):
            return json.dumps(self.to_dict(), indent=4, ensure_ascii=False)

    def get_stats(self) -> dict:
        """Get comprehensive statistics about the updater."""
        with self._cache_lock:
            cache_stats = {
                "size": len(self.tag_cache),
                "entries": list(self.tag_cache.keys()),
            }

        return {
            "performance": self._stats.copy(),
            "cache": cache_stats,
            "configuration": {
                "timeout": self._timeout,
                "max_concurrent_repos": MAX_CONCURRENT_REPOS,
                "max_tags_per_repo": MAX_TAGS_PER_REPO,
                "max_updates_per_repo": MAX_UPDATES_PER_REPO,
                "cache_ttl": CACHE_TTL,
            },
            "local_images": {
                "repositories": len(self.local_images),
                "total_tags": sum(len(tags) for tags in self.local_images.values()),
            },
        }

    def clear_cache(self) -> None:
        """Clear all cached data."""
        with self._cache_lock:
            len(self.tag_cache)
            self.tag_cache.clear()

        # Reset stats
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "api_calls": 0,
            "rate_limits": 0,
            "errors": 0,
        }

        self._log.info("docker.updates.cleared.cache.info")

    def validate_configuration(self) -> dict[str, Any]:
        """Validate current configuration and return issues."""
        issues = []

        if self._timeout < 5:
            issues.append("Timeout too low, may cause frequent failures")
        elif self._timeout > 30:
            issues.append("Timeout very high, may cause slow responses")

        if not self.local_images:
            issues.append(
                "No local images found, initialize() may not have been called"
            )

        # Check for potential rate limiting issues
        if self._stats["rate_limits"] > self._stats["api_calls"] * 0.1:
            issues.append("High rate limit ratio detected")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "recommendations": [
                "Call initialize() before checking updates",
                "Monitor rate limiting and adjust concurrency if needed",
                "Clear cache periodically to avoid memory growth",
            ],
        }

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        try:
            self.clear_cache()
        except Exception:
            pass  # Suppress exceptions during cleanup
