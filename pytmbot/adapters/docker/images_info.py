#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from datetime import datetime
from functools import wraps
from typing import List, Dict, Any

from docker.errors import APIError, ImageNotFound
from docker.models.images import Image

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.exceptions import ImageOperationError, DockerConnectionError
from pytmbot.logs import Logger
from pytmbot.utils.utilities import set_naturalsize, set_naturaltime

logger = Logger()


def with_image_logging(operation_name: str):
    """
    Decorator for logging Docker image operations with timing and context.

    Args:
        operation_name: Name of the Docker image operation being performed
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            operation_context = {
                'operation': operation_name,
                'function': func.__name__,
                'start_time': datetime.now().isoformat()
            }

            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time

                operation_context.update({
                    'execution_time': f"{execution_time:.3f}s",
                    'success': True,
                    'images_processed': len(result) if isinstance(result, list) else 0
                })

                logger.debug(
                    f"Image operation completed: {operation_name}",
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
                    f"Image operation failed: {operation_name}",
                    extra=operation_context
                )
                raise ImageOperationError(f"Failed during {operation_name}: {e}") from e

        return wrapper

    return decorator


def process_image_attrs(image: Image) -> Dict[str, Any]:
    """
    Process Docker image attributes into a standardized format.

    Args:
        image: Docker image object

    Returns:
        Dictionary containing formatted image details
    """
    try:
        created_raw = image.attrs.get("Created", "")
        created_clean = created_raw.split('.')[0].rstrip('Z')

        created_time = datetime.fromisoformat(created_clean) if created_clean else None

        # Safely handle RepoTags - if empty or None, use first tag from image.tags or "N/A"
        repo_tags = image.attrs.get("RepoTags", [])
        primary_name = (
            repo_tags[0] if repo_tags
            else (image.tags[0] if image.tags
                  else "<none>:<none>")
        )

        return {
            "id": image.short_id,
            "name": primary_name,
            "tags": image.tags or ["<none>"],
            "architecture": image.attrs.get("Architecture", "N/A"),
            "os": image.attrs.get("Os", "N/A"),
            "size": set_naturalsize(image.attrs.get("Size", 0)),
            "created": set_naturaltime(created_time) if created_time else "N/A",
            "author": image.attrs.get("Author", "N/A"),
            "docker_version": image.attrs.get("DockerVersion", "N/A"),
            "labels": image.attrs.get("ContainerConfig", {}).get("Labels", {}),
            "exposed_ports": list(
                image.attrs.get("ContainerConfig", {})
                .get("ExposedPorts", {})
                .keys()
            ),
            "env_variables": image.attrs.get("ContainerConfig", {}).get("Env", []),
            "entrypoint": image.attrs.get("ContainerConfig", {}).get("Entrypoint", []),
            "cmd": image.attrs.get("ContainerConfig", {}).get("Cmd", [])
        }
    except Exception as e:
        logger.error(
            f"Failed to process image attributes for {image.short_id}: {e}",
            extra={'image_id': image.short_id, 'error': str(e)}
        )
        return {
            "id": image.short_id,
            "error": f"Failed to process image attributes: {e}"
        }


@with_image_logging("fetch_image_details")
def fetch_image_details() -> List[Dict[str, Any]]:
    """
    Fetches detailed information about Docker images.

    Returns:
        List of dictionaries containing image details.

    Raises:
        ImageOperationError: If the operation fails.
    """
    try:
        with DockerAdapter() as adapter:
            images = adapter.images.list(all=True)
            images_data = [process_image_attrs(image) for image in images]
            return images_data

    except DockerConnectionError as e:
        raise ImageOperationError(f"Failed to connect to Docker daemon: {e}")
    except APIError as e:
        raise ImageOperationError(f"Docker API error: {e}")
    except Exception as e:
        raise ImageOperationError(f"Unexpected error: {e}")


@with_image_logging("get_image_history")
def get_image_history(image_id: str) -> List[Dict[str, Any]]:
    """
    Fetches the history of a Docker image.

    Args:
        image_id: ID of the Docker image

    Returns:
        List of dictionaries containing image layer history

    Raises:
        ImageOperationError: If the operation fails
        ImageNotFound: If the image doesn't exist
    """
    try:
        with DockerAdapter() as adapter:
            image = adapter.images.get(image_id)
            history = image.history()

            return [
                {
                    "id": layer.get("Id", "N/A")[:12],
                    "created": set_naturaltime(
                        datetime.fromtimestamp(layer.get("Created", 0))
                    ),
                    "created_by": layer.get("CreatedBy", "N/A"),
                    "size": set_naturalsize(layer.get("Size", 0)),
                    "comment": layer.get("Comment", ""),
                    "tags": layer.get("Tags", [])
                }
                for layer in history
            ]

    except ImageNotFound:
        raise ImageNotFound(f"Image {image_id} not found")
    except Exception as e:
        raise ImageOperationError(f"Failed to get image history: {e}")


@with_image_logging("get_image_stats")
def get_image_stats() -> Dict[str, Any]:
    """
    Get statistics about Docker images.

    Returns:
        Dictionary containing image statistics
    """
    try:
        with DockerAdapter() as adapter:
            images = adapter.images.list(all=True)

            total_size = sum(image.attrs.get("Size", 0) for image in images)
            os_types = set(image.attrs.get("Os", "unknown") for image in images)
            architectures = set(
                image.attrs.get("Architecture", "unknown") for image in images
            )

            return {
                "total_images": len(images),
                "total_size": set_naturalsize(total_size),
                "operating_systems": list(os_types),
                "architectures": list(architectures),
                "tagged_images": sum(1 for image in images if image.tags),
                "untagged_images": sum(1 for image in images if not image.tags)
            }

    except Exception as e:
        raise ImageOperationError(f"Failed to get image statistics: {e}")
