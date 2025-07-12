#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
from typing import Dict, List, Optional

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
from pytmbot.utils import set_naturaltime, sanitize_exception

logger = Logger()


def with_operation_logging(operation_name: str):
    """
    Decorator for logging Docker operations with timing and context.

    Args:
        operation_name: Name of the Docker operation being performed
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            # Build base context
            context = {
                "action": f"docker_{operation_name}",
                "operation": operation_name,
                "start_time": datetime.now().isoformat(),
            }

            # Add function arguments context (sanitized)
            if args:
                context["args_count"] = len(args)
                # Add first argument if it's a string (usually container_id)
                if args and isinstance(args[0], str):
                    context["container_id"] = args[0]

            if kwargs:
                # Sanitize kwargs to avoid logging sensitive data
                safe_kwargs = {
                    k: v
                    for k, v in kwargs.items()
                    if not any(
                        sensitive in k.lower()
                        for sensitive in ["password", "token", "secret", "key"]
                    )
                }
                if safe_kwargs:
                    context["params"] = safe_kwargs

            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time

                # Update context with success metrics
                context.update(
                    {
                        "execution_time": f"{execution_time:.3f}s",
                        "success": True,
                        "result_type": type(result).__name__,
                    }
                )

                # Add result size context for collections
                if isinstance(result, (list, dict)):
                    context["result_size"] = len(result)

                # Log based on execution time and settings
                if execution_time > 1.0:
                    # Slow operations should be logged at info level
                    logger.info(
                        f"Docker operation completed (slow): {operation_name}",
                        **context,
                    )
                elif settings.docker.debug_docker_client:
                    # Debug mode: log all operations
                    logger.debug(
                        f"Docker operation completed: {operation_name}", **context
                    )

                return result

            except Exception as e:
                execution_time = time.time() - start_time
                context.update(
                    {
                        "execution_time": f"{execution_time:.3f}s",
                        "success": False,
                        "error": sanitize_exception(e),
                    }
                )

                logger.error(f"Docker operation failed: {operation_name}", **context)
                raise

        return wrapper

    return decorator


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


@with_operation_logging("get_container_attributes")
def __get_container_attributes(container_id: str) -> Container:
    """
    Retrieve the details of a Docker container.

    Args:
        container_id: The ID of the container.

    Returns:
        Container: The container object.

    Raises:
        ContainerNotFoundError: If the container cannot be found.
        DockerOperationError: If the operation fails.
    """
    context = {
        "action": "container_attributes",
        "container_id": container_id,
    }

    if not container_id:
        logger.warning("Empty container ID provided", **context)
        raise ValueError("Container ID cannot be empty")

    try:
        with DockerAdapter() as adapter:
            container = adapter.containers.get(container_id)
            logger.debug("Container attributes retrieved", **context)
            return container

    except NotFound:
        logger.warning("Container not found", **context)
        raise ContainerNotFoundError(
            ErrorContext(
                message="Container not found",
                error_code="DOCKER_001",
                metadata={"container_id": container_id},
            )
        )
    except Exception as e:
        logger.error(
            "Failed to get container attributes", error=sanitize_exception(e), **context
        )
        raise DockerOperationException(
            ErrorContext(
                message="Failed to get container attributes",
                error_code="DOCKER_002",
                metadata={"container_id": container_id, "exception": str(e)},
            )
        )


@with_operation_logging("aggregate_container_details")
def __aggregate_container_details(container_id: str) -> Dict[str, str]:
    """
    Aggregates details of a Docker container into a dictionary.

    Args:
        container_id: The ID of the container.

    Returns:
        Dict containing container details.
    """
    context = {
        "action": "container_details_aggregation",
        "container_id": container_id,
    }

    try:
        container_details = __get_container_attributes(container_id)
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
    context = {
        "action": "container_logs_fetch",
        "container_id": container_id,
    }

    try:
        container = __get_container_attributes(container_id)
        logs = container.logs(tail=50, stdout=True, stderr=True, timestamps=True)
        log_content = logs.decode("utf-8", errors="replace")[-3800:]

        logger.debug("Container logs fetched", log_size=len(log_content), **context)

        return log_content

    except NotFound:
        logger.warning("Container not found for logs fetch", **context)
        raise ContainerNotFoundError(
            ErrorContext(
                message="Container not found",
                error_code="DOCKER_001",
                metadata={"container_id": container_id},
            )
        )
    except Exception as e:
        logger.error(
            "Failed to fetch container logs", error=sanitize_exception(e), **context
        )
        raise DockerOperationException(
            ErrorContext(
                message="Failed to fetch container logs",
                error_code="DOCKER_002",
                metadata={"container_id": container_id, "exception": str(e)},
            )
        )


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


@with_operation_logging("get_container_state")
def get_container_state(container_id: str) -> Optional[str]:
    """
    Retrieves the status of a Docker container.

    Args:
        container_id: The ID of the container.

    Returns:
        Container status string or None if not found.
    """
    context = {
        "action": "container_state_check",
        "container_id": container_id,
    }

    try:
        container = __get_container_attributes(container_id)
        status = container.status

        logger.debug("Container state retrieved", status=status, **context)

        return status

    except ContainerNotFoundError:
        logger.debug("Container not found for state check", **context)
        return None

    except Exception as e:
        logger.error(
            "Failed to get container state", error=sanitize_exception(e), **context
        )
        return None


@with_operation_logging("fetch_full_container_details")
def fetch_full_container_details(container_id: str):
    """
    Retrieves and returns the full attributes of a Docker container.

    Args:
        container_id (str): The ID of the container.

    Returns:
        dict: A dictionary containing the full attributes of the Docker container.
    """
    context = {
        "action": "full_container_details",
        "container_id": container_id,
    }

    try:
        container = __get_container_attributes(container_id)
        logger.debug("Full container details retrieved", **context)
        return container

    except NotFound:
        logger.warning("Container not found for full details", **context)
        return {}

    except Exception as e:
        logger.error(
            "Failed to fetch full container details",
            error=sanitize_exception(e),
            **context,
        )
        return {}
