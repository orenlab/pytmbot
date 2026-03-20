#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Final, ParamSpec, TypeVar

from docker import DockerClient
from docker.errors import NotFound
from docker.models.containers import Container

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.exceptions import (
    ContainerNotFoundError,
    DockerConnectionError,
    DockerOperationException,
    ErrorContext,
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


class MemoryStatsProvider:
    """Fast memory statistics provider using multiple fallback methods."""

    @staticmethod
    def from_cgroups(container_id: str) -> MemoryStats | None:
        """Get memory stats directly from cgroups - fastest method."""
        try:
            # Try cgroups v2 first (newer Docker installations)
            cgroup_v2_paths = [
                f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/memory.current",
                f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/memory.max",
            ]

            # Try cgroups v1 (older Docker installations)
            cgroup_v1_paths = [
                f"/sys/fs/cgroup/memory/docker/{container_id}/memory.usage_in_bytes",
                f"/sys/fs/cgroup/memory/docker/{container_id}/memory.limit_in_bytes",
            ]

            usage, limit = None, None

            # Check cgroups v2 (EAFP: no redundant stat() before read)
            try:
                usage = int(Path(cgroup_v2_paths[0]).read_text().strip())
                limit_str = Path(cgroup_v2_paths[1]).read_text().strip()
                limit = int(limit_str) if limit_str != "max" else None
            except (FileNotFoundError, ValueError, PermissionError):
                usage, limit = None, None

            # Check cgroups v1 if v2 failed
            if usage is None:
                try:
                    usage = int(Path(cgroup_v1_paths[0]).read_text().strip())
                    limit = int(Path(cgroup_v1_paths[1]).read_text().strip())
                except (FileNotFoundError, ValueError, PermissionError):
                    pass

            if usage is not None:
                return MemoryStatsProvider._format_memory_stats(usage, limit)

        except Exception:
            logger.debug("docker.utils.get.memory.fail")

        return None

    @staticmethod
    def from_docker_cli(container_id: str) -> MemoryStats | None:
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

    @staticmethod
    def from_inspect(container: Container) -> MemoryStats | None:
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
            else:
                return {
                    "mem_usage": "N/A",
                    "mem_limit": "No Limit",
                    "mem_percent": "N/A",
                }

        except Exception:
            logger.debug("docker.utils.get.memory.fail")
            return None

    @staticmethod
    def from_container_stats(container: Container) -> MemoryStats | None:
        """Fallback to container.stats() - slowest method."""
        try:
            stats = get_container_stats_snapshot(container)
            memory_stats_obj = stats.get("memory_stats", {})
            memory_stats = (
                memory_stats_obj if isinstance(memory_stats_obj, dict) else {}
            )
            usage_raw = memory_stats.get("usage", 0)
            limit_raw = memory_stats.get("limit", 0)
            usage = int(usage_raw) if isinstance(usage_raw, (int, float)) else 0
            limit = int(limit_raw) if isinstance(limit_raw, (int, float)) else 0

            if usage == 0 and limit == 0:
                return {"mem_usage": "N/A", "mem_limit": "N/A", "mem_percent": "N/A"}

            return MemoryStatsProvider._format_memory_stats(usage, limit)

        except Exception:
            logger.debug("docker.utils.container.stats.fail")
            return None

    @staticmethod
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
        snapshot = next(iter(stats), {}) or {}
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


@with_operation_logging("get_container_state", slow_threshold=0.5)
def get_container_state(
    container_id: str, docker_client: DockerClient | None = None
) -> str | None:
    """
    Retrieves the status of a Docker container with caching and enhanced error handling.

    Args:
        container_id: The ID of the container.

    Returns:
        Container status string or None if not found.

    Raises:
        ValueError: If container_id is invalid
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    container_id = container_id.strip()

    # Check cache first
    if cached_state := _state_cache.get(container_id):
        return cached_state

    context = build_container_context(
        container_id=container_id, action="container_state_check"
    )

    try:
        container = get_container_safely(container_id, docker_client=docker_client)
        status_raw = container.status
        status = status_raw if isinstance(status_raw, str) else str(status_raw)

        # Cache the result
        _state_cache.set(container_id, status)

        logger.debug("docker.utils.container.state.debug", status=status, **context)
        return status

    except ContainerNotFoundError:
        logger.debug("docker.utils.container.not.debug", **context)
        return None

    except Exception as e:
        logger.error(
            "docker.utils.get.container.fail",
            error=sanitize_exception(e),
            error_type=type(e).__name__,
            **context,
        )
        return None


def get_container_safely(
    container_id: str, docker_client: DockerClient | None = None
) -> Container:
    """
    Safely retrieves a container by ID with uniform error handling and validation.

    Args:
        container_id: Container ID

    Returns:
        Container: Container object

    Raises:
        ValueError: If container_id is invalid
        ContainerNotFoundError: If container is not found
        DockerOperationException: For other Docker errors
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    container_id = container_id.strip()
    context = {
        "action": "container_retrieval",
        "container_id": container_id,
        "container_id_length": len(container_id),
        "client_source": "shared" if docker_client is not None else "new",
    }
    start_time = time.time()

    try:
        if docker_client is not None:
            container = docker_client.containers.get(container_id)
        else:
            with docker_client_context() as adapter:
                container = adapter.containers.get(container_id)

        execution_time = time.time() - start_time
        logger.debug(
            "docker.utils.container.fetch.ok",
            execution_time=f"{execution_time:.3f}s",
            container_name=getattr(container, "name", "unknown"),
            container_status=getattr(container, "status", "unknown"),
            **context,
        )
        return container

    except NotFound:
        execution_time = time.time() - start_time
        logger.warning(
            "docker.utils.container.not.warn",
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise ContainerNotFoundError(
            ErrorContext(
                message=f"Container not found: {container_id}",
                error_code="DOCKER_001",
                metadata={"container_id": container_id, "search_time": execution_time},
            )
        )
    except DockerConnectionError:
        execution_time = time.time() - start_time
        logger.error(
            "docker.utils.container.connection.fail",
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "docker.utils.container.retrieval.fail",
            error=sanitize_exception(e),
            error_type=type(e).__name__,
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise DockerOperationException(
            ErrorContext(
                message=f"Failed to retrieve container: {container_id}",
                error_code="DOCKER_002",
                metadata={
                    "container_id": container_id,
                    "exception": str(e),
                    "execution_time": execution_time,
                },
            )
        )


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

    # Method 1: Direct cgroups read (fastest)
    if memory_stats := MemoryStatsProvider.from_cgroups(container_id):
        logger.debug("docker.utils.got.memory.debug")
        return memory_stats

    # Method 2: Runtime one-shot stats for running containers
    if container.status.lower() == "running":
        if memory_stats := MemoryStatsProvider.from_container_stats(container):
            logger.debug("docker.utils.got.memory.debug")
            return memory_stats

    # Method 3: Container inspect (limited but fast)
    if memory_stats := MemoryStatsProvider.from_inspect(container):
        logger.debug("docker.utils.got.memory.debug")
        return memory_stats

    # Method 4: Fallback to docker CLI for running containers
    if container.status.lower() == "running":
        if memory_stats := MemoryStatsProvider.from_docker_cli(container_id):
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

    safe_kwargs: dict[str, object] = {}
    for key, value in kwargs.items():
        key_lower = key.lower()

        if any(sensitive in key_lower for sensitive in sensitive_keys):
            safe_kwargs[key] = "[REDACTED]"
        elif isinstance(value, str):
            if len(value) > 200:
                safe_kwargs[key] = f"{value[:100]}...[TRUNCATED:{len(value)} chars]"
            elif (
                len(value) > 20
                and any(char in value for char in "abcdefABCDEF0123456789")
                and len(set(value)) > 10
            ):  # High entropy strings
                safe_kwargs[key] = f"[REDACTED:{len(value)} chars]"
            else:
                safe_kwargs[key] = value
        elif isinstance(value, (list, tuple)):
            if len(value) > 10:
                safe_kwargs[key] = f"[LIST:{len(value)} items]"
            else:
                safe_kwargs[key] = value
        elif isinstance(value, dict):
            if len(value) > 20:
                safe_kwargs[key] = f"[DICT:{len(value)} keys]"
            else:
                safe_kwargs[key] = sanitize_kwargs_for_logging(value)
        else:
            safe_kwargs[key] = value

    return safe_kwargs


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
        if self._last_cleanup == 0.0:
            self._last_cleanup = time.time()

    def clear(self) -> None:
        """Clear all operation history."""
        with self._lock:
            self._operations.clear()


# Global operation tracker instance
_operation_tracker = ContainerOperationTracker()
