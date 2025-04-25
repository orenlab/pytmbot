#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
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
from pytmbot.exceptions import ContainerNotFoundError, DockerOperationException, ErrorContext
from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.utils import set_naturaltime

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
            operation_context = {
                'operation': operation_name,
                'args': args,
                'kwargs': kwargs,
                'start_time': datetime.now().isoformat()
            }

            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time

                operation_context.update({
                    'execution_time': f"{execution_time:.3f}s",
                    'success': True,
                    'result_type': type(result).__name__
                })

                if settings.docker.debug_docker_client:
                    logger.debug(
                        f"Docker operation completed: {operation_name}",
                        extra=operation_context
                    )

                return result

            except Exception as e:
                execution_time = time.time() - start_time
                operation_context.update({
                    'execution_time': f"{execution_time:.3f}s",
                    'success': False,
                    'error': str(e),
                    'error_type': type(e).__name__
                })

                logger.error(
                    f"Docker operation failed: {operation_name}",
                    extra=operation_context
                )
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
    if not container_id:
        raise ValueError("Container ID cannot be empty")

    try:
        with DockerAdapter() as adapter:
            return adapter.containers.get(container_id)
    except NotFound:
        raise ContainerNotFoundError(ErrorContext(
            message="Container not found",
            error_code="DOCKER_001",
            metadata={"container_id": container_id}
        ))
    except Exception as e:
        raise DockerOperationException(ErrorContext(
            message="Failed to get container attributes",
            error_code="DOCKER_002",
            metadata={"container_id": container_id, "exception": str(e)}
        ))


@with_operation_logging("aggregate_container_details")
def __aggregate_container_details(container_id: str) -> Dict[str, str]:
    """
    Aggregates details of a Docker container into a dictionary.

    Args:
        container_id: The ID of the container.

    Returns:
        Dict containing container details.
    """
    container_details = __get_container_attributes(container_id)
    attrs = container_details.attrs

    created_at = datetime.fromisoformat(attrs["Created"])

    return {
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


@with_operation_logging("retrieve_containers_stats")
def retrieve_containers_stats() -> List[Dict[str, str]]:
    """
    Retrieves and returns details of Docker containers using parallel processing.

    Returns:
        List of container details dictionaries.
    """
    containers_id = __fetch_containers_list()
    if not containers_id:
        return []

    container_details = []
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
                logger.error(
                    f"Failed to process container {container_id}: {e}",
                    extra={'container_id': container_id, 'error': str(e)}
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
    try:
        container = __get_container_attributes(container_id)
        logs = container.logs(
            tail=50,
            stdout=True,
            stderr=True,
            timestamps=True
        )
        return logs.decode("utf-8", errors="replace")[-3800:]
    except NotFound:
        raise ContainerNotFoundError(ErrorContext(
            message="Container not found",
            error_code="DOCKER_001",
            metadata={"container_id": container_id}
        ))
    except Exception as e:
        raise DockerOperationException(ErrorContext(
            message="Failed to get container attributes",
            error_code="DOCKER_002",
            metadata={"container_id": container_id, "exception": str(e)}
        ))


@with_operation_logging("fetch_docker_counters")
def fetch_docker_counters() -> Dict[str, int]:
    """
    Fetches Docker image and container counts.

    Returns:
        Dict with image and container counts.
    """
    with DockerAdapter() as adapter:
        return {
            "images_count": len(adapter.images.list()),
            "containers_count": len(adapter.containers.list(all=True))
        }


@with_operation_logging("get_container_state")
def get_container_state(container_id: str) -> Optional[str]:
    """
    Retrieves the status of a Docker container.

    Args:
        container_id: The ID of the container.

    Returns:
        Container status string or None if not found.
    """
    try:
        container = __get_container_attributes(container_id)
        return container.status
    except ContainerNotFoundError:
        return None
    except Exception as e:
        logger.error(f"Failed to get container state: {e}")
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
    try:
        return __get_container_attributes(container_id)
    except NotFound:
        logger.error(f"Container {container_id} not found.")
        return {}
