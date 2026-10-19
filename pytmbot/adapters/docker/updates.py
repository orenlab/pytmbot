#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import asyncio
import math
import re
import time
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum, StrEnum, auto
from threading import Event, Lock, RLock, Thread, current_thread
from typing import Any, Final

import aiohttp
from aiohttp import (
    ClientConnectionError,
    ClientError,
    ClientResponseError,
    ClientSession,
    ClientTimeout,
)
from dateutil.parser import isoparse
from packaging import version
from packaging.version import InvalidVersion

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.images_info import list_images_tolerant
from pytmbot.logs import BaseComponent
from pytmbot.models.docker_models import TagInfo, UpdateInfo
from pytmbot.utils import sanitize_exception

# Type Aliases
type LocalTagEntry = dict[str, str | None]
type LocalImageInfo = dict[str, list[LocalTagEntry]]
type ReferenceResult = dict[str, object]
type CheckResults = dict[str, ReferenceResult]
type RemoteTagsFetcher = Callable[
    [ClientSession, str], Coroutine[object, object, list[EnhancedTagInfo]]
]
type RepositoryChecker = Callable[
    [ClientSession, str, list[LocalTagEntry]], Coroutine[object, object, CheckResults]
]

# Module constants for better maintainability
DEFAULT_TIMEOUT: Final[int] = 10  # per registry request, connection setup included
CONNECT_TIMEOUT: Final[int] = 5
MAX_TIMEOUT: Final[int] = 60
CHECK_DEADLINE: Final[float] = 60.0  # overall budget of one update check
BRIDGE_GRACE_SECONDS: Final[float] = 5.0
MAX_ATTEMPTS: Final[int] = 2  # one retry for timeouts and transient registry errors
RETRY_DELAY: Final[float] = 1.0
RATE_LIMIT_BACKOFF: Final[int] = 300  # 5 minutes when Docker Hub gives no Retry-After
MAX_RATE_LIMIT_BACKOFF: Final[int] = 6 * 3600  # longest Docker Hub limit window
CACHE_TTL: Final[int] = 3600  # 1 hour
MAX_CONCURRENT_REPOS: Final[int] = 5
MAX_TAGS_PER_REPO: Final[int] = 100
MAX_UPDATES_PER_REPO: Final[int] = 10
DOCKER_HUB_REGISTRY: Final[str] = "docker.io"
_DOCKER_HUB_ALIASES: Final[frozenset[str]] = frozenset(
    {"docker.io", "index.docker.io", "registry-1.docker.io"}
)
_DOCKER_HUB_TAGS_URL: Final[str] = (
    "https://registry.hub.docker.com/v2/repositories/{path}/tags/"
    "?page_size={page_size}&ordering=last_updated"
)
_USER_AGENT: Final[str] = "pyTMBot/1.0"
_DIGEST_PATTERN: Final[re.Pattern[str]] = re.compile(r"sha256:[a-f0-9]{64}")
_TAG_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\w][\w.-]{0,127}", re.ASCII)
_REPOSITORY_COMPONENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*"
)
_RETRY_AFTER_SECONDS_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d{1,10}", re.ASCII)
_MIN_TIMESTAMP: Final[datetime] = datetime.min.replace(tzinfo=UTC)


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


class CheckFailure(StrEnum):
    """Why a local image could not be checked; values are shown to users."""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate limited"
    NOT_FOUND = "not found"
    TAG_NOT_FOUND = "tag not found"
    NO_TAGS = "no tags found"
    ACCESS_DENIED = "access denied"
    REGISTRY_ERROR = "registry error"
    NETWORK_ERROR = "network error"
    INVALID_RESPONSE = "unexpected registry response"
    UNSUPPORTED_REGISTRY = "registry not supported"
    LOCAL_IMAGE = "local image"
    INTERNAL_ERROR = "internal error"


# Images that are never sent to Docker Hub; they are skipped, not failed.
_SKIPPED_FAILURES: Final[frozenset[str]] = frozenset(
    {CheckFailure.UNSUPPORTED_REGISTRY.name, CheckFailure.LOCAL_IMAGE.name}
)
_STATUS_FAILURES: Final[dict[int, CheckFailure]] = {
    401: CheckFailure.ACCESS_DENIED,
    403: CheckFailure.ACCESS_DENIED,
    404: CheckFailure.NOT_FOUND,
}


class RegistryCheckError(Exception):
    """A repository could not be checked against Docker Hub."""

    def __init__(
        self,
        reason: CheckFailure,
        *,
        retry_after: int | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.retry_after = retry_after
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ImageReference:
    """Image reference split into registry, repository path and tag."""

    repository: str  # as written locally, without tag or digest
    registry: str  # "docker.io" for Docker Hub
    path: str  # repository path inside the registry, e.g. "library/nginx"
    tag: str

    @property
    def is_docker_hub(self) -> bool:
        return self.registry == DOCKER_HUB_REGISTRY

    @property
    def canonical_name(self) -> str:
        return f"{self.registry}/{self.path}"


def _split_reference_tag(name: str) -> tuple[str, str]:
    repository, separator, tag = name.rpartition(":")
    if not separator or "/" in tag:
        # No tag, or the colon belongs to a registry port ("localhost:5000/app").
        return name, "latest"
    if not repository or not _TAG_NAME_PATTERN.fullmatch(tag):
        raise ValueError(f"Invalid tag in image reference: {name}")
    return repository, tag


def _split_registry(repository: str) -> tuple[str, str]:
    first, separator, rest = repository.partition("/")
    if separator and ("." in first or ":" in first or first == "localhost"):
        return first.lower(), rest
    return DOCKER_HUB_REGISTRY, repository


def parse_image_reference(reference: str) -> ImageReference:
    """
    Parse ``[registry/]path[:tag][@digest]`` the way the Docker CLI does.

    The first component names a registry only when it contains a dot or a colon
    or equals ``localhost``. Everything else lives on Docker Hub, where single
    names belong to the ``library`` namespace.
    """
    name = reference.strip().split("@", 1)[0]
    if not name:
        raise ValueError("Image reference cannot be empty")

    repository, tag = _split_reference_tag(name)
    registry, path = _split_registry(repository)
    if registry in _DOCKER_HUB_ALIASES:
        registry = DOCKER_HUB_REGISTRY
        if "/" not in path:
            path = f"library/{path}"
    if not path or not all(path.split("/")):
        raise ValueError(f"Invalid image reference: {reference}")
    return ImageReference(repository=repository, registry=registry, path=path, tag=tag)


def _docker_hub_tags_url(reference: ImageReference) -> str | None:
    """Return the Docker Hub tags endpoint, or None for any other registry."""
    if not reference.is_docker_hub:
        return None
    components = reference.path.split("/")
    if len(components) != 2 or not all(
        _REPOSITORY_COMPONENT_PATTERN.fullmatch(component) for component in components
    ):
        return None
    return _DOCKER_HUB_TAGS_URL.format(path=reference.path, page_size=MAX_TAGS_PER_REPO)


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


def _timestamp_sort_key(value: str | None) -> datetime:
    """Parse a timestamp into an aware datetime; unknown values sort first."""
    if not value:
        return _MIN_TIMESTAMP
    try:
        parsed = isoparse(value)
    except (ValueError, OverflowError):
        return _MIN_TIMESTAMP
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class EnhancedTagInfo:
    """Enhanced tag information with validation and comparison support."""

    tag_info: TagInfo
    tag_type: TagType
    version_info: version.Version | None = None
    date_info: datetime | None = None
    parse_error: str | None = None
    # Release line: only tags of the same family are compared with each other.
    family: str = ""

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

        if self.tag_type.priority != other.tag_type.priority:
            return self.tag_type.priority < other.tag_type.priority

        if self.tag_type == TagType.SEMVER and self.version_info and other.version_info:
            return self.version_info < other.version_info
        if self.tag_type == TagType.DATE and self.date_info and other.date_info:
            return self.date_info < other.date_info

        left_date = _timestamp_sort_key(self.created_at)
        right_date = _timestamp_sort_key(other.created_at)
        if left_date != right_date:
            return left_date < right_date
        return self.name < other.name


_TAG_DATE_PATTERN = re.compile(
    r"^(\d{4})[-_]?(\d{2})[-_]?(\d{2})(?:[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2}))?$"
)
_TAG_VERSION_PATTERN = re.compile(
    r"^(?P<prefix>v|(?:release|rel|r)[-_.]?v?)?"
    r"(?P<numbers>\d+(?:\.\d+)*)"
    r"(?P<suffix>(?:[-_.]?[a-z]|[-_])[a-z0-9_.-]*)?$",
    re.IGNORECASE,
)
_TAG_PRERELEASE_PATTERN = re.compile(
    r"(?<![a-z])(?P<label>alpha|beta|preview|pre|rc|dev|a|b)[-_.]?(?P<number>\d+)?(?![a-z])",
    re.IGNORECASE,
)
_PRERELEASE_SEGMENTS: Final[dict[str, str]] = {
    "alpha": "a",
    "a": "a",
    "beta": "b",
    "b": "b",
    "pre": "rc",
    "preview": "rc",
    "rc": "rc",
    "dev": ".dev",
}
_REPEATED_SEPARATORS_PATTERN = re.compile(r"[-_.]{2,}")
_TAG_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
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


def _split_prerelease(suffix: str) -> tuple[str, str]:
    """Split a tag suffix into a PEP 440 pre-release segment and the variant."""
    prerelease = _TAG_PRERELEASE_PATTERN.search(suffix)
    if prerelease is None:
        variant = suffix
        segment = ""
    else:
        variant = suffix[: prerelease.start()] + suffix[prerelease.end() :]
        label = _PRERELEASE_SEGMENTS[prerelease.group("label").lower()]
        segment = f"{label}{prerelease.group('number') or 0}"
    variant = _REPEATED_SEPARATORS_PATTERN.sub("-", variant).strip("-_.")
    return segment, variant


def _analyze_version_tag(tag_info: TagInfo, tag_name: str) -> EnhancedTagInfo | None:
    """Classify numeric tags such as ``16``, ``1.25-alpine`` or ``v2.0.0-rc1``."""
    version_match = _TAG_VERSION_PATTERN.match(tag_name)
    if version_match is None:
        return None

    numbers = version_match.group("numbers")
    prerelease, variant = _split_prerelease(
        (version_match.group("suffix") or "").lower()
    )
    try:
        parsed_version = version.parse(f"{numbers}{prerelease}")
    except InvalidVersion as error:
        return _custom_tag_result(tag_info, parse_error=f"Invalid version: {error}")

    prefix = (version_match.group("prefix") or "").lower()
    return EnhancedTagInfo(
        tag_info=tag_info,
        tag_type=TagType.SEMVER,
        version_info=parsed_version,
        family=f"{prefix}|{numbers.count('.') + 1}|{variant}",
    )


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


def _analyze_date_tag(tag_info: TagInfo, tag_name: str) -> EnhancedTagInfo | None:
    """Classify date tags such as ``20240115`` or ``2024-01-15``."""
    date_match = _TAG_DATE_PATTERN.match(tag_name)
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
        family=re.sub(r"\d", "9", tag_name),
    )


class TagAnalyzer:
    """Classify Docker tags so only comparable tags are compared."""

    LATEST_TAG_NAMES = _LATEST_TAG_NAMES
    SHA_PATTERN = _TAG_SHA_PATTERN

    @classmethod
    def analyze_tag(cls, tag_info: TagInfo) -> EnhancedTagInfo:
        """Analyze Docker tag metadata and classify it."""
        if not tag_info or not tag_info.name:
            return _invalid_tag_result(tag_info, "Empty or invalid tag info")

        tag_name = tag_info.name.strip()
        if not tag_name:
            return _invalid_tag_result(tag_info, "Empty tag name")

        if tag_name.lower() in cls.LATEST_TAG_NAMES:
            return EnhancedTagInfo(tag_info, TagType.LATEST)

        # Dates and numbers first: "20240115" is a date, not a short SHA.
        for analyzer in (_analyze_date_tag, _analyze_version_tag):
            analyzed = analyzer(tag_info, tag_name)
            if analyzed is not None:
                return analyzed

        if cls.SHA_PATTERN.match(tag_name.lower()):
            return EnhancedTagInfo(tag_info, TagType.SHA)
        return _custom_tag_result(tag_info)


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
                except ValueError:
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


def _image_attrs(image: object) -> dict[str, object]:
    image_attrs = getattr(image, "attrs", None)
    return image_attrs if isinstance(image_attrs, dict) else {}


def _repo_digests_by_name(image: object) -> dict[str, str]:
    """Map each repository an image was pulled from to the digest Docker recorded."""
    repo_digests = _image_attrs(image).get("RepoDigests")
    if not isinstance(repo_digests, list):
        return {}

    digests: dict[str, str] = {}
    for entry in repo_digests:
        if not isinstance(entry, str):
            continue
        name, _, digest = entry.partition("@")
        if not _DIGEST_PATTERN.fullmatch(digest):
            continue
        with suppress(ValueError):
            digests.setdefault(parse_image_reference(name).canonical_name, digest)
    return digests


def _process_local_image_tags(
    image: object,
    local_images: LocalImageInfo,
    *,
    log: Any,
) -> None:
    """Add every valid tag of ``image`` with the digest pulled for its repository."""
    created_at = normalize_created_at(_image_attrs(image).get("Created"))
    digests = _repo_digests_by_name(image)

    image_tags = getattr(image, "tags", None)
    for tag in image_tags if isinstance(image_tags, list) else []:
        if not isinstance(tag, str) or not tag.strip():
            continue
        try:
            reference = parse_image_reference(tag)
        except ValueError:
            log.warning("docker.updates.invalid.tag.warn")
            continue
        if len(reference.repository) > 255:
            continue

        local_images.setdefault(reference.repository, []).append(
            {
                "tag": reference.tag,
                "created_at": created_at,
                # None means the tag was never pulled from this repository.
                "digest": digests.get(reference.canonical_name),
            }
        )


def _is_newer_version(
    local_version: version.Version | None, remote_version: version.Version | None
) -> bool:
    if local_version is None or remote_version is None:
        return False
    if remote_version.is_prerelease and not local_version.is_prerelease:
        return False
    return (
        remote_version.major == local_version.major and remote_version > local_version
    )


def _compare_enhanced_tags(
    local_tag: EnhancedTagInfo,
    remote_tag: EnhancedTagInfo,
) -> bool:
    """Return True when ``remote_tag`` is a newer release on the same release line."""
    if (
        local_tag.tag_type != remote_tag.tag_type
        or local_tag.family != remote_tag.family
    ):
        return False

    if local_tag.tag_type == TagType.SEMVER:
        return _is_newer_version(local_tag.version_info, remote_tag.version_info)
    if local_tag.tag_type == TagType.DATE:
        return (
            local_tag.date_info is not None
            and remote_tag.date_info is not None
            and remote_tag.date_info > local_tag.date_info
        )
    # latest, SHA and custom tags only update through a new digest.
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
    """Find newer remote tags for a local tag, newest first, without duplicates."""
    with log.context(
        action="find_updates",
        tag=local_tag.name,
        tag_type=local_tag.tag_type.name,
    ):
        if not local_tag.is_valid:
            return []

        candidates: dict[str, EnhancedTagInfo] = {}
        for remote_tag in remote_tags:
            if not remote_tag.is_valid or remote_tag.name in candidates:
                continue
            if remote_tag.name == local_tag.name:
                is_update = bool(local_tag.digest and remote_tag.digest) and (
                    not digests_equal(local_tag, remote_tag)
                )
            else:
                is_update = compare_versions(local_tag, remote_tag)
            if is_update:
                candidates[remote_tag.name] = remote_tag

        newest_first = sorted(candidates.values(), reverse=True)
        return [
            UpdateInfo(
                current_tag=local_tag.name,
                newer_tag=tag.name,
                created_at_local=local_tag.created_at,
                created_at_remote=tag.created_at,
                current_digest=local_tag.digest or "",
            )
            for tag in newest_first[:MAX_UPDATES_PER_REPO]
        ]


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    """Parse a ``Retry-After`` header given as delay-seconds or as an HTTP-date."""
    if value is None:
        return None
    text = value.strip()
    if _RETRY_AFTER_SECONDS_PATTERN.fullmatch(text):
        return int(text)
    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delay = (retry_at - (now or datetime.now(UTC))).total_seconds()
    return max(0, math.ceil(delay))


class RateLimitHandler:
    """Remember Docker Hub rate limits so later lookups wait instead of retrying."""

    def __init__(self) -> None:
        self._blocked_until: float = 0.0
        self._consecutive_limits: int = 0
        self._lock = RLock()

    def retry_after(self) -> int | None:
        """Seconds until requests may resume, or None when not rate limited."""
        with self._lock:
            remaining = self._blocked_until - time.time()
        return math.ceil(remaining) if remaining > 0 else None

    def handle_rate_limit(self, retry_after: int | None = None) -> None:
        """Record a rate limit; honour Retry-After when Docker Hub sent one."""
        with self._lock:
            self._consecutive_limits += 1
            if retry_after is None:
                multiplier = 2 if self._consecutive_limits > 5 else 1
                retry_after = RATE_LIMIT_BACKOFF * multiplier
            backoff = min(max(retry_after, 1), MAX_RATE_LIMIT_BACKOFF)
            self._blocked_until = max(self._blocked_until, time.time() + backoff)

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


def _request_timeout(timeout: int) -> ClientTimeout:
    return ClientTimeout(total=timeout, connect=min(CONNECT_TIMEOUT, timeout))


def _tag_info_from_entry(entry: object) -> TagInfo | None:
    """Build TagInfo from one Docker Hub result, dropping malformed entries."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not _TAG_NAME_PATTERN.fullmatch(name):
        return None
    pushed_at = entry.get("tag_last_pushed") or entry.get("last_updated")
    digest = entry.get("digest")
    return TagInfo(
        name=name,
        created_at=pushed_at if isinstance(pushed_at, str) else "",
        digest=digest
        if isinstance(digest, str) and _DIGEST_PATTERN.fullmatch(digest)
        else None,
    )


def _parse_tag_results(
    payload: object, *, analyzer: TagAnalyzer
) -> list[EnhancedTagInfo]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ValueError("Docker Hub response has no tag list")

    tags_info: list[EnhancedTagInfo] = []
    for entry in results[:MAX_TAGS_PER_REPO]:
        tag_info = _tag_info_from_entry(entry)
        if tag_info is None:
            continue
        enhanced_tag = analyzer.analyze_tag(tag_info)
        if enhanced_tag.is_valid:
            tags_info.append(enhanced_tag)
    return tags_info


async def _fetch_tags_from_registry_url(
    session: ClientSession,
    url: str,
    *,
    timeout: int,
    analyzer: TagAnalyzer,
    stats: dict[str, int],
    log: Any,
) -> list[EnhancedTagInfo]:
    """Fetch one page of tags; retry once on timeouts and transient errors."""
    attempt = 1
    while True:
        stats["api_calls"] += 1
        try:
            async with session.get(url, timeout=_request_timeout(timeout)) as response:
                response.raise_for_status()
                payload = await response.json()
            return _parse_tag_results(payload, analyzer=analyzer)
        except ClientResponseError as error:
            if error.status < 500 or attempt >= MAX_ATTEMPTS:
                raise
        except (TimeoutError, ClientConnectionError):
            if attempt >= MAX_ATTEMPTS:
                raise

        log.debug("docker.updates.fetch.retry.debug", attempt=attempt)
        attempt += 1
        await asyncio.sleep(RETRY_DELAY)


def _response_failure(
    error: ClientResponseError,
    *,
    rate_limiter: RateLimitHandler,
    stats: dict[str, int],
    log: Any,
) -> RegistryCheckError:
    """Classify an HTTP error response from Docker Hub."""
    if error.status == 429:
        stats["rate_limits"] += 1
        headers = error.headers
        rate_limiter.handle_rate_limit(
            parse_retry_after(headers.get("Retry-After") if headers else None)
        )
        retry_after = rate_limiter.retry_after()
        log.warning("docker.updates.rate.limited.warn", retry_after=retry_after)
        return RegistryCheckError(
            CheckFailure.RATE_LIMITED, retry_after=retry_after, status_code=429
        )

    stats["errors"] += 1
    log.warning("docker.updates.http.fail", status_code=error.status)
    if error.status < 400:
        # aiohttp reports a non-JSON body on a successful response this way.
        return RegistryCheckError(CheckFailure.INVALID_RESPONSE)
    reason = _STATUS_FAILURES.get(error.status, CheckFailure.REGISTRY_ERROR)
    return RegistryCheckError(reason, status_code=error.status)


async def _fetch_classified_tags(
    session: ClientSession,
    url: str,
    repo: str,
    *,
    rate_limiter: RateLimitHandler,
    stats: dict[str, int],
    log: Any,
    fetch_tags_from_url: Callable[
        [ClientSession, str, str], Coroutine[object, object, list[EnhancedTagInfo]]
    ],
) -> list[EnhancedTagInfo]:
    """Fetch tags and turn every expected failure into a RegistryCheckError."""
    try:
        return await fetch_tags_from_url(session, url, repo)
    except ClientResponseError as error:
        raise _response_failure(
            error, rate_limiter=rate_limiter, stats=stats, log=log
        ) from error
    except TimeoutError as error:
        stats["errors"] += 1
        log.warning("docker.updates.fetch.timeout.warn")
        raise RegistryCheckError(CheckFailure.TIMEOUT) from error
    except ClientError as error:
        stats["errors"] += 1
        log.warning("docker.updates.fetch.fail", error=sanitize_exception(error))
        raise RegistryCheckError(CheckFailure.NETWORK_ERROR) from error
    except ValueError as error:
        stats["errors"] += 1
        log.warning(
            "docker.updates.fetch.invalid.warn", error=sanitize_exception(error)
        )
        raise RegistryCheckError(CheckFailure.INVALID_RESPONSE) from error


async def _fetch_remote_tags_for_repository(
    session: ClientSession,
    repo: str,
    *,
    cache: _UpdaterTagCache,
    rate_limiter: RateLimitHandler,
    stats: dict[str, int],
    log: Any,
    fetch_tags_from_url: Callable[
        [ClientSession, str, str], Coroutine[object, object, list[EnhancedTagInfo]]
    ],
) -> list[EnhancedTagInfo]:
    """Fetch Docker Hub tags for a local repository, using cache and rate limits."""
    try:
        reference = parse_image_reference(repo)
    except ValueError as error:
        raise RegistryCheckError(CheckFailure.UNSUPPORTED_REGISTRY) from error
    url = _docker_hub_tags_url(reference)
    if url is None:
        raise RegistryCheckError(CheckFailure.UNSUPPORTED_REGISTRY)

    cached_tags = cache.get_valid(reference.canonical_name, time.time())
    if cached_tags is not None:
        stats["cache_hits"] += 1
        return cached_tags

    retry_after = rate_limiter.retry_after()
    if retry_after is not None:
        log.debug("docker.updates.skipping.due.debug", retry_after=retry_after)
        raise RegistryCheckError(CheckFailure.RATE_LIMITED, retry_after=retry_after)

    stats["cache_misses"] += 1
    with log.context(action="fetch_remote_tags", repository=reference.canonical_name):
        tags_info = await _fetch_classified_tags(
            session,
            url,
            repo,
            rate_limiter=rate_limiter,
            stats=stats,
            log=log,
            fetch_tags_from_url=fetch_tags_from_url,
        )
    rate_limiter.handle_success()
    if not tags_info:
        raise RegistryCheckError(CheckFailure.NO_TAGS)

    # Only successful, non-empty lookups are cached; failures are retried next time.
    cache.set(reference.canonical_name, tags_info, time.time())
    return tags_info


def _failure_text(reason: CheckFailure, status_code: int | None) -> str:
    if reason == CheckFailure.REGISTRY_ERROR and status_code is not None:
        return f"{reason.value} (HTTP {status_code})"
    return reason.value


def _reference_result(
    repository: str, tag_entry: LocalTagEntry, updates: list[UpdateInfo]
) -> ReferenceResult:
    return {
        "repository": repository,
        "tag": tag_entry.get("tag") or "latest",
        "created_at": tag_entry.get("created_at") or "",
        "updates": [update.model_dump() for update in updates],
    }


def _failure_results(
    repository: str,
    local_tags: Sequence[LocalTagEntry],
    reason: CheckFailure,
    *,
    retry_after: int | None = None,
    status_code: int | None = None,
) -> CheckResults:
    results: CheckResults = {}
    for tag_entry in local_tags:
        result = _reference_result(repository, tag_entry, [])
        result["error"] = _failure_text(reason, status_code)
        result["reason"] = reason.name
        if retry_after is not None:
            result["retry_after"] = retry_after
        results[f"{repository}:{result['tag']}"] = result
    return results


def _split_checkable_tags(
    repository: str, local_tags: Sequence[LocalTagEntry]
) -> tuple[CheckResults, list[LocalTagEntry]]:
    """Resolve images Docker Hub cannot answer for; return the ones to look up."""
    try:
        reference: ImageReference | None = parse_image_reference(repository)
    except ValueError:
        reference = None
    if reference is None or _docker_hub_tags_url(reference) is None:
        return (
            _failure_results(repository, local_tags, CheckFailure.UNSUPPORTED_REGISTRY),
            [],
        )

    pulled = [tag for tag in local_tags if tag.get("digest")]
    built_locally = [tag for tag in local_tags if not tag.get("digest")]
    return (
        _failure_results(repository, built_locally, CheckFailure.LOCAL_IMAGE),
        pulled,
    )


def _local_tag_result(
    repository: str,
    tag_entry: LocalTagEntry,
    remote_tags: list[EnhancedTagInfo],
    *,
    analyzer: TagAnalyzer,
    log: Any,
) -> CheckResults:
    local_tag = analyzer.analyze_tag(dict_to_tag_info(tag_entry))
    updates = _find_compatible_tag_updates(
        local_tag,
        remote_tags,
        log=log,
        compare_versions=_compare_enhanced_tags,
        digests_equal=_tag_digests_equal,
    )
    if not updates and all(tag.name != local_tag.name for tag in remote_tags):
        # Without the tag itself on Docker Hub there is nothing to compare with.
        return _failure_results(repository, [tag_entry], CheckFailure.TAG_NOT_FOUND)
    result = _reference_result(repository, tag_entry, updates)
    return {f"{repository}:{result['tag']}": result}


async def _check_repository(
    session: ClientSession,
    repository: str,
    local_tags: list[LocalTagEntry],
    *,
    fetch_remote_tags: RemoteTagsFetcher,
    analyzer: TagAnalyzer,
    log: Any,
) -> CheckResults:
    """Look up one Docker Hub repository and compare every pulled local tag."""
    try:
        remote_tags = await fetch_remote_tags(session, repository)
    except RegistryCheckError as error:
        return _failure_results(
            repository,
            local_tags,
            error.reason,
            retry_after=error.retry_after,
            status_code=error.status_code,
        )

    results: CheckResults = {}
    for tag_entry in local_tags:
        results.update(
            _local_tag_result(
                repository, tag_entry, remote_tags, analyzer=analyzer, log=log
            )
        )
    return results


def _collect_task_results(
    task: "asyncio.Future[CheckResults]",
    repository: str,
    local_tags: list[LocalTagEntry],
    *,
    log: Any,
) -> CheckResults:
    if task.cancelled():
        return _failure_results(repository, local_tags, CheckFailure.TIMEOUT)
    error = task.exception()
    if error is None:
        return task.result()
    if not isinstance(error, Exception):
        raise error
    log.error(
        "docker.updates.repository.processing.fail",
        repository=repository,
        error=sanitize_exception(error),
    )
    return _failure_results(repository, local_tags, CheckFailure.INTERNAL_ERROR)


async def _check_repositories(
    session: ClientSession,
    pending: dict[str, list[LocalTagEntry]],
    *,
    deadline: float,
    check_repository: RepositoryChecker,
    log: Any,
) -> tuple[CheckResults, bool]:
    """Check repositories concurrently; cancel whatever outlives ``deadline``."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REPOS)

    async def _limited(
        repository: str, local_tags: list[LocalTagEntry]
    ) -> CheckResults:
        async with semaphore:
            return await check_repository(session, repository, local_tags)

    tasks = {
        asyncio.ensure_future(_limited(repository, local_tags)): repository
        for repository, local_tags in pending.items()
    }
    _, unfinished = await asyncio.wait(tasks, timeout=max(deadline, 0.0))
    for task in unfinished:
        task.cancel()
    if unfinished:
        log.warning("docker.updates.deadline.exceeded.warn", pending=len(unfinished))
        await asyncio.wait(unfinished)

    results: CheckResults = {}
    for task, repository in tasks.items():
        results.update(
            _collect_task_results(task, repository, pending[repository], log=log)
        )
    return results, bool(unfinished)


def _open_registry_session(timeout: int) -> ClientSession:
    connector = aiohttp.TCPConnector(
        limit=MAX_CONCURRENT_REPOS,
        # Never make a request wait for a pooled connection: aiohttp counts
        # that wait against the request timeout.
        limit_per_host=MAX_CONCURRENT_REPOS,
        ttl_dns_cache=300,
        use_dns_cache=True,
    )
    return ClientSession(
        timeout=_request_timeout(timeout),
        connector=connector,
        headers={"User-Agent": _USER_AGENT},
    )


def _summarize_results(
    results: CheckResults,
) -> tuple[UpdaterStatus, str, int, int, list[str]]:
    """Derive status, message and counters from per-image results."""
    processed = sum(1 for result in results.values() if not result.get("error"))
    failed_reasons = {
        label: str(result.get("reason"))
        for label, result in results.items()
        if result.get("error") and result.get("reason") not in _SKIPPED_FAILURES
    }
    rate_limited = [
        label
        for label, reason in failed_reasons.items()
        if reason == CheckFailure.RATE_LIMITED.name
    ]
    failed = len(failed_reasons)

    if not failed:
        return (
            UpdaterStatus.SUCCESS,
            "Successfully checked for updates",
            processed,
            0,
            [],
        )
    if processed:
        message = f"Checked {processed} images, {failed} could not be checked"
        return UpdaterStatus.PARTIAL_SUCCESS, message, processed, failed, rate_limited
    if len(rate_limited) == failed:
        message = f"Rate limited for {failed} images"
        return UpdaterStatus.RATE_LIMITED, message, processed, failed, rate_limited
    return (
        UpdaterStatus.ERROR,
        "No image could be checked",
        processed,
        failed,
        rate_limited,
    )


def _build_response(
    results: CheckResults,
    *,
    deadline_exceeded: bool,
    stats: dict[str, int],
    cache: _UpdaterTagCache,
    execution_time: float,
) -> UpdaterResponse:
    status, message, processed, failed, rate_limited = _summarize_results(results)
    retry_after = max(
        (
            value
            for result in results.values()
            if isinstance(value := result.get("retry_after"), int)
        ),
        default=None,
    )
    return UpdaterResponse(
        status=status,
        message=message,
        data=results,
        metadata={
            "stats": stats.copy(),
            "rate_limited_repos": rate_limited,
            "retry_after": retry_after,
            "deadline_exceeded": deadline_exceeded,
            "cache_size": len(cache.entries),
        },
        execution_time=execution_time,
        repositories_processed=processed,
        repositories_failed=failed,
    )


async def _check_updates_async(
    local_images: LocalImageInfo,
    *,
    deadline: float,
    timeout: int,
    cache: _UpdaterTagCache,
    analyzer: TagAnalyzer,
    stats: dict[str, int],
    log: Any,
    fetch_remote_tags: RemoteTagsFetcher,
) -> UpdaterResponse:
    """Check updates for all local images within ``deadline`` seconds."""
    start_time = time.time()

    with log.context(action="check_updates"):
        if not local_images:
            return UpdaterResponse(
                status=UpdaterStatus.VALIDATION_ERROR,
                message="No local images found to check for updates",
                execution_time=time.time() - start_time,
            )

        results: CheckResults = {}
        pending: dict[str, list[LocalTagEntry]] = {}
        for repository, local_tags in local_images.items():
            skipped, checkable = _split_checkable_tags(repository, local_tags)
            results.update(skipped)
            if checkable:
                pending[repository] = checkable

        deadline_exceeded = False
        if pending:

            async def _check(
                session: ClientSession, repository: str, tags: list[LocalTagEntry]
            ) -> CheckResults:
                return await _check_repository(
                    session,
                    repository,
                    tags,
                    fetch_remote_tags=fetch_remote_tags,
                    analyzer=analyzer,
                    log=log,
                )

            async with _open_registry_session(timeout) as session:
                checked, deadline_exceeded = await _check_repositories(
                    session,
                    pending,
                    deadline=deadline,
                    check_repository=_check,
                    log=log,
                )
            results.update(checked)

        return _build_response(
            results,
            deadline_exceeded=deadline_exceeded,
            stats=stats,
            cache=cache,
            execution_time=time.time() - start_time,
        )


class DockerImageUpdater(BaseComponent):
    """
    Compare local Docker Hub images with the tags published on Docker Hub.

    Images from other registries and images that were never pulled are reported
    as not checked. Lookups are cached, honour Docker Hub rate limits and are
    bounded by an overall deadline.
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
                # Skip images removed between the list and the inspect.
                images = list_images_tolerant(adapter, include_intermediate=False)
                self._log.debug("docker.updates.found.local.debug")

                for image in images:
                    try:
                        if not image.tags:
                            skipped_count += 1
                            self._log.debug("docker.updates.skipping.image.debug")
                            continue

                        _process_local_image_tags(image, local_images, log=self._log)
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
        """Fetch Docker Hub tags for a local repository."""
        return await _fetch_remote_tags_for_repository(
            session,
            repo,
            cache=self._cache,
            rate_limiter=self.rate_limiter,
            stats=self._stats,
            log=self._log,
            fetch_tags_from_url=self._fetch_tags_from_url,
        )

    async def _fetch_tags_from_url(
        self, session: ClientSession, url: str, _repo: str
    ) -> list[EnhancedTagInfo]:
        """Fetch tags from specific URL with intelligent retry logic."""
        return await _fetch_tags_from_registry_url(
            session,
            url,
            timeout=self._timeout,
            analyzer=self.analyzer,
            stats=self._stats,
            log=self._log,
        )

    async def _check_updates(self, deadline: float = CHECK_DEADLINE) -> UpdaterResponse:
        """Check the current local images against Docker Hub."""
        return await _check_updates_async(
            self.local_images,
            deadline=deadline,
            timeout=self._timeout,
            cache=self._cache,
            analyzer=self.analyzer,
            stats=self._stats,
            log=self._log,
            fetch_remote_tags=self._fetch_remote_tags,
        )

    def check_updates(self, deadline: float = CHECK_DEADLINE) -> UpdaterResponse:
        """
        Refresh local images and check them against Docker Hub.

        Blocks the calling thread for at most about ``deadline`` seconds, so run
        it off the Telegram worker threads. Failures are returned as responses.
        """
        started = time.monotonic()
        try:
            self.initialize()
        except Exception:  # initialize() already logged the Docker failure
            return UpdaterResponse(
                status=UpdaterStatus.DOCKER_ERROR,
                message="Couldn't read local images from Docker",
                execution_time=time.monotonic() - started,
            )
        return self._run_check_safely(deadline - (time.monotonic() - started))

    def _run_check_safely(self, deadline: float) -> UpdaterResponse:
        try:
            return self._run_check_updates_sync(deadline)
        except Exception as e:
            self._log.error(
                "docker.updates.update.check.fail", error=sanitize_exception(e)
            )
            return UpdaterResponse(
                status=UpdaterStatus.ERROR,
                message=f"Failed to check for updates: {sanitize_exception(e)}",
                execution_time=0.0,
            )

    def to_dict(self) -> dict[str, object]:
        """Run update check and return dictionary response."""
        with self._log.context(action="to_dict"):
            return self._run_check_safely(CHECK_DEADLINE).to_dict()

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

    def _run_check_updates_sync(
        self, deadline: float = CHECK_DEADLINE
    ) -> UpdaterResponse:
        """Run the async check on the bridge loop, giving up after the deadline."""
        self._ensure_sync_bridge()
        loop = self._sync_bridge.loop
        if loop is None:
            raise RuntimeError("Docker updates sync bridge is unavailable")
        future = asyncio.run_coroutine_threadsafe(self._check_updates(deadline), loop)
        try:
            return future.result(timeout=max(deadline, 0.0) + BRIDGE_GRACE_SECONDS)
        except TimeoutError:
            if future.done():
                raise
            future.cancel()
            self._log.warning("docker.updates.deadline.exceeded.warn")
            return UpdaterResponse(
                status=UpdaterStatus.ERROR,
                message="Update check timed out",
                metadata={"deadline_exceeded": True},
                execution_time=max(deadline, 0.0) + BRIDGE_GRACE_SECONDS,
            )


_shared_updater: DockerImageUpdater | None = None
_shared_updater_lock = Lock()


def get_image_updater() -> DockerImageUpdater:
    """Return the process-wide updater so cache and rate-limit state persist."""
    global _shared_updater
    with _shared_updater_lock:
        if _shared_updater is None:
            _shared_updater = DockerImageUpdater()
        return _shared_updater
