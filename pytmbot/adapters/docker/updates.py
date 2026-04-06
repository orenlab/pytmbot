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
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from threading import Event, RLock, Thread, current_thread
from typing import Any, Final

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout
from dateutil.parser import ParserError, isoparse
from packaging import version
from packaging.version import InvalidVersion

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.logs import BaseComponent
from pytmbot.models.docker_models import TagInfo, UpdateInfo
from pytmbot.utils import sanitize_exception

# Type Aliases
type LocalImageInfo = dict[str, list[dict[str, str | None]]]
type UpdateResult = dict[str, dict[str, list[dict[str, object]]]]
type TagAnalyzerFn = Callable[[TagInfo, str], EnhancedTagInfo | None]

# Module constants for better maintainability
DEFAULT_TIMEOUT: Final[int] = 15
MAX_TIMEOUT: Final[int] = 60
MAX_RETRIES: Final[int] = 3  # Only for transient errors (5xx, timeouts, network issues)
RATE_LIMIT_BACKOFF: Final[int] = 300  # 5 minutes
CACHE_TTL: Final[int] = 3600  # 1 hour
MAX_CONCURRENT_REPOS: Final[int] = 5
MAX_TAGS_PER_REPO: Final[int] = 100
MAX_UPDATES_PER_REPO: Final[int] = 10
_DIGEST_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[a-f0-9]{64}$")

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


@dataclass(frozen=True, slots=True)
class UpdaterResponse:
    """Enhanced response with additional metadata."""

    status: UpdaterStatus
    message: str
    data: Mapping[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    execution_time: float | None = None
    repositories_processed: int = 0
    repositories_failed: int = 0

    def to_dict(self) -> dict[str, object]:
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


_TAG_SEMVER_PATTERN = re.compile(
    r"^v?(\d+\.\d+\.\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_TAG_DATE_PATTERN = re.compile(
    r"^(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})(?:[-_.]?(\d{2})[-_.]?(\d{2})[-_.]?(\d{2}))?$"
)
_TAG_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
_TAG_NUMERIC_PATTERN = re.compile(r"^\d+(\.\d+)*$")
_TAG_RELEASE_PATTERN = re.compile(
    r"^(release|rel|r)[-_.]?v?(\d+(?:\.\d+)*)$", re.IGNORECASE
)
_LATEST_TAG_NAMES: Final[frozenset[str]] = frozenset(
    {"latest", "current", "stable", "main", "master"}
)


def _invalid_tag_result(tag_info: TagInfo, message: str) -> EnhancedTagInfo:
    return EnhancedTagInfo(
        tag_info=tag_info,
        tag_type=TagType.INVALID,
        parse_error=message,
    )


def _custom_tag_result(
    tag_info: TagInfo, *, parse_error: str | None = None
) -> EnhancedTagInfo:
    return EnhancedTagInfo(
        tag_info=tag_info,
        tag_type=TagType.CUSTOM,
        parse_error=parse_error,
    )


def _parse_version_tag(
    tag_info: TagInfo,
    raw_version: str,
    *,
    parse_error_prefix: str | None = None,
) -> EnhancedTagInfo | None:
    try:
        parsed_version = version.parse(raw_version)
    except InvalidVersion as error:
        if parse_error_prefix is None:
            return None
        return _custom_tag_result(
            tag_info, parse_error=f"{parse_error_prefix}: {error}"
        )
    return EnhancedTagInfo(
        tag_info=tag_info,
        tag_type=TagType.SEMVER,
        version_info=parsed_version,
    )


def _analyze_semver_tag(
    tag_info: TagInfo, tag_name: str, pattern: re.Pattern[str]
) -> EnhancedTagInfo | None:
    semver_match = pattern.match(tag_name)
    if semver_match is None:
        return None
    return _parse_version_tag(
        tag_info,
        semver_match.group(1),
        parse_error_prefix="Invalid semver",
    )


def _analyze_release_tag(
    tag_info: TagInfo, tag_name: str, pattern: re.Pattern[str]
) -> EnhancedTagInfo | None:
    release_match = pattern.match(tag_name)
    if release_match is None:
        return None
    return _parse_version_tag(tag_info, release_match.group(2))


def _analyze_numeric_tag(
    tag_info: TagInfo, tag_name: str, pattern: re.Pattern[str]
) -> EnhancedTagInfo | None:
    if pattern.match(tag_name) is None:
        return None
    return _parse_version_tag(tag_info, tag_name)


def _build_tag_date_info(date_groups: tuple[str | None, ...]) -> datetime:
    if date_groups[0] is None or date_groups[1] is None or date_groups[2] is None:
        raise ValueError("Date components are incomplete")

    year, month, day = (
        int(date_groups[0]),
        int(date_groups[1]),
        int(date_groups[2]),
    )
    if not (2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        raise ValueError("Date out of valid range")

    if date_groups[3] and date_groups[4] and date_groups[5]:
        hour, minute, second = (
            int(date_groups[3]),
            int(date_groups[4]),
            int(date_groups[5]),
        )
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            raise ValueError("Time out of valid range")
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)

    return datetime(year, month, day, tzinfo=UTC)


def _analyze_date_tag(
    tag_info: TagInfo, tag_name: str, pattern: re.Pattern[str]
) -> EnhancedTagInfo | None:
    date_match = pattern.match(tag_name)
    if date_match is None:
        return None

    try:
        date_info = _build_tag_date_info(date_match.groups())
    except (ValueError, OverflowError) as error:
        return _custom_tag_result(tag_info, parse_error=f"Invalid date: {error}")

    return EnhancedTagInfo(
        tag_info=tag_info,
        tag_type=TagType.DATE,
        date_info=date_info,
    )


class TagAnalyzer:
    """Facade for tag analysis using module-level analyzers."""

    SEMVER_PATTERN = _TAG_SEMVER_PATTERN
    DATE_PATTERN = _TAG_DATE_PATTERN
    SHA_PATTERN = _TAG_SHA_PATTERN
    NUMERIC_PATTERN = _TAG_NUMERIC_PATTERN
    RELEASE_PATTERN = _TAG_RELEASE_PATTERN
    LATEST_TAG_NAMES = _LATEST_TAG_NAMES

    @classmethod
    def analyze_tag(cls, tag_info: TagInfo) -> EnhancedTagInfo:
        """Analyze Docker tag metadata and classify it."""
        if not tag_info or not tag_info.name:
            return _invalid_tag_result(tag_info, "Empty or invalid tag info")

        tag_name = tag_info.name.strip()
        if not tag_name:
            return _invalid_tag_result(tag_info, "Empty tag name")

        tag_lower = tag_name.lower()

        try:
            if tag_lower in cls.LATEST_TAG_NAMES:
                return EnhancedTagInfo(tag_info, TagType.LATEST)

            if cls.SHA_PATTERN.match(tag_lower):
                return EnhancedTagInfo(tag_info, TagType.SHA)

            analyzers: tuple[TagAnalyzerFn, ...] = (
                lambda info, name: _analyze_semver_tag(info, name, cls.SEMVER_PATTERN),
                lambda info, name: _analyze_release_tag(
                    info, name, cls.RELEASE_PATTERN
                ),
                lambda info, name: _analyze_numeric_tag(
                    info, name, cls.NUMERIC_PATTERN
                ),
                lambda info, name: _analyze_date_tag(info, name, cls.DATE_PATTERN),
            )
            for analyzer in analyzers:
                analyzed = analyzer(tag_info, tag_name)
                if analyzed is not None:
                    return analyzed

            return _custom_tag_result(tag_info)

        except Exception as error:
            return _invalid_tag_result(tag_info, f"Analysis error: {error}")


def normalize_created_at(created: object) -> str | None:
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


def dict_to_tag_info(info: Mapping[str, object]) -> TagInfo:
    """Enhanced conversion with validation."""
    if not isinstance(info, dict):
        raise ValueError("Info must be a dictionary")

    required_fields = ["tag", "created_at", "digest"]
    for field_name in required_fields:
        if field_name not in info:
            raise ValueError(f"Missing required field: {field_name}")

    created_at_raw = info["created_at"]
    digest_raw = info["digest"]

    created_at = created_at_raw if isinstance(created_at_raw, str) else ""
    digest: str | None
    if digest_raw is None:
        digest = None
    elif isinstance(digest_raw, str):
        digest = digest_raw
    else:
        digest = str(digest_raw)

    return TagInfo(
        name=str(info["tag"]) if info["tag"] is not None else "",
        created_at=created_at,
        digest=digest,
    )


def _extract_image_digest(image: object, *, log: Any) -> str | None:
    """Extract a validated SHA256 digest from image metadata when present."""
    try:
        image_attrs_raw = getattr(image, "attrs", None)
        image_attrs = image_attrs_raw if isinstance(image_attrs_raw, dict) else {}
        repo_digests = image_attrs.get("RepoDigests", [])
        if not repo_digests or not isinstance(repo_digests, list):
            return None

        for digest_entry in repo_digests:
            if isinstance(digest_entry, str) and "@sha256:" in digest_entry:
                parts = digest_entry.split("@", 1)
                if len(parts) == 2 and parts[1].startswith("sha256:"):
                    digest = parts[1]
                    if _DIGEST_PATTERN.match(digest):
                        return digest

        return None
    except Exception:
        log.debug("docker.updates.could.not.debug")
        return None


def _parse_image_tag(tag: str) -> tuple[str, str]:
    """Parse repository and version from a Docker image tag."""
    if not tag or not isinstance(tag, str):
        raise ValueError("Tag must be a non-empty string")

    normalized_tag = tag.strip()
    if not normalized_tag:
        raise ValueError("Tag cannot be empty after stripping")

    if normalized_tag.count("/") >= 2:
        parts = normalized_tag.split("/")
        repo_tag = "/".join(parts[-2:]) if len(parts) >= 3 else normalized_tag
    else:
        repo_tag = normalized_tag

    if ":" in repo_tag:
        repo, version_name = repo_tag.rsplit(":", 1)
        if not repo or not version_name:
            raise ValueError(f"Invalid tag format: {tag}")
        return repo, version_name

    return repo_tag, "latest"


def _process_local_image_tags(
    image: object,
    digest: str | None,
    local_images: LocalImageInfo,
    *,
    log: Any,
    parse_tag: Callable[[str], tuple[str, str]],
) -> None:
    """Append validated image tags to the local image catalog."""
    image_attrs_raw = getattr(image, "attrs", None)
    image_attrs = image_attrs_raw if isinstance(image_attrs_raw, dict) else {}
    created_at = normalize_created_at(image_attrs.get("Created"))

    image_tags_raw = getattr(image, "tags", ())
    image_tags = image_tags_raw if isinstance(image_tags_raw, list) else []
    for tag in image_tags:
        try:
            if not isinstance(tag, str) or not tag.strip():
                continue

            repo, tag_version = parse_tag(tag.strip())
            if not repo or len(repo) > 255:
                continue

            local_images.setdefault(repo, []).append(
                {
                    "tag": tag_version,
                    "created_at": created_at,
                    "digest": digest,
                }
            )
        except ValueError:
            log.warning("docker.updates.invalid.tag.warn")
        except Exception:
            log.warning("docker.updates.processing.tag.fail")


def _build_repository_urls(repo: str) -> list[str]:
    """Build Docker Hub repository endpoints for a repository name."""
    normalized_repo = repo.strip().strip("/")
    if "/" in normalized_repo:
        return [
            f"https://registry.hub.docker.com/v2/repositories/{normalized_repo}/tags/"
        ]

    return [
        f"https://registry.hub.docker.com/v2/repositories/{normalized_repo}/tags/",
        f"https://registry.hub.docker.com/v2/repositories/library/{normalized_repo}/tags/",
    ]


def _compare_enhanced_tags(
    local_tag: EnhancedTagInfo,
    remote_tag: EnhancedTagInfo,
) -> bool:
    """Compare two analyzed tags and determine whether remote is newer."""
    if local_tag.tag_type != remote_tag.tag_type:
        return False

    try:
        if local_tag.tag_type == TagType.SEMVER:
            if remote_tag.version_info is None or local_tag.version_info is None:
                return False
            return remote_tag.version_info > local_tag.version_info

        if local_tag.tag_type == TagType.DATE:
            if remote_tag.date_info is None or local_tag.date_info is None:
                return False
            return remote_tag.date_info > local_tag.date_info

        try:
            local_time = isoparse(local_tag.created_at)
            remote_time = isoparse(remote_tag.created_at)
            if isinstance(local_time, datetime) and isinstance(remote_time, datetime):
                return remote_time > local_time
            return False
        except (ParserError, ValueError):
            return False
    except Exception:
        return False


def _tag_digests_equal(local_tag: EnhancedTagInfo, remote_tag: EnhancedTagInfo) -> bool:
    """Compare digests when both are available."""
    if not local_tag.digest or not remote_tag.digest:
        return False
    return local_tag.digest == remote_tag.digest


def _find_compatible_tag_updates(
    local_tag: EnhancedTagInfo,
    remote_tags: list[EnhancedTagInfo],
    *,
    log: Any,
    compare_versions: Callable[[EnhancedTagInfo, EnhancedTagInfo], bool],
    digests_equal: Callable[[EnhancedTagInfo, EnhancedTagInfo], bool],
) -> list[UpdateInfo]:
    """Find compatible remote updates for a local tag."""
    with log.context(
        action="find_updates",
        tag=local_tag.name,
        tag_type=local_tag.tag_type.name,
    ):
        if not local_tag.is_valid:
            return []

        compatible_tags: list[EnhancedTagInfo] = []
        for remote_tag in remote_tags:
            if not remote_tag.is_valid:
                continue

            if local_tag.name == remote_tag.name:
                if digests_equal(local_tag, remote_tag):
                    continue
                if local_tag.digest and remote_tag.digest:
                    compatible_tags.append(remote_tag)
                continue

            if (
                local_tag.tag_type == TagType.SEMVER
                and remote_tag.tag_type == TagType.SEMVER
            ):
                if (
                    local_tag.version_info
                    and remote_tag.version_info
                    and local_tag.version_info.major == remote_tag.version_info.major
                    and compare_versions(local_tag, remote_tag)
                ):
                    compatible_tags.append(remote_tag)
            elif local_tag.tag_type == remote_tag.tag_type and compare_versions(
                local_tag, remote_tag
            ):
                compatible_tags.append(remote_tag)

        compatible_tags.sort(reverse=True)
        updates: list[UpdateInfo] = []
        for tag in compatible_tags[:MAX_UPDATES_PER_REPO]:
            try:
                updates.append(
                    UpdateInfo(
                        current_tag=local_tag.name,
                        newer_tag=tag.name,
                        created_at_local=local_tag.created_at,
                        created_at_remote=tag.created_at,
                        current_digest=local_tag.digest or "",
                    )
                )
            except Exception:
                log.warning("docker.updates.create.update.fail")
                continue

        return updates


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


class _UpdaterTagCache:
    """Thread-safe cache for repository tag lookups."""

    def __init__(self) -> None:
        self.entries: dict[str, tuple[list[EnhancedTagInfo], float]] = {}
        self.lock = RLock()

    def get_valid(self, repo: str, current_time: float) -> list[EnhancedTagInfo] | None:
        with self.lock:
            cached_entry = self.entries.get(repo)
            if cached_entry is None:
                return None
            cached_tags, timestamp = cached_entry
            if current_time - timestamp < CACHE_TTL:
                return cached_tags
            self.entries.pop(repo, None)
            return None

    def set(
        self, repo: str, tags_info: list[EnhancedTagInfo], current_time: float
    ) -> None:
        with self.lock:
            self.entries[repo] = (tags_info, current_time)

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "size": len(self.entries),
                "entries": list(self.entries.keys()),
            }


class _UpdaterSyncBridge:
    """Own the background event loop used by sync callers."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.ready = Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: Thread | None = None

    def ensure_ready(self) -> None:
        with self.lock:
            if (
                self.thread is not None
                and self.thread.is_alive()
                and self.loop is not None
                and self.loop.is_running()
            ):
                return

            self.ready.clear()

            def _bridge_worker() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                with self.lock:
                    self.loop = loop
                self.ready.set()
                try:
                    loop.run_forever()
                finally:
                    loop.close()

            self.thread = Thread(
                target=_bridge_worker,
                name="docker_updates_sync_bridge",
                daemon=True,
            )
            self.thread.start()

        if not self.ready.wait(timeout=2.0):
            raise RuntimeError("Docker updates sync bridge failed to start")

    def stop(self) -> None:
        with self.lock:
            loop = self.loop
            thread = self.thread
            self.loop = None
            self.thread = None

        if loop is not None and loop.is_running():
            with suppress(Exception):
                loop.call_soon_threadsafe(loop.stop)

        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=2.0)


async def _fetch_tags_from_registry_url(
    session: ClientSession,
    url: str,
    *,
    timeout: int,
    analyzer: TagAnalyzer,
    stats: dict[str, int],
    log: Any,
) -> list[EnhancedTagInfo] | None:
    """Fetch tags from a specific registry URL with retry handling."""
    for attempt in range(MAX_RETRIES):
        try:
            stats["api_calls"] += 1

            async with session.get(url, timeout=ClientTimeout(timeout)) as response:
                response.raise_for_status()
                data = await response.json()

                results = data.get("results", [])
                if not results:
                    return []

                if len(results) > MAX_TAGS_PER_REPO:
                    log.warning("docker.updates.too.many.warn")
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

                        enhanced_tag = analyzer.analyze_tag(tag_info)
                        if enhanced_tag.is_valid:
                            tags_info.append(enhanced_tag)

                    except Exception:
                        log.debug("docker.updates.tag.entry.fail")
                        continue

                log.debug("docker.updates.fetch.valid.debug")
                return tags_info

        except ClientResponseError as error:
            if 400 <= error.status < 500:
                if error.status == 403:
                    log.warning("docker.updates.access.forbidden.warn")
                elif error.status == 429:
                    log.warning("docker.updates.rate.limited.warn")
                else:
                    log.warning("docker.updates.client.fail")
                raise

            if error.status >= 500:
                if attempt < MAX_RETRIES - 1:
                    wait_time = 2**attempt
                    log.debug("docker.updates.server.fail")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            else:
                raise

        except TimeoutError:
            if attempt < MAX_RETRIES - 1:
                wait_time = 2**attempt
                log.debug("docker.updates.timeout.retry.debug")
                await asyncio.sleep(wait_time)
            else:
                raise

        except (ClientError, json.JSONDecodeError):
            if attempt < MAX_RETRIES - 1:
                wait_time = 2**attempt
                log.debug("docker.updates.network.parsing.fail")
                await asyncio.sleep(wait_time)
            else:
                raise

        except Exception:
            log.warning("docker.updates.unexpected.fail")
            raise

    return None


async def _fetch_remote_tags_for_repository(
    session: ClientSession,
    repo: str,
    *,
    timeout: int,
    cache: _UpdaterTagCache,
    rate_limiter: RateLimitHandler,
    stats: dict[str, int],
    log: Any,
    fetch_tags_from_url: Callable[
        [ClientSession, str, str],
        Coroutine[object, object, list[EnhancedTagInfo] | None],
    ],
) -> list[EnhancedTagInfo]:
    """Fetch remote tags with cache and rate-limit handling."""
    if rate_limiter.should_skip_request():
        log.warning("docker.updates.skipping.due.warn")
        return []

    current_time = time.time()
    cached_tags = cache.get_valid(repo, current_time)
    if cached_tags is not None:
        stats["cache_hits"] += 1
        log.debug("docker.updates.using.cached.debug")
        return cached_tags

    stats["cache_misses"] += 1
    base_urls = _build_repository_urls(repo)

    tags_info: list[EnhancedTagInfo] = []
    last_error: Exception | None = None

    for url in base_urls:
        url_parts = (
            url.split("/repositories/")[1].split("/tags/")[0]
            if "/repositories/" in url
            else repo
        )

        with log.context(
            action="fetch_remote_tags", repository=repo, url_repo=url_parts
        ):
            try:
                result = await fetch_tags_from_url(session, url, repo)
                if result:
                    tags_info = result
                    rate_limiter.handle_success()
                    log.debug("docker.updates.fetch.tags.ok")
                    break

            except ClientResponseError as error:
                last_error = error
                if error.status == 429:
                    stats["rate_limits"] += 1
                    headers = error.headers
                    retry_after = int(
                        headers.get("Retry-After", "3600") if headers else "3600"
                    )
                    rate_limiter.handle_rate_limit(retry_after)
                    log.warning("docker.updates.rate.limited.warn")
                    raise
                if error.status == 404:
                    log.debug("docker.updates.repository.not.debug")
                    continue

                log.warning("docker.updates.http.fail")
                continue

            except Exception as error:
                last_error = error
                stats["errors"] += 1
                log.warning("docker.updates.fetch.fail")
                continue

    if tags_info or last_error:
        cache.set(repo, tags_info, time.time())

    if not tags_info and last_error:
        log.warning("docker.updates.fetch.tags.fail")

    return tags_info


async def _check_updates_async(
    local_images: LocalImageInfo,
    *,
    timeout: int,
    cache: _UpdaterTagCache,
    analyzer: TagAnalyzer,
    stats: dict[str, int],
    log: Any,
    fetch_remote_tags: Callable[
        [ClientSession, str], Coroutine[object, object, list[EnhancedTagInfo]]
    ],
) -> UpdaterResponse:
    """Check updates for all local repositories."""
    start_time = time.time()

    with log.context(action="check_updates"):
        if not local_images:
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

            timeout_config = ClientTimeout(total=timeout)

            async with ClientSession(
                timeout=timeout_config,
                connector=connector,
                headers={"User-Agent": "pyTMBot/1.0"},
            ) as session:
                updates = {}
                repositories_processed = 0
                repositories_failed = 0
                rate_limited_repos: list[str] = []
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_REPOS)

                async def process_repo(
                    repo: str, local_tags: Sequence[dict[str, str | None]]
                ) -> tuple[str, dict[str, object]]:
                    async with semaphore:
                        try:
                            remote_tags = await fetch_remote_tags(session, repo)

                            if not remote_tags:
                                return repo, {
                                    "updates": [],
                                    "error": "No remote tags found",
                                }

                            repo_updates = []
                            for tag_dict in local_tags:
                                try:
                                    local_tag = analyzer.analyze_tag(
                                        dict_to_tag_info(tag_dict)
                                    )
                                    if local_tag.is_valid:
                                        updates_found = _find_compatible_tag_updates(
                                            local_tag,
                                            remote_tags,
                                            log=log,
                                            compare_versions=_compare_enhanced_tags,
                                            digests_equal=_tag_digests_equal,
                                        )
                                        repo_updates.extend(updates_found)
                                except Exception:
                                    log.warning("docker.updates.processing.local.fail")
                                    continue

                            repo_updates.sort(
                                key=lambda update: (
                                    isoparse(update.created_at_remote)
                                    if update.created_at_remote
                                    else datetime.min
                                ),
                                reverse=True,
                            )

                            limited_updates = repo_updates[:MAX_UPDATES_PER_REPO]
                            return repo, {
                                "updates": [
                                    update.model_dump() for update in limited_updates
                                ],
                                "total_found": len(repo_updates),
                                "remote_tags_count": len(remote_tags),
                            }

                        except ClientResponseError as error:
                            if error.status == 429:
                                rate_limited_repos.append(repo)
                                return repo, {
                                    "updates": [],
                                    "error": "Rate limited",
                                    "status_code": 429,
                                }
                            if error.status == 404:
                                return repo, {
                                    "updates": [],
                                    "error": "Repository not found",
                                    "status_code": 404,
                                }
                            if error.status == 403:
                                return repo, {
                                    "updates": [],
                                    "error": "Access forbidden",
                                    "status_code": 403,
                                }
                            return repo, {
                                "updates": [],
                                "error": f"HTTP {error.status}: {error.message}",
                                "status_code": error.status,
                            }
                        except Exception as error:
                            return repo, {
                                "updates": [],
                                "error": f"Processing failed: {sanitize_exception(error)}",
                            }

                tasks: list[
                    Coroutine[object, object, tuple[str, dict[str, object]]]
                ] = [
                    process_repo(repo, local_tags)
                    for repo, local_tags in local_images.items()
                ]

                try:
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for result in results:
                        if isinstance(result, BaseException):
                            repositories_failed += 1
                            log.error("docker.updates.repository.processing.fail")
                            continue

                        repo, repo_data = result
                        updates[repo] = repo_data

                        if repo_data.get("error"):
                            repositories_failed += 1
                        else:
                            repositories_processed += 1

                except Exception as error:
                    log.error("docker.updates.parallel.processing.fail")
                    return UpdaterResponse(
                        status=UpdaterStatus.ERROR,
                        message=f"Failed during parallel processing: {error}",
                        execution_time=time.time() - start_time,
                    )

        except Exception as error:
            log.error("docker.updates.update.check.fail")
            return UpdaterResponse(
                status=UpdaterStatus.ERROR,
                message=f"Error checking for updates: {error}",
                execution_time=time.time() - start_time,
            )

        execution_time = time.time() - start_time
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
                "stats": stats.copy(),
                "rate_limited_repos": rate_limited_repos,
                "cache_size": len(cache.entries),
            },
            execution_time=execution_time,
            repositories_processed=repositories_processed,
            repositories_failed=repositories_failed,
        )


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
        self.analyzer = TagAnalyzer()
        self.rate_limiter = RateLimitHandler()
        self._cache = _UpdaterTagCache()
        self._sync_bridge = _UpdaterSyncBridge()

        # Performance metrics
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "api_calls": 0,
            "rate_limits": 0,
            "errors": 0,
        }

    def _ensure_sync_bridge(self) -> None:
        """Ensure persistent background loop exists for sync-to-async bridge."""
        self._sync_bridge.ensure_ready()

    def _stop_sync_bridge(self) -> None:
        """Stop and cleanup sync bridge resources."""
        self._sync_bridge.stop()

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
            with docker_client_context() as adapter:
                images = adapter.images.list(all=False)
                self._log.debug("docker.updates.found.local.debug")

                for image in images:
                    try:
                        if not image.tags:
                            skipped_count += 1
                            self._log.debug("docker.updates.skipping.image.debug")
                            continue

                        digest = _extract_image_digest(image, log=self._log)
                        _process_local_image_tags(
                            image,
                            digest,
                            local_images,
                            log=self._log,
                            parse_tag=_parse_image_tag,
                        )
                        processed_count += 1

                    except Exception as e:
                        skipped_count += 1
                        self._log.warning(
                            "docker.updates.image.fail",
                            error=sanitize_exception(e),
                        )
                        continue

        except Exception:
            self._log.error("docker.updates.fetch.local.fail")
            raise

        total_tags = sum(len(tags) for tags in local_images.values())
        self._log.info(
            "docker.updates.processed.images.info",
            repositories=len(local_images),
            total_tags=total_tags,
        )

        return local_images

    async def _fetch_remote_tags(
        self, session: ClientSession, repo: str
    ) -> list[EnhancedTagInfo]:
        """Enhanced remote tag fetching with comprehensive error handling."""
        return await _fetch_remote_tags_for_repository(
            session,
            repo,
            timeout=self._timeout,
            cache=self._cache,
            rate_limiter=self.rate_limiter,
            stats=self._stats,
            log=self._log,
            fetch_tags_from_url=self._fetch_tags_from_url,
        )

    async def _fetch_tags_from_url(
        self, session: ClientSession, url: str, _repo: str
    ) -> list[EnhancedTagInfo] | None:
        """Fetch tags from specific URL with intelligent retry logic."""
        return await _fetch_tags_from_registry_url(
            session,
            url,
            timeout=self._timeout,
            analyzer=self.analyzer,
            stats=self._stats,
            log=self._log,
        )

    async def _check_updates(self) -> UpdaterResponse:
        """Enhanced update checking with comprehensive error handling."""
        return await _check_updates_async(
            self.local_images,
            timeout=self._timeout,
            cache=self._cache,
            analyzer=self.analyzer,
            stats=self._stats,
            log=self._log,
            fetch_remote_tags=self._fetch_remote_tags,
        )

    def to_dict(self) -> dict[str, object]:
        """Run update check and return dictionary response."""
        with self._log.context(action="to_dict"):
            try:
                result = self._run_check_updates_sync()
                return result.to_dict()
            except Exception as e:
                error_response = UpdaterResponse(
                    status=UpdaterStatus.ERROR,
                    message=f"Failed to generate response: {sanitize_exception(e)}",
                    execution_time=0.0,
                )
                return error_response.to_dict()

    def get_stats(self) -> dict[str, object]:
        """Get comprehensive statistics about the updater."""
        return {
            "performance": self._stats.copy(),
            "cache": self._cache.snapshot(),
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
        self._cache.clear()

        # Reset stats
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "api_calls": 0,
            "rate_limits": 0,
            "errors": 0,
        }

        self._log.info("docker.updates.cleared.cache.info")

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        try:
            self.clear_cache()
            self._stop_sync_bridge()
        except Exception:
            pass  # Suppress exceptions during cleanup

    def _run_check_updates_sync(self) -> UpdaterResponse:
        """Run async updates check from sync context via persistent bridge loop."""
        self._ensure_sync_bridge()
        loop = self._sync_bridge.loop
        if loop is None:
            raise RuntimeError("Docker updates sync bridge is unavailable")
        future = asyncio.run_coroutine_threadsafe(self._check_updates(), loop)
        return future.result()
