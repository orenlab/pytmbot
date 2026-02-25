#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from datetime import datetime
from threading import RLock
from typing import Any, Final

from docker.models.containers import Container

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.utils import (
    build_container_context,
    get_container_safely,
    with_operation_logging,
)
from pytmbot.exceptions import (
    ContainerNotFoundError,
)
from pytmbot.logs import Logger
from pytmbot.utils import sanitize_exception, set_naturaltime

logger = Logger()

# Module-level constants
CACHE_TTL: Final[int] = 60  # Cache TTL in seconds
MAX_LOG_TAIL: Final[int] = 100  # Maximum log lines to fetch
DOCKER_COUNTERS_CACHE_TTL: Final[float] = 30.0


class ContainerInfoCache:
    """Thread-safe cache for container information with TTL."""

    __slots__ = (
        "_cache",
        "_lock",
        "_ttl",
        "_max_entries",
        "_cleanup_interval_seconds",
        "_last_cleanup_timestamp",
    )

    def __init__(self, ttl: int = CACHE_TTL):
        self._cache: dict[str, tuple[dict, float]] = {}
        self._lock = RLock()
        self._ttl = ttl
        self._max_entries = 100
        self._cleanup_interval_seconds = 30.0
        self._last_cleanup_timestamp = 0.0

    def _cleanup_expired_entries(
        self, current_time: float, *, force: bool = False
    ) -> None:
        """Cleanup expired entries with bounded cadence."""
        should_cleanup = force or (
            current_time - self._last_cleanup_timestamp
            >= self._cleanup_interval_seconds
        )
        if not should_cleanup:
            return

        self._last_cleanup_timestamp = current_time
        expired_keys = [
            key
            for key, (_value, timestamp) in self._cache.items()
            if current_time - timestamp >= self._ttl
        ]
        for key in expired_keys:
            self._cache.pop(key, None)

    def get(self, key: str) -> dict | None:
        """Get cached value if not expired."""
        with self._lock:
            current_time = time.time()
            self._cleanup_expired_entries(current_time)

            if key in self._cache:
                value, timestamp = self._cache[key]
                if current_time - timestamp < self._ttl:
                    return value
                else:
                    # Remove expired entry
                    del self._cache[key]
        return None

    def set(self, key: str, value: dict) -> None:
        """Set cached value with current timestamp."""
        with self._lock:
            current_time = time.time()
            self._cache[key] = (value, current_time)
            self._cleanup_expired_entries(
                current_time, force=len(self._cache) > self._max_entries
            )

            if len(self._cache) > self._max_entries:
                oldest_key = min(
                    self._cache, key=lambda cache_key: self._cache[cache_key][1]
                )
                self._cache.pop(oldest_key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)


# Global cache instance
_container_cache = ContainerInfoCache()
_docker_counters_cache: dict[str, int] | None = None
_docker_counters_cached_at: float = 0.0
_docker_counters_lock = RLock()


def _get_cached_docker_counters() -> dict[str, int] | None:
    """Return cached docker counters if TTL has not expired."""
    global _docker_counters_cache, _docker_counters_cached_at

    with _docker_counters_lock:
        if _docker_counters_cache is None:
            return None

        if time.monotonic() - _docker_counters_cached_at >= DOCKER_COUNTERS_CACHE_TTL:
            _docker_counters_cache = None
            _docker_counters_cached_at = 0.0
            return None

        return dict(_docker_counters_cache)


def _store_docker_counters(counters: dict[str, int]) -> None:
    """Store docker counters in bounded TTL cache."""
    global _docker_counters_cache, _docker_counters_cached_at
    with _docker_counters_lock:
        _docker_counters_cache = dict(counters)
        _docker_counters_cached_at = time.monotonic()


def _clear_docker_counters_cache() -> None:
    """Clear docker counters cache."""
    global _docker_counters_cache, _docker_counters_cached_at
    with _docker_counters_lock:
        _docker_counters_cache = None
        _docker_counters_cached_at = 0.0


@with_operation_logging("aggregate_container_details")
def __aggregate_container_details(
    container_ref: str | Container,
    docker_client: Any | None = None,
) -> dict[str, str]:
    """
    Aggregates details of a Docker container into a dictionary with enhanced error handling.

    Args:
        container_ref: Container ID or container object.

    Returns:
        Dict containing container details for list/overview rendering.

    Raises:
        ContainerNotFoundError: If container is not found.
        Exception: For other container access errors.
    """
    try:
        if isinstance(container_ref, Container):
            container_details = container_ref
            container_id = (
                getattr(container_details, "short_id", "")
                or str(getattr(container_details, "id", ""))[:12]
            )
        else:
            container_id = container_ref
            container_details = get_container_safely(
                container_id,
                docker_client=docker_client,
            )

        context = build_container_context(
            container_id=container_id,
            action="container_details_aggregation",
        )

        # Check cache first
        cached_details = _container_cache.get(f"details_{container_id}")
        if cached_details is not None:
            logger.debug("docker.containers.using.cached.debug", **context)
            return cached_details

        attrs_raw = getattr(container_details, "attrs", {})
        attrs = attrs_raw if isinstance(attrs_raw, dict) else {}

        # Safely parse created timestamp
        created_str_value = attrs.get("Created", "")
        created_str = created_str_value if isinstance(created_str_value, str) else ""
        try:
            if created_str:
                created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            else:
                created_at = None
        except (ValueError, AttributeError) as e:
            logger.warning(
                "docker.containers.parse.container.fail",
                created_str=created_str,
                error=str(e),
                **context,
            )
            created_at = None

        # Safely get container state info
        state_raw = attrs.get("State", {})
        state_info = state_raw if isinstance(state_raw, dict) else {}
        started_at_value = state_info.get("StartedAt", "")
        started_at_str = started_at_value if isinstance(started_at_value, str) else ""

        # Parse start time
        run_at_display = "N/A"
        if started_at_str and started_at_str != "0001-01-01T00:00:00Z":
            try:
                started_at = datetime.fromisoformat(
                    started_at_str.replace("Z", "+00:00")
                )
                run_at_display = set_naturaltime(started_at)
            except (ValueError, AttributeError) as e:
                logger.debug(
                    "docker.containers.parse.container.fail",
                    started_at_str=started_at_str,
                    error=str(e),
                    **context,
                )

        # Get image information safely
        config_raw = attrs.get("Config", {})
        config = config_raw if isinstance(config_raw, dict) else {}
        image_name_value = config.get("Image", "N/A")
        image_name = image_name_value if isinstance(image_name_value, str) else "N/A"

        # Extract container name (remove leading slash)
        container_name_raw = attrs.get("Name", "")
        container_name = (
            container_name_raw.lstrip("/")
            if isinstance(container_name_raw, str)
            else ""
        )
        if not container_name:
            container_name = container_id[:12]  # Fallback to short ID

        health_raw = state_info.get("Health", {})
        health = (
            health_raw.get("Status", "N/A") if isinstance(health_raw, dict) else "N/A"
        )
        status_value = state_info.get("Status")
        status = (
            status_value
            if isinstance(status_value, str) and status_value
            else getattr(container_details, "status", "N/A")
        )

        details = {
            "id": container_id,
            "name": container_name.title(),
            "image": image_name,
            "created": (
                created_at.strftime("%Y-%m-%d, %H:%M:%S") if created_at else "unknown"
            ),
            "run_at": run_at_display,
            "status": status,
            "health": health,
            "exit_code": state_info.get("ExitCode"),
            "restart_count": attrs.get("RestartCount", 0),
        }

        # Cache the details
        _container_cache.set(f"details_{container_id}", details)

        logger.debug(
            "docker.containers.container.details.debug",
            status=details["status"],
            health=details.get("health", "N/A"),
            **context,
        )
        return details

    except ContainerNotFoundError:
        context = build_container_context(
            container_id=str(container_ref),
            action="container_details_aggregation",
        )
        logger.warning("docker.containers.container.not.warn", **context)
        raise

    except Exception as e:
        context = build_container_context(
            container_id=str(container_ref),
            action="container_details_aggregation",
        )
        logger.error(
            "docker.containers.container.details.fail",
            error=sanitize_exception(e),
            error_type=type(e).__name__,
            **context,
        )
        raise


@with_operation_logging("retrieve_containers_stats")
def retrieve_containers_stats() -> list[dict[str, str]]:
    """
    Retrieve and return details of Docker containers with a single list roundtrip.

    Returns:
        List of container details dictionaries.

    Raises:
        Exception: If container list fetching fails.
    """
    context = {"action": "containers_stats_retrieval"}
    start_time = time.time()

    try:
        with docker_client_context() as adapter:
            container_objects = adapter.containers.list(all=True)
            if not container_objects:
                logger.info("docker.containers.no.found.info", **context)
                return []

            logger.info(
                "docker.containers.single.list.start",
                containers_count=len(container_objects),
                **context,
            )

            container_details: list[dict[str, str]] = []
            failed_containers: list[str] = []
            for container in container_objects:
                container_id = (
                    getattr(container, "short_id", "")
                    or str(getattr(container, "id", ""))[:12]
                    or "unknown"
                )
                try:
                    details = __aggregate_container_details(container, adapter)
                    container_details.append(details)
                except ContainerNotFoundError:
                    failed_containers.append(container_id)
                    logger.debug(
                        "docker.containers.container.not.debug",
                        container_id=container_id,
                        **context,
                    )
                except Exception as e:
                    failed_containers.append(container_id)
                    logger.error(
                        "docker.containers.container.details.fail",
                        container_id=container_id,
                        error=sanitize_exception(e),
                        error_type=type(e).__name__,
                        **context,
                    )

        execution_time = time.time() - start_time

        # Sort results by container name for consistent ordering
        if len(container_details) > 1:
            container_details.sort(key=lambda x: x.get("name", "").lower())

        # Log comprehensive summary
        logger.info(
            "docker.containers.container.stats.ok",
            successful_count=len(container_details),
            failed_count=len(failed_containers),
            timeout_count=0,
            total_containers=len(container_objects),
            execution_time=f"{execution_time:.2f}s",
            **context,
        )

        if failed_containers:
            logger.warning(
                "docker.containers.some.fail",
                failed_containers=failed_containers[:10],  # Limit log size
                failed_count=len(failed_containers),
                **context,
            )

        return container_details

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "docker.containers.container.stats.fail",
            error=sanitize_exception(e),
            execution_time=f"{execution_time:.2f}s",
            **context,
        )
        raise


@with_operation_logging("fetch_container_logs")
def fetch_container_logs(
    container_id: str, tail_lines: int = MAX_LOG_TAIL, include_timestamps: bool = True
) -> str:
    """
    Fetches and returns the logs of a Docker container with enhanced options.

    Args:
        container_id: The ID of the container.
        tail_lines: Number of log lines to fetch (default: 100, max: 1000).
        include_timestamps: Whether to include timestamps in logs.

    Returns:
        Container logs as a string.

    Raises:
        ContainerNotFoundError: If the container cannot be found.
        ValueError: If tail_lines is invalid.
    """
    # Validate input parameters
    if not isinstance(tail_lines, int) or tail_lines <= 0:
        raise ValueError("tail_lines must be a positive integer")

    # Limit maximum log lines for performance and memory reasons
    tail_lines = min(tail_lines, 1000)

    context = build_container_context(
        container_id=container_id,
        action="container_logs_fetch",
        tail_lines=tail_lines,
        include_timestamps=include_timestamps,
    )

    start_time = time.time()

    try:
        with docker_client_context() as adapter:
            container = get_container_safely(container_id, docker_client=adapter)

            # Fetch logs with enhanced options
            logs = container.logs(
                tail=tail_lines,
                stdout=True,
                stderr=True,
                timestamps=include_timestamps,
                follow=False,  # Never follow in sync context
                since=None,  # Could be parameterized in future
            )

        # Decode logs with strict type narrowing
        if isinstance(logs, (bytes, bytearray)):
            log_content = logs.decode("utf-8", errors="replace")
        else:
            log_content = str(logs)

        # Truncate if too large (safety measure)
        max_log_size = 10000  # 10KB limit
        if len(log_content) > max_log_size:
            log_content = (
                f"[LOG TRUNCATED - showing last {max_log_size} chars]\n"
                + log_content[-max_log_size:]
            )

        execution_time = time.time() - start_time

        logger.debug(
            "docker.containers.container.logs.debug",
            log_size=len(log_content),
            actual_lines=len(log_content.splitlines()),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )

        return log_content

    except ContainerNotFoundError:
        logger.warning("docker.containers.container.not.warn", **context)
        raise

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "docker.containers.fetch.container.fail",
            error=sanitize_exception(e),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise


@with_operation_logging("fetch_docker_counters")
def fetch_docker_counters(*, force_refresh: bool = False) -> dict[str, int]:
    """
    Fetches Docker image and container counts with caching.

    Returns:
        Dict with image and container counts.

    Raises:
        Exception: If Docker operations fail.
    """
    context = {"action": "docker_counters_fetch"}
    start_time = time.time()

    try:
        if not force_refresh:
            cached_counters = _get_cached_docker_counters()
            if cached_counters is not None:
                logger.debug("docker.containers.counters.cache.hit.debug", **context)
                return cached_counters

        with docker_client_context() as adapter:
            # Use list comprehensions for better performance
            images_count = len(
                adapter.images.list(all=False)
            )  # Only non-dangling images
            containers = adapter.containers.list(all=True)
            containers_count = len(containers)
            running_containers = sum(
                1
                for container in containers
                if getattr(container, "status", "") == "running"
            )

            counters = {
                "images_count": images_count,
                "containers_count": containers_count,
                "running_containers": running_containers,
                "stopped_containers": containers_count - running_containers,
            }

            execution_time = time.time() - start_time

            logger.info(
                "docker.containers.counters.fetch.info",
                execution_time=f"{execution_time:.3f}s",
                **counters,
                **context,
            )

            _store_docker_counters(counters)
            return counters

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "docker.containers.fetch.counters.fail",
            error=sanitize_exception(e),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise


@with_operation_logging("fetch_full_container_details")
def fetch_full_container_details(container_id: str) -> Container | None:
    """
    Retrieves and returns the actual Docker Container object for handler compatibility.

    Args:
        container_id (str): The ID of the container.

    Returns:
        Container: The actual Docker Container object, or None if container not found.

    Raises:
        Exception: For unexpected errors during container retrieval.
    """
    context = build_container_context(
        container_id=container_id,
        action="full_container_details",
    )

    start_time = time.time()

    try:
        # Return the actual Container object for compatibility with handlers
        with docker_client_context() as adapter:
            container = get_container_safely(container_id, docker_client=adapter)

        execution_time = time.time() - start_time

        logger.debug(
            "docker.containers.full.container.debug",
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        return container

    except ContainerNotFoundError:
        logger.debug("docker.containers.container.not.debug", **context)
        return None

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "docker.containers.fetch.full.fail",
            error=sanitize_exception(e),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        # Return None for backward compatibility, but log the error
        return None


def clear_container_cache() -> None:
    """Clear the container information cache."""
    _container_cache.clear()
    _clear_docker_counters_cache()
    logger.info("docker.containers.container.cache.info")


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics for monitoring."""
    cached_counters = _get_cached_docker_counters()
    return {
        "cache_size": _container_cache.size(),
        "cache_ttl": _container_cache._ttl,
        "docker_counters_cached": cached_counters is not None,
        "docker_counters_ttl_seconds": DOCKER_COUNTERS_CACHE_TTL,
        "docker_counters_cache_size": len(cached_counters or {}),
    }
