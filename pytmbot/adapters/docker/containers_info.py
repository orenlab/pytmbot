#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List

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


@with_operation_logging("fetch_containers_list")
def __fetch_containers_list() -> List[str]:
    """
    Retrieves a list of all running containers and returns their short IDs.

    Returns:
        List[str]: A list of short IDs of the running containers.

    Raises:
        DockerConnectionError: If there is an error connecting to Docker.
    """
    with DockerAdapter() as adapter:
        container_list = adapter.containers.list(all=True)
        return [container.short_id for container in container_list]


@with_operation_logging("aggregate_container_details")
def __aggregate_container_details(container_id: str) -> Dict[str, str]:
    """
    Aggregates details of a Docker container into a dictionary.

    Args:
        container_id: The ID of the container.

    Returns:
        Dict containing container details.
    """
    context = build_container_context(
        container_id=container_id,
        action="container_details_aggregation",
    )

    try:
        container_details = get_container_safely(container_id)
        attrs = container_details.attrs

        created_at = datetime.fromisoformat(attrs["Created"])

        details = {
            "id": container_id,
            "name": attrs["Name"].strip("/").title(),
            "image": attrs.get("Config", {}).get("Image", "N/A"),
            "created": created_at.strftime("%Y-%m-%d, %H:%M:%S"),
            "run_at": (
                set_naturaltime(
                    datetime.fromisoformat(attrs["State"].get("StartedAt", ""))
                )
                if attrs["State"].get("StartedAt")
                else "N/A"
            ),
            "status": attrs.get("State", {}).get("Status", "N/A"),
        }

        logger.debug(
            "Container details aggregated", status=details["status"], **context
        )
        return details

    except Exception as e:
        logger.error(
            "Container details aggregation failed",
            error=sanitize_exception(e),
            **context,
        )
        raise


@with_operation_logging("retrieve_containers_stats")
def retrieve_containers_stats() -> List[Dict[str, str]]:
    """
    Retrieves and returns details of Docker containers using parallel processing.

    Returns:
        List of container details dictionaries.
    """
    context = {"action": "containers_stats_retrieval"}

    containers_id = __fetch_containers_list()
    if not containers_id:
        logger.debug("No containers found", **context)
        return []

    logger.info(
        "Starting parallel container stats retrieval",
        containers_count=len(containers_id),
        **context,
    )

    container_details = []
    failed_containers = []

    with ThreadPoolExecutor() as executor:
        future_to_id = {
            executor.submit(__aggregate_container_details, cid): cid
            for cid in containers_id
        }

        for future in as_completed(future_to_id):
            container_id = future_to_id[future]
            try:
                details = future.result()
                container_details.append(details)

            except Exception as e:
                failed_containers.append(container_id)
                logger.error(
                    "Failed to process container in parallel execution",
                    container_id=container_id,
                    error=sanitize_exception(e),
                    **context,
                )

    # Log summary
    logger.info(
        "Container stats retrieval completed",
        successful_count=len(container_details),
        failed_count=len(failed_containers),
        **context,
    )

    if failed_containers:
        logger.warning(
            "Some containers failed to process",
            failed_containers=failed_containers,
            **context,
        )

    return container_details


@with_operation_logging("fetch_container_logs")
def fetch_container_logs(container_id: str) -> str:
    """
    Fetches and returns the logs of a Docker container.

    Args:
        container_id: The ID of the container.

    Returns:
        Container logs as a string.

    Raises:
        ContainerNotFoundError: If the container cannot be found.
    """
    context = build_container_context(
        container_id=container_id,
        action="container_logs_fetch",
    )

    try:
        container = get_container_safely(container_id)
        logs = container.logs(tail=50, stdout=True, stderr=True, timestamps=True)
        log_content = logs.decode("utf-8", errors="replace")[-3800:]

        logger.debug("Container logs fetched", log_size=len(log_content), **context)

        return log_content

    except Exception as e:
        logger.error(
            "Failed to fetch container logs", error=sanitize_exception(e), **context
        )
        raise


@with_operation_logging("fetch_docker_counters")
def fetch_docker_counters() -> Dict[str, int]:
    """
    Fetches Docker image and container counts.

    Returns:
        Dict with image and container counts.
    """
    context = {"action": "docker_counters_fetch"}

    with DockerAdapter() as adapter:
        counters = {
            "images_count": len(adapter.images.list()),
            "containers_count": len(adapter.containers.list(all=True)),
        }

        logger.debug("Docker counters fetched", **counters, **context)

        return counters


@with_operation_logging("fetch_full_container_details")
def fetch_full_container_details(container_id: str):
    """
    Retrieves and returns the full attributes of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        dict: A dictionary containing the full attributes of the Docker container.
    """
    context = build_container_context(
        container_id=container_id,
        action="full_container_details",
    )

    try:
        container = get_container_safely(container_id)
        logger.debug("Full container details retrieved", **context)
        return container

    except ContainerNotFoundError:
        logger.debug("Container not found for full details", **context)
        return {}

    except Exception as e:
        logger.error(
            "Failed to fetch full container details",
            error=sanitize_exception(e),
            **context,
        )
        return {}
