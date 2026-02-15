#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import wraps
from pathlib import Path
from threading import RLock
from time import sleep
from typing import TYPE_CHECKING, Any, Final, TypeAlias

from docker.errors import NotFound
from docker.models.containers import Container

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.exceptions import (
    ContainerNotFoundError,
    DockerOperationException,
    ErrorContext,
)
from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.models.docker_models import ContainersState
from pytmbot.utils import sanitize_exception, set_naturalsize

if TYPE_CHECKING:
    from collections.abc import Callable

logger = Logger()

# Type aliases for better code clarity
ContainerName: TypeAlias = str
ContainerID: TypeAlias = str
LogContext: TypeAlias = dict[str, Any]
MemoryStats: TypeAlias = dict[str, str]

# Module constants
MAX_STATE_CHECK_ATTEMPTS: Final[int] = 5
DEFAULT_STATE_CHECK_INTERVAL: Final[float] = 1.5
MIN_STATE_CHECK_INTERVAL: Final[float] = 0.5
MAX_STATE_CHECK_INTERVAL: Final[float] = 5.0
OPERATION_TIMEOUT: Final[float] = 30.0
STATE_CACHE_TTL: Final[float] = 2.0
STATE_CACHE_MAX_SIZE: Final[int] = 100


class ContainerState(str, Enum):
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

    @property
    def is_stopped(self) -> bool:
        """Check if container state indicates stopped state."""
        return self in {self.EXITED, self.STOPPED, self.CREATED}

    @property
    def is_transitional(self) -> bool:
        """Check if container state indicates transitional state."""
        return self in {self.RESTARTING, self.REMOVING}


@dataclass(frozen=True, slots=True)
class StateCheckConfig:
    """Configuration for container state checking with validation."""

    max_attempts: int = MAX_STATE_CHECK_ATTEMPTS
    interval: float = DEFAULT_STATE_CHECK_INTERVAL

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if not isinstance(self.max_attempts, int) or self.max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")

        if not isinstance(self.interval, (int, float)) or self.interval <= 0:
            raise ValueError("interval must be a positive number")

        # Clamp interval to reasonable bounds
        if not (MIN_STATE_CHECK_INTERVAL <= self.interval <= MAX_STATE_CHECK_INTERVAL):
            object.__setattr__(
                self,
                "interval",
                max(
                    MIN_STATE_CHECK_INTERVAL,
                    min(self.interval, MAX_STATE_CHECK_INTERVAL),
                ),
            )


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

    def get_stats(self) -> dict[str, Any]:
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

            # Check cgroups v2
            if Path(cgroup_v2_paths[0]).exists():
                try:
                    usage = int(Path(cgroup_v2_paths[0]).read_text().strip())
                    limit_str = Path(cgroup_v2_paths[1]).read_text().strip()
                    limit = int(limit_str) if limit_str != "max" else None
                except (FileNotFoundError, ValueError, PermissionError):
                    usage, limit = None, None

            # Check cgroups v1 if v2 failed
            if usage is None and Path(cgroup_v1_paths[0]).exists():
                try:
                    usage = int(Path(cgroup_v1_paths[0]).read_text().strip())
                    limit = int(Path(cgroup_v1_paths[1]).read_text().strip())
                except (FileNotFoundError, ValueError, PermissionError):
                    pass

            if usage is not None:
                return MemoryStatsProvider._format_memory_stats(usage, limit)

        except Exception as e:
            logger.debug(f"Failed to get memory from cgroups for {container_id}: {e}")

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
                timeout=2,
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

        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as e:
            logger.debug(f"Failed to get memory via docker CLI for {container_id}: {e}")

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

        except Exception as e:
            logger.debug(f"Failed to get memory from inspect: {e}")
            return None

    @staticmethod
    def from_container_stats(container: Container) -> MemoryStats | None:
        """Fallback to container.stats() - slowest method."""
        try:
            stats = get_container_stats_snapshot(container)
            memory_stats = stats.get("memory_stats", {})
            usage = memory_stats.get("usage", 0)
            limit = memory_stats.get("limit", 0)

            if usage == 0 and limit == 0:
                return {"mem_usage": "N/A", "mem_limit": "N/A", "mem_percent": "N/A"}

            return MemoryStatsProvider._format_memory_stats(usage, limit)

        except Exception as e:
            logger.debug(f"container.stats() failed: {e}")
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


def get_container_stats_snapshot(container: Container) -> dict[str, Any]:
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

    except Exception as e:
        logger.debug(f"Failed to get container stats snapshot: {e}")
        return {}


def check_container_state(
    container_name: ContainerName,
    target_state: str = ContainerState.RUNNING,
    config: StateCheckConfig | None = None,
) -> ContainerState | None:
    """
    Checks if container reaches target state within configured attempts.

    Args:
        container_name: Container identifier
        target_state: Desired container state
        config: Check configuration parameters

    Returns:
        Final container state or None on error

    Raises:
        ValueError: If target state is invalid or container_name is empty
        DockerOperationException: If Docker operations fail
    """
    if not container_name or not isinstance(container_name, str):
        raise ValueError("container_name must be a non-empty string")

    if config is None:
        config = StateCheckConfig()

    try:
        target = ContainerState.from_str(target_state)
        containers_state = ContainersState()

        # Validate target state exists in containers state model
        if target.value not in containers_state.__dict__.values():
            raise ValueError(f"Invalid target state: {target}")

        return _execute_state_check_loop(container_name, target, config)

    except ValueError:
        logger.error(
            "Invalid target state", container=container_name, state=target_state
        )
        raise
    except Exception as e:
        logger.error(
            "Unexpected error during state check",
            container=container_name,
            target_state=target_state,
            error=sanitize_exception(e),
        )
        raise


def _execute_state_check_loop(
    container_name: str, target: ContainerState, config: StateCheckConfig
) -> ContainerState | None:
    """Execute the state checking loop with proper logging and timing."""
    operation_start = time.time()
    current_state = None

    for attempt in range(1, config.max_attempts + 1):
        attempt_start = time.time()
        log_context = _build_state_check_context(
            container_name, target, attempt, config, operation_start
        )

        logger.debug(
            f"Checking state (attempt {attempt}/{config.max_attempts})", **log_context
        )

        try:
            current_state_str = get_container_state(container_name)
            if current_state_str is None:
                logger.error("Failed to get container state", **log_context)
                return None

            current_state = ContainerState.from_str(current_state_str)
            attempt_time = time.time() - attempt_start
            log_context.update(
                {"state": current_state.value, "attempt_time": f"{attempt_time:.3f}s"}
            )

            if current_state == target:
                total_time = time.time() - operation_start
                logger.info(
                    "Target state reached",
                    total_time=f"{total_time:.2f}s",
                    **log_context,
                )
                return current_state

            _log_state_transition_info(current_state, target, log_context)

            if attempt < config.max_attempts:
                logger.debug(
                    f"State mismatch: {current_state.value}, retrying in {config.interval}s",
                    **log_context,
                )
                sleep(config.interval)

        except Exception as e:
            attempt_time = time.time() - attempt_start
            logger.error(
                "State check failed",
                error=sanitize_exception(e),
                error_type=type(e).__name__,
                attempt_time=f"{attempt_time:.3f}s",
                **log_context,
            )
            if attempt < config.max_attempts:
                sleep(config.interval)
            else:
                return None

    _log_final_state_check_result(
        container_name, target, current_state, config, operation_start
    )
    return current_state


def _build_state_check_context(
    container_name: str,
    target: ContainerState,
    attempt: int,
    config: StateCheckConfig,
    operation_start: float,
) -> LogContext:
    """Build logging context for state check operations."""
    return {
        "container": container_name,
        "target": target.value,
        "attempt": attempt,
        "max_attempts": config.max_attempts,
        "operation_time": f"{time.time() - operation_start:.2f}s",
    }


def _log_state_transition_info(
    current_state: ContainerState, target: ContainerState, log_context: LogContext
) -> None:
    """Log information about container state transitions."""
    if current_state.is_transitional and target.is_active:
        logger.debug(
            f"Container in transitional state {current_state.value}, continuing to wait",
            **log_context,
        )
    elif current_state.is_stopped and target.is_active:
        logger.warning(
            f"Container stopped unexpectedly while waiting for {target.value}",
            **log_context,
        )


def _log_final_state_check_result(
    container_name: str,
    target: ContainerState,
    current_state: ContainerState | None,
    config: StateCheckConfig,
    operation_start: float,
) -> None:
    """Log the final result of state check operation."""
    total_time = time.time() - operation_start
    logger.warning(
        "Failed to reach target state",
        container=container_name,
        target=target.value,
        final_state=current_state.value if current_state else "unknown",
        attempts=config.max_attempts,
        total_time=f"{total_time:.2f}s",
    )


def with_operation_logging(
    operation_name: str, slow_threshold: float = 1.0
) -> Callable:
    """Enhanced decorator for logging Docker operations with timing and performance monitoring."""
    if not operation_name or not isinstance(operation_name, str):
        raise ValueError("operation_name must be a non-empty string")

    if slow_threshold <= 0:
        raise ValueError("slow_threshold must be positive")

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            operation_id = f"{operation_name}_{int(start_time * 1000) % 10000}"
            context = _build_operation_context(
                operation_name, operation_id, start_time, args, kwargs
            )

            if getattr(settings.docker, "debug_docker_client", False):
                logger.debug(f"Starting Docker operation: {operation_name}", **context)

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
    args: tuple,
    kwargs: dict[str, Any],
) -> LogContext:
    """Build context for operation logging."""
    context = {
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
    result: Any,
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
        logger.warning(
            f"Docker operation completed (SLOW): {operation_name}", **context
        )
    elif execution_time > slow_threshold / 2:
        logger.info(f"Docker operation completed: {operation_name}", **context)
    elif getattr(settings.docker, "debug_docker_client", False):
        logger.debug(f"Docker operation completed: {operation_name}", **context)


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
    logger.error(f"Docker operation failed: {operation_name}", **context)


@with_operation_logging("get_container_state", slow_threshold=0.5)
def get_container_state(container_id: str) -> str | None:
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
        container = get_container_safely(container_id)
        status = container.status

        # Cache the result
        _state_cache.set(container_id, status)

        logger.debug("Container state retrieved", status=status, **context)
        return status

    except ContainerNotFoundError:
        logger.debug("Container not found for state check", **context)
        return None

    except Exception as e:
        logger.error(
            "Failed to get container state",
            error=sanitize_exception(e),
            error_type=type(e).__name__,
            **context,
        )
        return None


def get_container_safely(container_id: str) -> Container:
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
    }
    start_time = time.time()

    try:
        with DockerAdapter() as adapter:
            container = adapter.containers.get(container_id)

            execution_time = time.time() - start_time
            logger.debug(
                "Container retrieved successfully",
                execution_time=f"{execution_time:.3f}s",
                container_name=getattr(container, "name", "unknown"),
                container_status=getattr(container, "status", "unknown"),
                **context,
            )
            return container

    except NotFound:
        execution_time = time.time() - start_time
        logger.warning(
            "Container not found", execution_time=f"{execution_time:.3f}s", **context
        )
        raise ContainerNotFoundError(
            ErrorContext(
                message=f"Container not found: {container_id}",
                error_code="DOCKER_001",
                metadata={"container_id": container_id, "search_time": execution_time},
            )
        )
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "Container retrieval failed",
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

    Tries methods in order of speed:
    1. cgroups direct read (fastest)
    2. docker CLI command (fast)
    3. container inspect (very fast, but limited info)
    4. fallback to container.stats() (slowest)

    Args:
        container: Docker container object

    Returns:
        Dictionary with memory statistics
    """
    container_id = container.id

    # Method 1: Direct cgroups read (fastest)
    if memory_stats := MemoryStatsProvider.from_cgroups(container_id):
        logger.debug(f"Got memory stats from cgroups for {container_id[:12]}")
        return memory_stats

    # Method 2: Docker CLI (fast) - only for running containers
    if container.status.lower() == "running":
        if memory_stats := MemoryStatsProvider.from_docker_cli(container_id):
            logger.debug(f"Got memory stats from Docker CLI for {container_id[:12]}")
            return memory_stats

    # Method 3: Container inspect (limited but fast)
    if memory_stats := MemoryStatsProvider.from_inspect(container):
        logger.debug(f"Got memory limit from inspect for {container_id[:12]}")
        return memory_stats

    # Method 4: Fallback to original stats method (slowest)
    if container.status.lower() == "running":
        if memory_stats := MemoryStatsProvider.from_container_stats(container):
            logger.debug(
                f"Got memory stats from container.stats() for {container_id[:12]}"
            )
            return memory_stats

    # Ultimate fallback
    return {
        "mem_usage": "Unavailable",
        "mem_limit": "Unavailable",
        "mem_percent": "N/A",
    }


def get_container_basic_info(container: Container) -> dict[str, Any]:
    """
    Extracts basic container information with enhanced data including memory stats.

    Args:
        container: Container object

    Returns:
        Dict: Enhanced container information

    Raises:
        ValueError: If container is None
    """
    if container is None:
        raise ValueError("Container object cannot be None")

    try:
        basic_info = _extract_basic_container_data(container)

        # Add state information if available
        if hasattr(container, "attrs") and container.attrs:
            basic_info.update(_extract_container_state_info(container.attrs))

        # Get memory statistics for running containers
        if container.status.lower() == "running":
            try:
                memory_stats = get_container_memory_stats(container)
                if memory_stats:
                    basic_info.update(memory_stats)
            except Exception as e:
                logger.debug(
                    f"Failed to get runtime stats for container {container.short_id}: {e}"
                )

        return basic_info

    except Exception as e:
        logger.warning(
            "Failed to extract complete container basic info",
            container_id=getattr(container, "id", "unknown"),
            error=sanitize_exception(e),
        )
        return _get_minimal_container_info(container)


def _extract_basic_container_data(container: Container) -> dict[str, Any]:
    """Extract basic container data without state information."""
    image_tags = []
    if hasattr(container, "image") and container.image:
        image_tags = getattr(container.image, "tags", [])

    image_name = image_tags[0] if image_tags else "unknown"

    return {
        "id": container.id,
        "short_id": container.short_id,
        "name": container.name.lstrip("/"),
        "status": container.status,
        "image": image_name,
        "image_id": getattr(container.image, "short_id", "unknown")
        if hasattr(container, "image")
        else "unknown",
        "created": getattr(container.attrs, "get", lambda k, d: d)(
            "Created", "unknown"
        ),
        "ports": getattr(container, "ports", {}),
        "labels": getattr(container, "labels", {}),
    }


def _extract_container_state_info(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """Extract container state information from attrs."""
    state = attrs.get("State", {})
    return {
        "exit_code": state.get("ExitCode"),
        "pid": state.get("Pid"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
    }


def _get_minimal_container_info(container: Container) -> dict[str, Any]:
    """Return minimal container info on error."""
    return {
        "id": getattr(container, "id", "unknown"),
        "short_id": getattr(container, "short_id", "unknown"),
        "name": getattr(container, "name", "unknown"),
        "status": getattr(container, "status", "unknown"),
        "image": "unknown",
    }


def sanitize_kwargs_for_logging(kwargs: dict[str, Any]) -> dict[str, Any]:
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

    safe_kwargs = {}
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
    container_id: str, action: str, **extra_context: Any
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

    context = {
        "action": action.strip(),
        "container_id": container_id.strip(),
        "timestamp": datetime.now().isoformat(),
    }

    if extra_context:
        sanitized_extra = sanitize_kwargs_for_logging(extra_context)
        context.update(sanitized_extra)

    return context


def clear_state_cache() -> None:
    """Clear the container state cache."""
    _state_cache.clear()
    logger.debug("Container state cache cleared")


def get_cache_stats() -> dict[str, Any]:
    """Get comprehensive cache statistics for monitoring."""
    return _state_cache.get_stats()


def validate_container_operation_params(
    container_id: str, operation: str, **kwargs: Any
) -> dict[str, Any]:
    """
    Validate parameters for container operations.

    Args:
        container_id: Container ID to validate
        operation: Operation name
        **kwargs: Additional operation-specific parameters

    Returns:
        Dict with validated parameters

    Raises:
        ValueError: If parameters are invalid
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    if not operation or not isinstance(operation, str):
        raise ValueError("operation must be a non-empty string")

    container_id = container_id.strip()
    operation = operation.strip().lower()

    # Basic ID format validation
    if len(container_id) < 4:
        raise ValueError("container_id too short (minimum 4 characters)")

    if len(container_id) > 64:
        raise ValueError("container_id too long (maximum 64 characters)")

    # Operation-specific validation
    validated_params = {
        "container_id": container_id,
        "operation": operation,
    }

    if operation == "rename":
        new_name = kwargs.get("new_container_name", "").strip()
        if not new_name:
            raise ValueError("new_container_name required for rename operation")
        if len(new_name) > 64:
            raise ValueError("new_container_name too long (maximum 64 characters)")
        validated_params["new_container_name"] = new_name

    elif operation in {"stop", "restart"}:
        timeout = kwargs.get("timeout", 10)
        if not isinstance(timeout, (int, float)) or timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        if timeout > 300:  # 5 minutes max
            raise ValueError("timeout too large (maximum 300 seconds)")
        validated_params["timeout"] = timeout

    return validated_params


@dataclass(slots=True)
class ContainerOperationTracker:
    """Track container operations for monitoring and rate limiting."""

    _operations: dict[str, list[float]] = None
    _lock: RLock = None
    _max_history: int = 100
    _cleanup_interval: float = 300.0  # 5 minutes
    _last_cleanup: float = 0.0

    def __post_init__(self) -> None:
        """Initialize tracker components."""
        if self._operations is None:
            self._operations = {}
        if self._lock is None:
            self._lock = RLock()
        if self._last_cleanup == 0.0:
            self._last_cleanup = time.time()

    def record_operation(self, container_id: str, operation: str) -> None:
        """Record a container operation."""
        with self._lock:
            key = f"{container_id}:{operation}"
            current_time = time.time()

            if key not in self._operations:
                self._operations[key] = []

            self._operations[key].append(current_time)

            # Limit history size
            if len(self._operations[key]) > self._max_history:
                self._operations[key] = self._operations[key][-self._max_history :]

            # Periodic cleanup
            if current_time - self._last_cleanup > self._cleanup_interval:
                self._cleanup_old_operations()
                self._last_cleanup = current_time

    def get_recent_operations(
        self, container_id: str, since_seconds: float = 3600
    ) -> list[dict[str, Any]]:
        """Get recent operations for a container."""
        with self._lock:
            current_time = time.time()
            cutoff_time = current_time - since_seconds

            recent_ops = []
            for key, timestamps in self._operations.items():
                if key.startswith(f"{container_id}:"):
                    operation = key.split(":", 1)[1]
                    recent_timestamps = [ts for ts in timestamps if ts > cutoff_time]

                    if recent_timestamps:
                        recent_ops.append(
                            {
                                "operation": operation,
                                "count": len(recent_timestamps),
                                "last_time": max(recent_timestamps),
                                "first_time": min(recent_timestamps),
                            }
                        )

            return sorted(recent_ops, key=lambda x: x["last_time"], reverse=True)

    def _cleanup_old_operations(self) -> None:
        """Remove old operation records."""
        current_time = time.time()
        cutoff_time = current_time - 86400  # 24 hours

        for key in list(self._operations.keys()):
            self._operations[key] = [
                ts for ts in self._operations[key] if ts > cutoff_time
            ]

            # Remove empty entries
            if not self._operations[key]:
                del self._operations[key]

    def clear(self) -> None:
        """Clear all operation history."""
        with self._lock:
            self._operations.clear()


# Global operation tracker instance
_operation_tracker = ContainerOperationTracker()


def record_container_operation(container_id: str, operation: str) -> None:
    """Record a container operation for monitoring."""
    _operation_tracker.record_operation(container_id, operation)


def get_container_operation_history(
    container_id: str, since_seconds: float = 3600
) -> list[dict[str, Any]]:
    """Get recent operation history for a container."""
    return _operation_tracker.get_recent_operations(container_id, since_seconds)
