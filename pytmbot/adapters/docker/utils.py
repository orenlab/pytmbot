#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Final, ParamSpec, TypeVar

from docker.client import DockerClient
from docker.errors import NotFound
from docker.models.containers import Container
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.exceptions import (
    ContainerNotFoundError,
    DockerConnectionError,
    DockerOperationException,
    ErrorContext,
    InvalidContainerReferenceError,
)
from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.utils import sanitize_exception, set_naturalsize

logger = Logger()

# Type aliases for better code clarity
type ContainerName = str
type ContainerID = str
type LogContext = dict[str, object]
P = ParamSpec("P")
R = TypeVar("R")
type MemoryStats = dict[str, str]

# Module constants
STATE_CACHE_TTL: Final[float] = 2.0
STATE_CACHE_MAX_SIZE: Final[int] = 100

# Central container reference contract shared by handlers and adapter calls.
CONTAINER_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,254}$"
)
# Shortest ID prefix accepted when dockerd resolves a reference by ID prefix.
# Shorter references must match the container name exactly, so a stale or
# hex-looking name never silently targets an unrelated container.
MIN_CONTAINER_ID_PREFIX_LENGTH: Final[int] = 12

SECRET_MASK: Final[str] = "\u2022\u2022\u2022\u2022"
_SAFE_ENV_KEYS: Final[frozenset[str]] = frozenset(
    {
        "PATH",
        "TZ",
        "LANG",
        "LANGUAGE",
        "HOME",
        "HOSTNAME",
        "TERM",
        "SHELL",
        "USER",
        "PUID",
        "PGID",
        "UID",
        "GID",
        "UMASK",
        "NODE_ENV",
        "ENV",
        "ENVIRONMENT",
        "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE",
        "JAVA_HOME",
        "GOPATH",
        "VIRTUAL_ENV",
    }
)
_SAFE_ENV_KEY_PREFIXES: Final[tuple[str, ...]] = ("LC_",)
_SECRET_NAME_MARKERS: Final[tuple[str, ...]] = (
    "pass",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "key",
    "auth",
    "credential",
    "dsn",
    "apikey",
    "api-key",
    "requirepass",
)
_URL_CREDENTIALS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<prefix>\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@'\"]*):(?P<secret>[^\s@/'\"]+)@"
)
# HTTP header credentials, e.g. ``curl -H "Authorization: Bearer x"`` in a
# command line or healthcheck.
_HEADER_CREDENTIALS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<name>\b(?:Proxy-)?Authorization|\bCookie|\bX-[A-Za-z0-9-]*"
    r"(?:Key|Token|Auth|Secret|Password)[A-Za-z0-9-]*)\s*:\s*(?P<value>[^\"'\r\n]+)",
    re.IGNORECASE,
)
_FLAG_VALUE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w-])(?P<flag>--?[A-Za-z][\w.-]*)(?P<sep>=|[ \t]+)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|(?!-)[^\s;&|\"']+)"
)
_ASSIGNMENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.-])(?P<key>[A-Za-z_][A-Za-z0-9_.]*)="
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s;&|]*)"
)
_LEGACY_BUILD_ASSIGNMENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?P<keyword>ENV|ARG)(?P<gap1>[ \t]+)(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<gap2>[ \t]+)(?P<value>[^=\s][^\n]*)"
)
_TIMESTAMP_FRACTION_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\.\d{6})\d+")


class ContainerState(StrEnum):
    """Enhanced container state enumeration with validation."""

    RUNNING = "running"
    EXITED = "exited"
    STOPPED = "stopped"
    CREATED = "created"
    RESTARTING = "restarting"
    REMOVING = "removing"
    PAUSED = "paused"
    DEAD = "dead"

    @classmethod
    def from_str(cls, value: str) -> ContainerState:
        """Convert string to ContainerState with enhanced error handling."""
        if not value or not isinstance(value, str):
            raise ValueError("State value must be a non-empty string")

        normalized_value = value.lower().strip()
        try:
            return cls(normalized_value)
        except ValueError:
            valid_states = [state.value for state in cls]
            raise ValueError(
                f"Invalid container state: '{value}'. Valid states: {valid_states}"
            ) from None

    @property
    def is_active(self) -> bool:
        """Check if container state indicates active/running state."""
        return self in {self.RUNNING, self.RESTARTING}


@dataclass(slots=True)
class CacheEntry:
    """Cache entry with timestamp for TTL management."""

    data: str
    timestamp: float


class ContainerStateCache:
    """Thread-safe container state cache with TTL management."""

    def __init__(
        self, ttl: float = STATE_CACHE_TTL, max_size: int = STATE_CACHE_MAX_SIZE
    ) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._lock = RLock()
        self._ttl = ttl
        self._max_size = max_size

    def get(self, container_id: str) -> str | None:
        """Get cached container state if not expired."""
        with self._lock:
            if entry := self._cache.get(container_id):
                if time.time() - entry.timestamp < self._ttl:
                    return entry.data
                else:
                    del self._cache[container_id]
        return None

    def set(self, container_id: str, state: str) -> None:
        """Set container state in cache with TTL."""
        with self._lock:
            # Clean expired entries if cache is getting full
            if len(self._cache) >= self._max_size:
                self._cleanup_expired()

            self._cache[container_id] = CacheEntry(data=state, timestamp=time.time())

    def _cleanup_expired(self) -> None:
        """Remove expired cache entries."""
        current_time = time.time()
        expired_keys = [
            key
            for key, entry in self._cache.items()
            if current_time - entry.timestamp >= self._ttl
        ]
        for key in expired_keys:
            del self._cache[key]

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def get_stats(self) -> dict[str, object]:
        """Get cache statistics."""
        with self._lock:
            current_time = time.time()
            fresh_entries = sum(
                1
                for entry in self._cache.values()
                if current_time - entry.timestamp < self._ttl
            )
            return {
                "size": len(self._cache),
                "fresh_entries": fresh_entries,
                "ttl": self._ttl,
            }


# Global cache instance
_state_cache = ContainerStateCache()


def _format_memory_stats(usage: int, limit: int | None) -> MemoryStats:
    """Format raw memory statistics into human-readable format."""
    mem_usage = set_naturalsize(usage)
    mem_limit = set_naturalsize(limit) if limit else "No Limit"
    mem_percent = round(usage / limit * 100, 2) if limit and limit > 0 else 0

    return {
        "mem_usage": mem_usage,
        "mem_limit": mem_limit,
        "mem_percent": f"{mem_percent}%",
    }


def _memory_from_cgroups(container_id: str) -> MemoryStats | None:
    """Get memory stats directly from cgroups - fastest method."""
    try:
        cgroup_v2_paths = [
            f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/memory.current",
            f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/memory.max",
        ]
        cgroup_v1_paths = [
            f"/sys/fs/cgroup/memory/docker/{container_id}/memory.usage_in_bytes",
            f"/sys/fs/cgroup/memory/docker/{container_id}/memory.limit_in_bytes",
        ]

        usage, limit = None, None

        try:
            usage = int(Path(cgroup_v2_paths[0]).read_text().strip())
            limit_str = Path(cgroup_v2_paths[1]).read_text().strip()
            limit = int(limit_str) if limit_str != "max" else None
        except (FileNotFoundError, ValueError, PermissionError):
            usage, limit = None, None

        if usage is None:
            try:
                usage = int(Path(cgroup_v1_paths[0]).read_text().strip())
                limit = int(Path(cgroup_v1_paths[1]).read_text().strip())
            except (FileNotFoundError, ValueError, PermissionError):
                pass

        if usage is not None:
            return _format_memory_stats(usage, limit)

    except Exception:
        logger.debug("docker.utils.get.memory.fail")

    return None


def _memory_from_docker_cli(container_id: str) -> MemoryStats | None:
    """Get memory stats via Docker CLI command."""
    try:
        result = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.MemUsage}},{{.MemPerc}}",
                container_id[:12],
            ],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) == 2:
                mem_usage_raw, mem_percent = parts[0].strip(), parts[1].strip()

                if " / " in mem_usage_raw:
                    usage_part, limit_part = mem_usage_raw.split(" / ")
                    return {
                        "mem_usage": usage_part.strip(),
                        "mem_limit": limit_part.strip(),
                        "mem_percent": mem_percent,
                    }

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        logger.debug("docker.utils.get.memory.fail")

    return None


def _memory_from_inspect(container: Container) -> MemoryStats | None:
    """Get memory limit from container inspect - fast but limited."""
    try:
        host_config = container.attrs.get("HostConfig", {})
        memory_limit = host_config.get("Memory", 0)

        if memory_limit > 0:
            return {
                "mem_usage": "N/A",
                "mem_limit": set_naturalsize(memory_limit),
                "mem_percent": "N/A",
            }

        return {
            "mem_usage": "N/A",
            "mem_limit": "No Limit",
            "mem_percent": "N/A",
        }

    except Exception:
        logger.debug("docker.utils.get.memory.fail")
        return None


def _memory_from_container_stats(container: Container) -> MemoryStats | None:
    """Fallback to container.stats() - slowest method."""
    try:
        stats = get_container_stats_snapshot(container)
        memory_stats_obj = stats.get("memory_stats", {})
        memory_stats = memory_stats_obj if isinstance(memory_stats_obj, dict) else {}
        usage_raw = memory_stats.get("usage", 0)
        limit_raw = memory_stats.get("limit", 0)
        usage = int(usage_raw) if isinstance(usage_raw, (int, float)) else 0
        limit = int(limit_raw) if isinstance(limit_raw, (int, float)) else 0

        if usage == 0 and limit == 0:
            return {"mem_usage": "N/A", "mem_limit": "N/A", "mem_percent": "N/A"}

        return _format_memory_stats(usage, limit)

    except Exception:
        logger.debug("docker.utils.container.stats.fail")
        return None


@dataclass(slots=True)
class _MemoryStatsProviderFacade:
    """Typed registry preserving the historical ``MemoryStatsProvider.*`` API."""

    from_cgroups: Callable[[str], MemoryStats | None]
    from_docker_cli: Callable[[str], MemoryStats | None]
    from_inspect: Callable[[Container], MemoryStats | None]
    from_container_stats: Callable[[Container], MemoryStats | None]


MemoryStatsProvider: Final[_MemoryStatsProviderFacade] = _MemoryStatsProviderFacade(
    from_cgroups=_memory_from_cgroups,
    from_docker_cli=_memory_from_docker_cli,
    from_inspect=_memory_from_inspect,
    from_container_stats=_memory_from_container_stats,
)


def get_container_stats_snapshot(container: Container) -> dict[str, object]:
    """
    Get a single runtime stats snapshot with minimal latency.

    Prefers one-shot mode (faster on modern Docker APIs) and falls back to
    legacy non-streaming stats when one-shot isn't supported.
    """
    try:
        try:
            stats = container.stats(stream=False, one_shot=True)
        except TypeError:
            stats = container.stats(stream=False)
        except Exception as one_shot_error:
            one_shot_error_text = str(one_shot_error).lower()
            if "one-shot" in one_shot_error_text or "one_shot" in one_shot_error_text:
                stats = container.stats(stream=False)
            else:
                raise

        if isinstance(stats, dict):
            return stats

        # docker-py may return an iterator in some environments
        snapshot: object = next(iter(stats), {}) or {}
        return snapshot if isinstance(snapshot, dict) else {}

    except Exception:
        logger.debug("docker.utils.get.container.fail")
        return {}


def with_operation_logging(
    operation_name: str, slow_threshold: float = 1.0
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Enhanced decorator for logging Docker operations with timing and performance monitoring."""
    if not operation_name or not isinstance(operation_name, str):
        raise ValueError("operation_name must be a non-empty string")

    if slow_threshold <= 0:
        raise ValueError("slow_threshold must be positive")

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start_time = time.time()
            operation_id = f"{operation_name}_{int(start_time * 1000) % 10000}"
            context = _build_operation_context(
                operation_name, operation_id, start_time, args, kwargs
            )

            if getattr(settings.docker, "debug_docker_client", False):
                logger.debug("docker.utils.start", **context)

            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                _log_operation_success(
                    operation_name, context, execution_time, result, slow_threshold
                )
                return result

            except Exception as e:
                execution_time = time.time() - start_time
                _log_operation_failure(operation_name, context, execution_time, e)
                raise

        return wrapper

    return decorator


def _build_operation_context(
    operation_name: str,
    operation_id: str,
    start_time: float,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> LogContext:
    """Build context for operation logging."""
    context: LogContext = {
        "action": f"docker_{operation_name}",
        "operation": operation_name,
        "operation_id": operation_id,
        "start_time": datetime.now().isoformat(),
    }

    if args:
        context["args_count"] = len(args)
        if args and isinstance(args[0], str):
            context["container_id"] = args[0][:12]

    if kwargs:
        safe_kwargs = sanitize_kwargs_for_logging(kwargs)
        if safe_kwargs:
            context["params"] = safe_kwargs

    return context


def _log_operation_success(
    operation_name: str,
    context: LogContext,
    execution_time: float,
    result: object,
    slow_threshold: float,
) -> None:
    """Log successful operation with appropriate level based on execution time."""
    context.update(
        {
            "execution_time": f"{execution_time:.3f}s",
            "success": True,
            "result_type": type(result).__name__,
        }
    )

    if isinstance(result, (list, dict)):
        context["result_size"] = len(result)
    elif isinstance(result, str):
        context["result_length"] = len(result)

    if execution_time > slow_threshold:
        logger.warning("docker.utils.slow.ok", **context)
    elif execution_time > slow_threshold / 2:
        logger.info("docker.utils.ok", **context)
    elif getattr(settings.docker, "debug_docker_client", False):
        logger.debug("docker.utils.ok", **context)


def _log_operation_failure(
    operation_name: str, context: LogContext, execution_time: float, error: Exception
) -> None:
    """Log failed operation with error details."""
    context.update(
        {
            "execution_time": f"{execution_time:.3f}s",
            "success": False,
            "error": sanitize_exception(error),
            "error_type": type(error).__name__,
        }
    )
    logger.error("docker.utils.fail", **context)


def validate_container_reference(reference: object) -> str:
    """
    Validate a container reference (exact name or ID/ID prefix).

    The reference is never case-folded: Docker names are case-sensitive and a
    lowercased name can resolve to a different container by ID prefix.

    Raises:
        InvalidContainerReferenceError: If the reference is not a valid name/ID.
    """
    candidate = reference.strip() if isinstance(reference, str) else ""
    if (
        not candidate
        or ".." in candidate
        or not CONTAINER_REFERENCE_PATTERN.fullmatch(candidate)
    ):
        raise InvalidContainerReferenceError(
            ErrorContext(
                message="Invalid container reference",
                error_code="DOCKER_011",
                metadata={"reference_length": len(str(reference))},
            )
        )
    return candidate


def container_matches_reference(container: object, reference: str) -> bool:
    """
    Check that dockerd resolved ``reference`` to the intended container.

    dockerd resolves a reference by full ID, then exact name, then unique ID
    prefix. Only an exact name or a sufficiently long ID prefix is accepted.
    """
    name = str(getattr(container, "name", "") or "").lstrip("/")
    if name == reference:
        return True
    container_id = str(getattr(container, "id", "") or "")
    return len(reference) >= MIN_CONTAINER_ID_PREFIX_LENGTH and (
        container_id.startswith(reference)
    )


def is_docker_unavailable_error(error: BaseException) -> bool:
    """Return True when an error means Docker is unreachable or timed out."""
    return isinstance(
        error, (DockerConnectionError, RequestsConnectionError, RequestsTimeout)
    )


@contextmanager
def docker_unavailable_as_connection_error(operation: str) -> Iterator[None]:
    """Translate transport failures (refused socket, timeouts) to DockerConnectionError."""
    try:
        yield
    except (RequestsConnectionError, RequestsTimeout) as error:
        raise DockerConnectionError(
            ErrorContext(
                message=f"Docker is unavailable during {operation}",
                error_code="DOCKER_012",
                metadata={"error": sanitize_exception(error)},
            )
        ) from error


def invalidate_container_state_cache() -> None:
    """Drop cached container states (call after lifecycle actions)."""
    _state_cache.clear()


@with_operation_logging("get_container_state", slow_threshold=0.5)
def get_container_state(
    container_id: str, docker_client: DockerClient | None = None
) -> str | None:
    """
    Return the current status of a container (short-lived cache).

    Returns:
        Container status string, or None if the container does not exist.

    Raises:
        InvalidContainerReferenceError: If the reference is invalid.
        DockerConnectionError: If Docker is unavailable.
        DockerOperationException: For other Docker API failures.
    """
    reference = validate_container_reference(container_id)
    if cached_state := _state_cache.get(reference):
        return cached_state

    context = build_container_context(
        container_id=reference, action="container_state_check"
    )
    try:
        container = get_container_safely(reference, docker_client=docker_client)
    except ContainerNotFoundError:
        logger.debug("docker.utils.container.not.debug", **context)
        return None

    status_raw = container.status
    status = status_raw if isinstance(status_raw, str) else str(status_raw)
    _state_cache.set(reference, status)
    logger.debug("docker.utils.container.state.debug", status=status, **context)
    return status


def _container_not_found_error(
    reference: str, execution_time: float, *, reason: str
) -> ContainerNotFoundError:
    return ContainerNotFoundError(
        ErrorContext(
            message=f"Container not found: {reference}",
            error_code="DOCKER_001",
            metadata={
                "container_id": reference,
                "search_time": execution_time,
                "reason": reason,
            },
        )
    )


def _lookup_container(reference: str, docker_client: DockerClient | None) -> Container:
    if docker_client is not None:
        return docker_client.containers.get(reference)
    with docker_client_context() as adapter:
        return adapter.containers.get(reference)


def _translate_lookup_error(
    error: Exception, reference: str, execution_time: float, context: LogContext
) -> DockerConnectionError | DockerOperationException:
    if is_docker_unavailable_error(error):
        logger.error(
            "docker.utils.container.connection.fail",
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        return DockerConnectionError(
            ErrorContext(
                message="Docker is unavailable while resolving container",
                error_code="DOCKER_012",
                metadata={"container_id": reference},
            )
        )
    logger.error(
        "docker.utils.container.retrieval.fail",
        error=sanitize_exception(error),
        error_type=type(error).__name__,
        execution_time=f"{execution_time:.3f}s",
        **context,
    )
    return DockerOperationException(
        ErrorContext(
            message=f"Failed to retrieve container: {reference}",
            error_code="DOCKER_002",
            metadata={
                "container_id": reference,
                "exception": sanitize_exception(error),
                "execution_time": execution_time,
            },
        )
    )


def get_container_safely(
    container_id: str, docker_client: DockerClient | None = None
) -> Container:
    """
    Resolve a container by exact name or ID and verify the resolved target.

    Raises:
        InvalidContainerReferenceError: If the reference is invalid.
        ContainerNotFoundError: If no container matches, or dockerd resolved the
            reference to a different container than the one that was named.
        DockerConnectionError: If Docker is unavailable or timed out.
        DockerOperationException: For other Docker errors.
    """
    reference = validate_container_reference(container_id)
    context: LogContext = {
        "action": "container_retrieval",
        "container_id": reference,
        "container_id_length": len(reference),
        "client_source": "shared" if docker_client is not None else "new",
    }
    start_time = time.time()

    try:
        container = _lookup_container(reference, docker_client)
    except NotFound as error:
        execution_time = time.time() - start_time
        logger.warning(
            "docker.utils.container.not.warn",
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise _container_not_found_error(
            reference, execution_time, reason="no_such_container"
        ) from error
    except DockerConnectionError:
        logger.error(
            "docker.utils.container.connection.fail",
            execution_time=f"{time.time() - start_time:.3f}s",
            **context,
        )
        raise
    except Exception as error:
        raise _translate_lookup_error(
            error, reference, time.time() - start_time, context
        ) from error

    execution_time = time.time() - start_time
    if not container_matches_reference(container, reference):
        logger.warning(
            "docker.utils.container.reference.mismatch.warn",
            resolved_id=str(getattr(container, "id", ""))[:12],
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise _container_not_found_error(
            reference, execution_time, reason="resolved_to_other_container"
        )

    logger.debug(
        "docker.utils.container.fetch.ok",
        execution_time=f"{execution_time:.3f}s",
        container_name=getattr(container, "name", "unknown"),
        container_status=getattr(container, "status", "unknown"),
        **context,
    )
    return container


def parse_docker_timestamp(value: object) -> datetime | None:
    """Parse a Docker RFC3339 timestamp into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("0001-01-01"):
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(_TIMESTAMP_FRACTION_PATTERN.sub(r"\1", text))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_safe_env_key(key: str) -> bool:
    """Return True for environment keys whose values are safe to display."""
    return key in _SAFE_ENV_KEYS or key.startswith(_SAFE_ENV_KEY_PREFIXES)


def looks_like_secret_name(name: str) -> bool:
    """Return True when a flag/variable name suggests it carries a secret."""
    normalized = name.strip().lstrip("-").casefold()
    return any(marker in normalized for marker in _SECRET_NAME_MARKERS)


def mask_url_credentials(text: str) -> str:
    """Mask URL passwords: ``scheme://user:pass@`` -> ``scheme://user:****@``."""
    return _URL_CREDENTIALS_PATTERN.sub(rf"\g<prefix>:{SECRET_MASK}@", text)


def mask_environment_variables(env_list: Sequence[object]) -> list[str]:
    """
    Show environment variables as keys only.

    Keeps the ``KEY=VALUE`` shape, but replaces every value with the mask
    except for a small allowlist of clearly harmless keys.
    """
    masked: list[str] = []
    for item in env_list:
        key, separator, value = str(item).partition("=")
        if not separator or not value:
            masked.append(str(item))
        elif is_safe_env_key(key):
            masked.append(f"{key}={mask_url_credentials(value)}")
        else:
            masked.append(f"{key}={SECRET_MASK}")
    return masked


def mask_secrets_in_text(text: str, *, mask_all_assignments: bool = False) -> str:
    """
    Mask secrets inside a command line or build step.

    Masks values after secret-looking flags (``--password x``, ``--token=x``),
    ``KEY=VALUE`` assignments with secret-looking keys (every non-allowlisted
    key when ``mask_all_assignments`` is set), legacy ``ENV KEY value`` build
    steps (with ``mask_all_assignments``), HTTP header credentials and URL
    credentials.
    """

    def _mask_flag(match: re.Match[str]) -> str:
        if not looks_like_secret_name(match.group("flag")):
            return match.group(0)
        return f"{match.group('flag')}{match.group('sep')}{SECRET_MASK}"

    def _mask_assignment(match: re.Match[str]) -> str:
        key = match.group("key")
        should_mask = mask_all_assignments or looks_like_secret_name(key)
        if not match.group("value") or is_safe_env_key(key) or not should_mask:
            return match.group(0)
        return f"{key}={SECRET_MASK}"

    def _mask_legacy(match: re.Match[str]) -> str:
        if is_safe_env_key(match.group("key")):
            return match.group(0)
        prefix = match.group(0)[: match.start("value") - match.start(0)]
        return f"{prefix}{SECRET_MASK}"

    masked = _HEADER_CREDENTIALS_PATTERN.sub(rf"\g<name>: {SECRET_MASK}", text)
    masked = _FLAG_VALUE_PATTERN.sub(_mask_flag, masked)
    masked = _ASSIGNMENT_PATTERN.sub(_mask_assignment, masked)
    if mask_all_assignments:
        masked = _LEGACY_BUILD_ASSIGNMENT_PATTERN.sub(_mask_legacy, masked)
    return mask_url_credentials(masked)


def _is_secret_flag_awaiting_value(argument: str) -> bool:
    return (
        argument.startswith("-")
        and "=" not in argument
        and not any(char.isspace() for char in argument)
        and looks_like_secret_name(argument)
    )


def mask_command_args(arguments: Sequence[object]) -> list[str]:
    """Mask secrets in an argv list (Cmd/Entrypoint), including ``--flag value``."""
    masked: list[str] = []
    mask_next = False
    for raw_argument in arguments:
        argument = str(raw_argument)
        if mask_next and not argument.startswith("-"):
            masked.append(SECRET_MASK)
            mask_next = False
            continue
        mask_next = _is_secret_flag_awaiting_value(argument)
        masked.append(mask_secrets_in_text(argument))
    return masked


def get_container_memory_stats(container: Container) -> MemoryStats:
    """
    Get container memory stats using the fastest available method.

    Tries methods in order of speed and reliability:
    1. cgroups direct read (fastest)
    2. container.stats() one-shot (fast and detailed)
    3. container inspect (very fast, limited info)
    4. docker CLI fallback (slowest, external process)

    Args:
        container: Docker container object

    Returns:
        Dictionary with memory statistics
    """
    container_id = container.id
    is_running = container.status.lower() == "running"

    # Method 1: Direct cgroups read (fastest)
    memory_stats = MemoryStatsProvider.from_cgroups(container_id)

    # Method 2: Runtime one-shot stats for running containers
    if not memory_stats and is_running:
        memory_stats = MemoryStatsProvider.from_container_stats(container)

    # Method 3: Container inspect (limited but fast)
    if not memory_stats:
        memory_stats = MemoryStatsProvider.from_inspect(container)

    # Method 4: Fallback to docker CLI for running containers
    if not memory_stats and is_running:
        memory_stats = MemoryStatsProvider.from_docker_cli(container_id)

    if memory_stats:
        logger.debug("docker.utils.got.memory.debug")
        return memory_stats

    # Ultimate fallback
    return {
        "mem_usage": "Unavailable",
        "mem_limit": "Unavailable",
        "mem_percent": "N/A",
    }


def sanitize_kwargs_for_logging(kwargs: dict[str, object]) -> dict[str, object]:
    """
    Enhanced sanitization of kwargs for safe logging by removing sensitive information.

    Args:
        kwargs: Dictionary of parameters

    Returns:
        Dict: Sanitized parameter dictionary
    """
    if not isinstance(kwargs, dict):
        return {}

    sensitive_keys = {
        "password",
        "passwd",
        "pass",
        "pwd",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "secret",
        "api_secret",
        "client_secret",
        "key",
        "private_key",
        "public_key",
        "api_key",
        "auth",
        "authorization",
        "credential",
        "credentials",
        "cert",
        "certificate",
        "ca_cert",
        "session",
        "session_id",
        "cookie",
    }

    def sanitize_value(key: str, value: object) -> object:
        key_lower = key.lower()

        if any(sensitive in key_lower for sensitive in sensitive_keys):
            return "[REDACTED]"

        if isinstance(value, str):
            if len(value) > 200:
                return f"{value[:100]}...[TRUNCATED:{len(value)} chars]"
            if (
                len(value) > 20
                and any(char in value for char in "abcdefABCDEF0123456789")
                and len(set(value)) > 10
            ):  # High entropy strings
                return f"[REDACTED:{len(value)} chars]"
            return value

        if isinstance(value, (list, tuple)):
            return f"[LIST:{len(value)} items]" if len(value) > 10 else value

        if isinstance(value, dict):
            return (
                f"[DICT:{len(value)} keys]"
                if len(value) > 20
                else sanitize_kwargs_for_logging(value)
            )

        return value

    return {key: sanitize_value(key, value) for key, value in kwargs.items()}


def build_container_context(
    container_id: str, action: str, **extra_context: object
) -> LogContext:
    """
    Creates a standard context for logging container operations with validation.

    Args:
        container_id: Container ID
        action: Action name
        **extra_context: Additional context fields

    Returns:
        Dict: Logging context

    Raises:
        ValueError: If required parameters are invalid
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    if not action or not isinstance(action, str):
        raise ValueError("action must be a non-empty string")

    context: LogContext = {
        "action": action.strip(),
        "container_id": container_id.strip(),
        "timestamp": datetime.now().isoformat(),
    }

    if extra_context:
        sanitized_extra = sanitize_kwargs_for_logging(extra_context)
        context.update(sanitized_extra)

    return context


@dataclass(slots=True)
class ContainerOperationTracker:
    """Track container operations for monitoring and rate limiting."""

    _operations: dict[str, list[float]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    _max_history: int = 100
    _cleanup_interval: float = 300.0  # 5 minutes
    _last_cleanup: float = 0.0

    def __post_init__(self) -> None:
        """Initialize tracker components."""
        if self._last_cleanup <= 0.0:
            self._last_cleanup = time.time()

    def clear(self) -> None:
        """Clear all operation history."""
        with self._lock:
            self._operations.clear()


# Global operation tracker instance
_operation_tracker = ContainerOperationTracker()
