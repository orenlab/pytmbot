#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FutureTimeoutError,
)
from datetime import datetime
from typing import Dict, List, Optional, Final, Any
from functools import lru_cache
import time
from threading import RLock

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.adapters.docker.utils import (
    get_container_safely,
    build_container_context,
    with_operation_logging,
)
from pytmbot.exceptions import (
    ContainerNotFoundError,
)
from pytmbot.logs import Logger
from pytmbot.utils import set_naturaltime, sanitize_exception

logger = Logger()

# Module-level constants
MAX_WORKERS: Final[int] = 8  # Optimal for I/O bound operations
OPERATION_TIMEOUT: Final[float] = 30.0
CACHE_TTL: Final[int] = 60  # Cache TTL in seconds
MAX_LOG_TAIL: Final[int] = 100  # Maximum log lines to fetch


class ContainerInfoCache:
    """Thread-safe cache for container information with TTL."""

    def __init__(self, ttl: int = CACHE_TTL):
        self._cache: Dict[str, tuple[Dict, float]] = {}
        self._lock = RLock()
        self._ttl = ttl

    def get(self, key: str) -> Optional[Dict]:
        """Get cached value if not expired."""
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self._ttl:
                    return value
                else:
                    # Remove expired entry
                    del self._cache[key]
        return None

    def set(self, key: str, value: Dict) -> None:
        """Set cached value with current timestamp."""
        with self._lock:
            self._cache[key] = (value, time.time())

            # Cleanup expired entries periodically
            if len(self._cache) > 100:  # Arbitrary cleanup threshold
                current_time = time.time()
                expired_keys = [
                    k
                    for k, (_, ts) in self._cache.items()
                    if current_time - ts >= self._ttl
                ]
                for k in expired_keys:
                    del self._cache[k]

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)

    @property
    def ttl(self):
        return self._ttl


# Global cache instance
_container_cache = ContainerInfoCache()


@with_operation_logging("fetch_containers_list")
def __fetch_containers_list() -> List[str]:
    """
    Retrieves a list of all containers and returns their short IDs.

    Returns:
        List[str]: A list of short IDs of all containers.

    Raises:
        DockerConnectionError: If there is an error connecting to Docker.
    """
    context = {"action": "fetch_containers_list"}

    # Check cache first
    cached_result = _container_cache.get("containers_list")
    if cached_result is not None:
        logger.debug("Using cached container list", **context)
        return cached_result["container_ids"]

    try:
        with DockerAdapter() as adapter:
            start_time = time.time()
            container_list = adapter.containers.list(all=True)
            execution_time = time.time() - start_time

            container_ids = [container.short_id for container in container_list]

            # Cache the result
            cache_data = {
                "container_ids": container_ids,
                "count": len(container_ids),
                "execution_time": execution_time,
            }
            _container_cache.set("containers_list", cache_data)

            logger.info(
                "Container list fetched",
                container_count=len(container_ids),
                execution_time=f"{execution_time:.3f}s",
                **context,
            )

            return container_ids

    except Exception as e:
        logger.error(
            "Failed to fetch container list", error=sanitize_exception(e), **context
        )
        raise


@with_operation_logging("aggregate_container_details")
def __aggregate_container_details(container_id: str) -> Dict[str, str]:
    """
    Aggregates details of a Docker container into a dictionary with enhanced error handling.

    Args:
        container_id: The ID of the container.

    Returns:
        Dict containing container details.

    Raises:
        ContainerNotFoundError: If container is not found.
        Exception: For other container access errors.
    """
    context = build_container_context(
        container_id=container_id,
        action="container_details_aggregation",
    )

    # Check cache first
    cached_details = _container_cache.get(f"details_{container_id}")
    if cached_details is not None:
        logger.debug("Using cached container details", **context)
        return cached_details

    try:
        container_details = get_container_safely(container_id)
        attrs = container_details.attrs

        # Safely parse created timestamp
        created_str = attrs.get("Created", "")
        try:
            if created_str:
                created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            else:
                created_at = None
        except (ValueError, AttributeError) as e:
            logger.warning(
                "Failed to parse container creation time",
                created_str=created_str,
                error=str(e),
                **context,
            )
            created_at = None

        # Safely get container state info
        state_info = attrs.get("State", {})
        started_at_str = state_info.get("StartedAt", "")

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
                    "Failed to parse container start time",
                    started_at_str=started_at_str,
                    error=str(e),
                    **context,
                )

        # Get image information safely
        config = attrs.get("Config", {})
        image_name = config.get("Image", "N/A")

        # Extract container name (remove leading slash)
        container_name = attrs.get("Name", "").lstrip("/")
        if not container_name:
            container_name = container_id[:12]  # Fallback to short ID

        details = {
            "id": container_id,
            "name": container_name.title(),
            "image": image_name,
            "created": (
                created_at.strftime("%Y-%m-%d, %H:%M:%S") if created_at else "unknown"
            ),
            "run_at": run_at_display,
            "status": state_info.get("Status", "N/A"),
            "health": state_info.get("Health", {}).get("Status", "N/A"),
            "exit_code": state_info.get("ExitCode"),
            "restart_count": attrs.get("RestartCount", 0),
        }

        # Cache the details
        _container_cache.set(f"details_{container_id}", details)

        logger.debug(
            "Container details aggregated",
            status=details["status"],
            health=details.get("health", "N/A"),
            **context,
        )
        return details

    except ContainerNotFoundError:
        logger.warning("Container not found during details aggregation", **context)
        raise

    except Exception as e:
        logger.error(
            "Container details aggregation failed",
            error=sanitize_exception(e),
            error_type=type(e).__name__,
            **context,
        )
        raise


@with_operation_logging("retrieve_containers_stats")
def retrieve_containers_stats() -> List[Dict[str, str]]:
    """
    Retrieves and returns details of Docker containers using optimized parallel processing.

    Returns:
        List of container details dictionaries.

    Raises:
        Exception: If container list fetching fails.
    """
    context = {"action": "containers_stats_retrieval"}
    start_time = time.time()

    try:
        containers_id = __fetch_containers_list()
        if not containers_id:
            logger.info("No containers found", **context)
            return []

        logger.info(
            "Starting optimized parallel container stats retrieval",
            containers_count=len(containers_id),
            max_workers=MAX_WORKERS,
            **context,
        )

        container_details = []
        failed_containers = []
        timeouts = []

        # Use ThreadPoolExecutor with optimized settings
        with ThreadPoolExecutor(
            max_workers=min(MAX_WORKERS, len(containers_id)),
            thread_name_prefix="container_stats",
        ) as executor:
            # Submit all tasks
            future_to_id = {
                executor.submit(__aggregate_container_details, cid): cid
                for cid in containers_id
            }

            # Process completed futures with timeout
            try:
                for future in as_completed(future_to_id, timeout=OPERATION_TIMEOUT):
                    container_id = future_to_id[future]
                    try:
                        details = future.result(timeout=5.0)  # Per-container timeout
                        container_details.append(details)

                    except FutureTimeoutError:
                        timeouts.append(container_id)
                        logger.warning(
                            "Container processing timeout",
                            container_id=container_id,
                            timeout=5.0,
                            **context,
                        )

                    except ContainerNotFoundError:
                        failed_containers.append(container_id)
                        logger.debug(
                            "Container not found during parallel processing",
                            container_id=container_id,
                            **context,
                        )

                    except Exception as e:
                        failed_containers.append(container_id)
                        logger.error(
                            "Failed to process container in parallel execution",
                            container_id=container_id,
                            error=sanitize_exception(e),
                            error_type=type(e).__name__,
                            **context,
                        )

            except FutureTimeoutError:
                logger.warning(
                    "Overall operation timeout reached",
                    timeout=OPERATION_TIMEOUT,
                    **context,
                )
                # Cancel remaining futures
                for future in future_to_id:
                    future.cancel()

        execution_time = time.time() - start_time

        # Sort results by container name for consistent ordering
        container_details.sort(key=lambda x: x.get("name", "").lower())

        # Log comprehensive summary
        logger.info(
            "Container stats retrieval completed",
            successful_count=len(container_details),
            failed_count=len(failed_containers),
            timeout_count=len(timeouts),
            total_containers=len(containers_id),
            execution_time=f"{execution_time:.2f}s",
            **context,
        )

        if failed_containers:
            logger.warning(
                "Some containers failed to process",
                failed_containers=failed_containers[:10],  # Limit log size
                failed_count=len(failed_containers),
                **context,
            )

        if timeouts:
            logger.warning(
                "Some containers timed out",
                timeout_containers=timeouts[:10],  # Limit log size
                timeout_count=len(timeouts),
                **context,
            )

        return container_details

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "Container stats retrieval failed",
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
        container = get_container_safely(container_id)

        # Fetch logs with enhanced options
        logs = container.logs(
            tail=tail_lines,
            stdout=True,
            stderr=True,
            timestamps=include_timestamps,
            follow=False,  # Never follow in sync context
            since=None,  # Could be parameterized in future
        )

        # Decode logs with error handling
        try:
            log_content = logs.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            # Fallback for binary logs
            log_content = str(logs)

        # Truncate if too large (safety measure)
        max_log_size = 10000  # 10KB limit
        if len(log_content) > max_log_size:
            log_content = log_content[-max_log_size:]
            log_content = (
                f"[LOG TRUNCATED - showing last {max_log_size} chars]\n" + log_content
            )

        execution_time = time.time() - start_time

        logger.debug(
            "Container logs fetched",
            log_size=len(log_content),
            actual_lines=len(log_content.splitlines()),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )

        return log_content

    except ContainerNotFoundError:
        logger.warning("Container not found for log fetch", **context)
        raise

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "Failed to fetch container logs",
            error=sanitize_exception(e),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise


@lru_cache(maxsize=1)
@with_operation_logging("fetch_docker_counters")
def fetch_docker_counters() -> Dict[str, int]:
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
        with DockerAdapter() as adapter:
            # Use list comprehensions for better performance
            images_count = len(
                adapter.images.list(all=False)
            )  # Only non-dangling images
            containers_count = len(adapter.containers.list(all=True))

            # Additional useful counts
            running_containers = len(adapter.containers.list(all=False))  # Only running

            counters = {
                "images_count": images_count,
                "containers_count": containers_count,
                "running_containers": running_containers,
                "stopped_containers": containers_count - running_containers,
            }

            execution_time = time.time() - start_time

            logger.info(
                "Docker counters fetched",
                execution_time=f"{execution_time:.3f}s",
                **counters,
                **context,
            )

            return counters

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "Failed to fetch Docker counters",
            error=sanitize_exception(e),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise


@with_operation_logging("fetch_full_container_details")
def fetch_full_container_details(container_id: str) -> Optional[Dict]:
    """
    Retrieves and returns the full attributes of a Docker container with caching.

    Args:
        container_id (str): The ID of the container.

    Returns:
        dict: A dictionary containing the full attributes of the Docker container,
              or None if container not found.

    Raises:
        Exception: For unexpected errors during container retrieval.
    """
    context = build_container_context(
        container_id=container_id,
        action="full_container_details",
    )

    # Check cache first
    cache_key = f"full_details_{container_id}"
    cached_details = _container_cache.get(cache_key)
    if cached_details is not None:
        logger.debug("Using cached full container details", **context)
        return cached_details

    start_time = time.time()

    try:
        container = get_container_safely(container_id)

        # Get full container attributes
        full_details = {
            "id": container.id,
            "short_id": container.short_id,
            "name": container.name,
            "status": container.status,
            "attrs": container.attrs,
            "image": {
                "id": container.image.id,
                "tags": container.image.tags,
                "short_id": container.image.short_id,
            }
            if container.image
            else None,
            "labels": container.labels,
            "ports": getattr(container, "ports", {}),
        }

        # Cache the full details (shorter TTL for full details due to size)
        _container_cache.set(cache_key, full_details)

        execution_time = time.time() - start_time

        logger.debug(
            "Full container details retrieved",
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        return full_details

    except ContainerNotFoundError:
        logger.debug("Container not found for full details", **context)
        return None

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "Failed to fetch full container details",
            error=sanitize_exception(e),
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        # Return empty dict for backward compatibility, but log the error
        return {}


def clear_container_cache() -> None:
    """Clear the container information cache."""
    _container_cache.clear()
    # Also clear the LRU cache
    fetch_docker_counters.cache_clear()
    logger.info("Container cache cleared")


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics for monitoring."""
    return {
        "cache_size": _container_cache.size(),
        "cache_ttl": _container_cache.ttl,
        "lru_cache_info": fetch_docker_counters.cache_info()._asdict(),
    }
