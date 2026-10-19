#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from collections.abc import Iterable
from threading import RLock
from typing import Final

from docker.client import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.utils import (
    build_container_context,
    docker_unavailable_as_connection_error,
    get_container_safely,
    parse_docker_timestamp,
    validate_container_reference,
    with_operation_logging,
)
from pytmbot.exceptions import (
    ContainerLogsUnavailableError,
    ContainerNotFoundError,
    DockerOperationException,
    ErrorContext,
)
from pytmbot.logs import Logger
from pytmbot.utils import as_object_dict, sanitize_exception, set_naturaltime

logger = Logger()

# Module-level constants
MAX_LOG_TAIL: Final[int] = 100  # Maximum log lines to fetch
DOCKER_COUNTERS_CACHE_TTL: Final[float] = 30.0
_MAX_SUMMARY_ITEMS: Final[int] = 5
_COUNTED_STATES: Final[tuple[str, ...]] = ("running", "paused", "restarting", "created")
_LOGS_DRIVER_NOT_READABLE_MARKER: Final[str] = (
    "configured logging driver does not support reading"
)

_docker_counters_cache: dict[str, int] | None = None
_docker_counters_cached_at: float = 0.0
_docker_counters_lock = RLock()


def _is_logs_driver_not_readable_error(error: APIError) -> bool:
    details = f"{error} {getattr(error, 'explanation', '')}".lower()
    return _LOGS_DRIVER_NOT_READABLE_MARKER in details


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


def _container_short_id(container: object) -> str:
    return (
        str(getattr(container, "short_id", "") or "")
        or str(getattr(container, "id", "") or "")[:12]
    )


def _format_created(attrs: dict[str, object]) -> str:
    created_at = parse_docker_timestamp(attrs.get("Created"))
    return created_at.strftime("%Y-%m-%d, %H:%M:%S") if created_at else "unknown"


def _format_run_at(state_info: dict[str, object]) -> str:
    started_at = parse_docker_timestamp(state_info.get("StartedAt"))
    return set_naturaltime(started_at) if started_at else "N/A"


def _resolve_status(state_info: dict[str, object], container: object) -> str:
    status_value = state_info.get("Status")
    if isinstance(status_value, str) and status_value:
        return status_value
    return str(getattr(container, "status", "N/A") or "N/A")


def _summarize_networks(attrs: dict[str, object]) -> str:
    network_settings = as_object_dict(attrs.get("NetworkSettings"))
    names = sorted(
        str(name) for name in as_object_dict(network_settings.get("Networks"))
    )
    return ", ".join(names[:_MAX_SUMMARY_ITEMS]) or "N/A"


def _describe_port(container_port: str, bindings: object) -> str:
    if not isinstance(bindings, list):
        return container_port
    hosts = [
        f"{binding.get('HostIp') or '0.0.0.0'}:{binding.get('HostPort')}"
        for binding in bindings
        if isinstance(binding, dict) and binding.get("HostPort")
    ]
    return f"{'/'.join(hosts)}->{container_port}" if hosts else container_port


def _summarize_ports(attrs: dict[str, object]) -> str:
    network_settings = as_object_dict(attrs.get("NetworkSettings"))
    ports = as_object_dict(network_settings.get("Ports"))
    rendered = sorted(
        _describe_port(str(container_port), bindings)
        for container_port, bindings in ports.items()
    )
    return ", ".join(rendered[:_MAX_SUMMARY_ITEMS]) or "N/A"


def _build_container_summary(container: object) -> dict[str, str]:
    """Build the list/overview row for a container from its inspect attrs."""
    attrs = as_object_dict(getattr(container, "attrs", {}))
    state_info = as_object_dict(attrs.get("State"))
    config = as_object_dict(attrs.get("Config"))
    health = as_object_dict(state_info.get("Health"))
    container_id = _container_short_id(container)
    container_name = str(attrs.get("Name") or "").lstrip("/") or container_id[:12]
    image_name = config.get("Image")

    return {
        "id": container_id,
        "name": container_name,
        "image": image_name if isinstance(image_name, str) else "N/A",
        "created": _format_created(attrs),
        "run_at": _format_run_at(state_info),
        "status": _resolve_status(state_info, container),
        "health": str(health.get("Status", "N/A")),
        "exit_code": str(state_info.get("ExitCode", "N/A")),
        "restart_count": str(attrs.get("RestartCount", 0)),
        "networks": _summarize_networks(attrs),
        "ports": _summarize_ports(attrs),
    }


@with_operation_logging("aggregate_container_details")
def __aggregate_container_details(
    container_ref: str | Container,
    docker_client: DockerClient | None = None,
) -> dict[str, str]:
    """
    Aggregate the details of a container for list/overview rendering.

    Details are always built from fresh inspect data (no cross-call cache), so
    the status shown right after a start/stop/restart is current.

    Raises:
        ContainerNotFoundError: If a referenced container is not found.
    """
    if isinstance(container_ref, Container):
        container: object = container_ref
    else:
        container = get_container_safely(container_ref, docker_client=docker_client)

    details = _build_container_summary(container)
    logger.debug(
        "docker.containers.container.details.debug",
        status=details["status"],
        health=details["health"],
        **build_container_context(
            container_id=details["id"] or "unknown",
            action="container_details_aggregation",
        ),
    )
    return details


def _collect_container_rows(
    container_objects: list[Container],
    adapter: DockerClient,
    context: dict[str, str],
) -> tuple[list[dict[str, str]], list[str]]:
    container_details: list[dict[str, str]] = []
    failed_containers: list[str] = []
    for container in container_objects:
        container_id = _container_short_id(container) or "unknown"
        try:
            container_details.append(__aggregate_container_details(container, adapter))
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
    return container_details, failed_containers


@with_operation_logging("retrieve_containers_stats")
def retrieve_containers_stats() -> list[dict[str, str]]:
    """
    Retrieve details of all Docker containers with a single list roundtrip.

    Containers removed between the list call and their inspect are skipped
    (``ignore_removed``) instead of failing the whole listing.

    Raises:
        DockerConnectionError: If Docker is unavailable.
        Exception: If container list fetching fails.
    """
    context = {"action": "containers_stats_retrieval"}
    start_time = time.time()

    try:
        with (
            docker_unavailable_as_connection_error("container listing"),
            docker_client_context() as adapter,
        ):
            container_objects = adapter.containers.list(all=True, ignore_removed=True)
            if not container_objects:
                logger.info("docker.containers.no.found.info", **context)
                return []

            logger.info(
                "docker.containers.single.list.start",
                containers_count=len(container_objects),
                **context,
            )
            container_details, failed_containers = _collect_container_rows(
                container_objects, adapter, context
            )
    except Exception as e:
        logger.error(
            "docker.containers.container.stats.fail",
            error=sanitize_exception(e),
            execution_time=f"{time.time() - start_time:.2f}s",
            **context,
        )
        raise

    container_details.sort(key=lambda row: row.get("name", "").lower())
    logger.info(
        "docker.containers.container.stats.ok",
        successful_count=len(container_details),
        failed_count=len(failed_containers),
        total_containers=len(container_objects),
        execution_time=f"{time.time() - start_time:.2f}s",
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


def _decode_logs(logs: object) -> str:
    if isinstance(logs, (bytes, bytearray)):
        log_content = logs.decode("utf-8", errors="replace")
    else:
        log_content = str(logs)

    max_log_size = 10000  # 10KB limit
    if len(log_content) > max_log_size:
        log_content = (
            f"[LOG TRUNCATED - showing last {max_log_size} chars]\n"
            + log_content[-max_log_size:]
        )
    return log_content


def _logs_unavailable_error(container_id: str) -> ContainerLogsUnavailableError:
    return ContainerLogsUnavailableError(
        ErrorContext(
            message=f"Container logs unavailable for: {container_id}",
            error_code="DOCKER_010",
            metadata={
                "container_id": container_id,
                "reason": "logging_driver_not_readable",
            },
        )
    )


@with_operation_logging("fetch_container_logs")
def fetch_container_logs(
    container_id: str, tail_lines: int = MAX_LOG_TAIL, include_timestamps: bool = True
) -> str | None:
    """
    Fetch the logs of a Docker container (exact name or short/full ID).

    Returns:
        Container logs as a string, or None if the container does not exist.

    Raises:
        ValueError: If tail_lines is invalid.
        InvalidContainerReferenceError: If the reference is invalid.
        ContainerLogsUnavailableError: If the logging driver cannot be read.
        DockerConnectionError: If Docker is unavailable.
    """
    if not isinstance(tail_lines, int) or tail_lines <= 0:
        raise ValueError("tail_lines must be a positive integer")

    reference = validate_container_reference(container_id)
    tail_lines = min(tail_lines, 1000)
    context = build_container_context(
        container_id=reference,
        action="container_logs_fetch",
        tail_lines=tail_lines,
        include_timestamps=include_timestamps,
    )
    start_time = time.time()

    try:
        with (
            docker_unavailable_as_connection_error("container logs fetch"),
            docker_client_context() as adapter,
        ):
            container = get_container_safely(reference, docker_client=adapter)
            logs = container.logs(
                tail=tail_lines,
                stdout=True,
                stderr=True,
                timestamps=include_timestamps,
                follow=False,  # Never follow in sync context
            )
    except ContainerNotFoundError:
        logger.warning("docker.containers.container.not.warn", **context)
        return None
    except NotFound:
        # The container disappeared between the lookup and the logs request.
        logger.warning("docker.containers.container.not.warn", **context)
        return None
    except APIError as error:
        if _is_logs_driver_not_readable_error(error):
            logger.info(
                "docker.containers.container.logs.unavailable.info",
                reason="logging_driver_not_readable",
                **context,
            )
            raise _logs_unavailable_error(reference) from error
        # e.g. 409 "can not get logs from container which is dead or marked
        # for removal": report it as an operation failure, not a crash.
        logger.warning(
            "docker.containers.container.logs.api.warn",
            status_code=getattr(error, "status_code", None),
            **context,
        )
        raise DockerOperationException(
            ErrorContext(
                message="Docker could not return the container logs",
                error_code="DOCKER_013",
                metadata={"container_id": reference},
            )
        ) from error
    except Exception as e:
        logger.error(
            "docker.containers.fetch.container.fail",
            error=sanitize_exception(e),
            execution_time=f"{time.time() - start_time:.3f}s",
            **context,
        )
        raise

    log_content = _decode_logs(logs)
    logger.debug(
        "docker.containers.container.logs.debug",
        log_size=len(log_content),
        actual_lines=len(log_content.splitlines()),
        execution_time=f"{time.time() - start_time:.3f}s",
        **context,
    )
    return log_content


def summarize_container_statuses(statuses: Iterable[str]) -> dict[str, int]:
    """
    Count containers per lifecycle bucket.

    ``stopped_containers`` counts only containers that are really stopped
    (exited/dead/removing); paused, restarting and created containers are
    reported separately.
    """
    counts = dict.fromkeys(_COUNTED_STATES, 0)
    total = 0
    for status in statuses:
        total += 1
        normalized = status.strip().lower()
        if normalized in counts:
            counts[normalized] += 1

    return {
        "containers_count": total,
        "running_containers": counts["running"],
        "paused_containers": counts["paused"],
        "restarting_containers": counts["restarting"],
        "created_containers": counts["created"],
        "stopped_containers": total - sum(counts.values()),
    }


@with_operation_logging("fetch_docker_counters")
def fetch_docker_counters(*, force_refresh: bool = False) -> dict[str, int]:
    """
    Fetch Docker image and container counts with caching.

    Uses a sparse container listing and the image summary list, so counting
    never inspects individual objects (no list/inspect race, two API calls).

    Raises:
        DockerConnectionError: If Docker is unavailable.
        Exception: If Docker operations fail.
    """
    context = {"action": "docker_counters_fetch"}
    start_time = time.time()

    if not force_refresh:
        cached_counters = _get_cached_docker_counters()
        if cached_counters is not None:
            logger.debug("docker.containers.counters.cache.hit.debug", **context)
            return cached_counters

    try:
        with (
            docker_unavailable_as_connection_error("docker counters fetch"),
            docker_client_context() as adapter,
        ):
            containers = adapter.containers.list(all=True, sparse=True)
            images_count = len(adapter.api.images(quiet=True))
    except Exception as e:
        logger.error(
            "docker.containers.fetch.counters.fail",
            error=sanitize_exception(e),
            execution_time=f"{time.time() - start_time:.3f}s",
            **context,
        )
        raise

    counters = {
        "images_count": images_count,
        **summarize_container_statuses(
            str(getattr(container, "status", "") or "") for container in containers
        ),
    }
    logger.info(
        "docker.containers.counters.fetch.info",
        execution_time=f"{time.time() - start_time:.3f}s",
        **counters,
        **context,
    )
    _store_docker_counters(counters)
    return counters


@with_operation_logging("fetch_full_container_details")
def fetch_full_container_details(container_id: str) -> Container | None:
    """
    Return the Docker Container object for an exact name or short/full ID.

    Returns:
        The Container, or None if it does not exist (or the reference resolved
        to a different container).

    Raises:
        InvalidContainerReferenceError: If the reference is invalid.
        DockerConnectionError: If Docker is unavailable (never reported as None).
        DockerOperationException: For other Docker API failures.
    """
    reference = validate_container_reference(container_id)
    context = build_container_context(
        container_id=reference,
        action="full_container_details",
    )
    start_time = time.time()

    try:
        with docker_client_context() as adapter:
            container = get_container_safely(reference, docker_client=adapter)
    except ContainerNotFoundError:
        logger.debug("docker.containers.container.not.debug", **context)
        return None

    logger.debug(
        "docker.containers.full.container.debug",
        execution_time=f"{time.time() - start_time:.3f}s",
        **context,
    )
    return container
