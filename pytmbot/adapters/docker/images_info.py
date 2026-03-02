#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from datetime import UTC, datetime

from docker.errors import APIError, ImageNotFound
from docker.models.images import Image

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.utils import with_operation_logging
from pytmbot.exceptions import DockerConnectionError, ImageOperationError
from pytmbot.logs import Logger
from pytmbot.utils import as_object_dict, set_naturalsize, set_naturaltime

logger = Logger()


def _safe_dict(value: object) -> dict[str, object]:
    return as_object_dict(value)


def _safe_list_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _safe_labels(value: object) -> dict[str, str]:
    raw_labels = _safe_dict(value)
    labels: dict[str, str] = {}
    for raw_key, raw_value in raw_labels.items():
        key = str(raw_key).strip()
        if not key:
            continue
        labels[key] = str(raw_value)
    return labels


def _parse_created(created_raw: object) -> tuple[datetime | None, str]:
    if not isinstance(created_raw, str) or not created_raw.strip():
        return None, "N/A"

    created_clean = created_raw.strip().split(".")[0].rstrip("Z")
    if not created_clean:
        return None, "N/A"

    try:
        created_time = datetime.fromisoformat(created_clean)
    except ValueError:
        return None, "N/A"

    created_at_utc = (
        created_time.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        if created_time.tzinfo is None
        else created_time.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    )
    return created_time, created_at_utc


def _safe_id(value: object, *, max_length: int = 24, default: str = "N/A") -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    if not normalized:
        return default
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    return normalized[:max_length]


def _safe_ns_duration(value: object) -> str:
    if not isinstance(value, int) or value <= 0:
        return "N/A"
    seconds = value / 1_000_000_000
    if seconds >= 60:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    return f"{seconds:.1f}s"


def _safe_int(value: object, *, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _format_iso_timestamp(raw: object) -> str:
    if not isinstance(raw, str):
        return "N/A"
    value = raw.strip()
    if not value or value.startswith("0001-01-01"):
        return "N/A"
    clean_value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(clean_value)
    except ValueError:
        return "N/A"
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_healthcheck(config: dict[str, object]) -> str:
    raw_health = _safe_dict(config.get("Healthcheck"))
    if not raw_health:
        return "none"

    test = _safe_list_strings(raw_health.get("Test"))
    if not test:
        return "none"

    parts = [f"test={' '.join(test)}"]
    interval = _safe_ns_duration(raw_health.get("Interval"))
    timeout = _safe_ns_duration(raw_health.get("Timeout"))
    start_period = _safe_ns_duration(raw_health.get("StartPeriod"))
    retries = raw_health.get("Retries")

    if interval != "N/A":
        parts.append(f"interval={interval}")
    if timeout != "N/A":
        parts.append(f"timeout={timeout}")
    if start_period != "N/A":
        parts.append(f"start_period={start_period}")
    if isinstance(retries, int) and retries >= 0:
        parts.append(f"retries={retries}")

    return "; ".join(parts)


def process_image_attrs(image: Image) -> dict[str, object]:
    """
    Process Docker image attributes into a standardized format.

    Args:
        image: Docker image object

    Returns:
        Dictionary containing formatted image details
    """
    try:
        attrs = _safe_dict(image.attrs)
        created_time, created_at_utc = _parse_created(attrs.get("Created"))

        # Safely handle RepoTags - if empty or None, use first tag from image.tags or "N/A"
        repo_tags = _safe_list_strings(attrs.get("RepoTags"))
        if repo_tags:
            primary_name = repo_tags[0]
        elif image.tags:
            primary_name = image.tags[0]
        else:
            primary_name = "<none>:<none>"

        config = _safe_dict(attrs.get("Config"))
        if not config:
            config = _safe_dict(attrs.get("ContainerConfig"))
        container_config = _safe_dict(attrs.get("ContainerConfig"))

        labels = _safe_labels(config.get("Labels"))
        if not labels:
            labels = _safe_labels(container_config.get("Labels"))

        exposed_ports_dict = _safe_dict(config.get("ExposedPorts"))
        if not exposed_ports_dict:
            exposed_ports_dict = _safe_dict(container_config.get("ExposedPorts"))

        rootfs = _safe_dict(attrs.get("RootFS"))
        rootfs_layers = _safe_list_strings(rootfs.get("Layers"))

        parent_id = _safe_id(attrs.get("Parent"))
        repo_digests = _safe_list_strings(attrs.get("RepoDigests"))

        healthcheck = _format_healthcheck(config)
        size_bytes = _safe_int(attrs.get("Size"))
        virtual_size_bytes = _safe_int(attrs.get("VirtualSize"), default=size_bytes)
        shared_size_bytes = _safe_int(attrs.get("SharedSize"), default=-1)

        return {
            "id": image.short_id,
            "name": primary_name,
            "tags": image.tags or ["<none>"],
            "repo_digests": repo_digests,
            "repo_digests_count": len(repo_digests),
            "architecture": attrs.get("Architecture", "N/A"),
            "variant": attrs.get("Variant", "N/A"),
            "os": attrs.get("Os", "N/A"),
            "size": set_naturalsize(size_bytes),
            "virtual_size": set_naturalsize(virtual_size_bytes),
            "shared_size": (
                set_naturalsize(shared_size_bytes) if shared_size_bytes >= 0 else "N/A"
            ),
            "created": set_naturaltime(created_time) if created_time else "N/A",
            "created_at": created_at_utc,
            "author": attrs.get("Author", "N/A"),
            "docker_version": attrs.get("DockerVersion", "N/A"),
            "comment": attrs.get("Comment", "N/A"),
            "parent_id": parent_id,
            "rootfs_type": rootfs.get("Type", "N/A"),
            "layers_count": len(rootfs_layers),
            "labels": labels,
            "label_count": len(labels),
            "exposed_ports": sorted(str(port) for port in exposed_ports_dict.keys()),
            "env_variables": _safe_list_strings(
                config.get("Env", container_config.get("Env"))
            ),
            "entrypoint": _safe_list_strings(
                config.get("Entrypoint", container_config.get("Entrypoint"))
            ),
            "cmd": _safe_list_strings(config.get("Cmd", container_config.get("Cmd"))),
            "shell": _safe_list_strings(
                config.get("Shell", container_config.get("Shell"))
            ),
            "volumes": sorted(
                str(volume)
                for volume in _safe_dict(
                    config.get("Volumes", container_config.get("Volumes"))
                ).keys()
            ),
            "user": str(
                config.get("User", container_config.get("User", "root")) or "root"
            ),
            "working_dir": str(
                config.get("WorkingDir", container_config.get("WorkingDir", "/")) or "/"
            ),
            "stop_signal": str(
                config.get(
                    "StopSignal",
                    container_config.get("StopSignal", "SIGTERM"),
                )
                or "SIGTERM"
            ),
            "healthcheck": healthcheck,
        }
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        logger.error(
            "docker.images.image.attributes.fail",
            image_id=image.short_id,
            error=str(e),
        )
        return {
            "id": image.short_id,
            "error": f"Failed to process image attributes: {e}",
        }


@with_operation_logging("fetch_image_details")
def fetch_image_details() -> list[dict[str, object]]:
    """
    Fetches detailed information about Docker images.

    Returns:
        List of dictionaries containing image details.

    Raises:
        ImageOperationError: If the operation fails.
    """
    try:
        with docker_client_context() as adapter:
            images = adapter.images.list(all=True)
            images_data = [process_image_attrs(image) for image in images]
            return images_data

    except DockerConnectionError as e:
        raise ImageOperationError(f"Failed to connect to Docker daemon: {e}")
    except APIError as e:
        raise ImageOperationError(f"Docker API error: {e}")
    except Exception as e:
        raise ImageOperationError(f"Unexpected error: {e}")


@with_operation_logging("get_image_history")
def get_image_history(image_id: str) -> list[dict[str, object]]:
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
        with docker_client_context() as adapter:
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
                    "tags": layer.get("Tags", []),
                }
                for layer in history
            ]

    except ImageNotFound:
        raise ImageNotFound(f"Image {image_id} not found")
    except Exception as e:
        raise ImageOperationError(f"Failed to get image history: {e}")


@with_operation_logging("get_image_stats")
def get_image_stats() -> dict[str, object]:
    """
    Get statistics about Docker images.

    Returns:
        Dictionary containing image statistics
    """
    try:
        with docker_client_context() as adapter:
            images = adapter.images.list(all=True)

            total_size = sum(image.attrs.get("Size", 0) for image in images)
            os_types = {image.attrs.get("Os", "unknown") for image in images}
            architectures = {
                image.attrs.get("Architecture", "unknown") for image in images
            }

            return {
                "total_images": len(images),
                "total_size": set_naturalsize(total_size),
                "operating_systems": list(os_types),
                "architectures": list(architectures),
                "tagged_images": sum(1 for image in images if image.tags),
                "untagged_images": sum(1 for image in images if not image.tags),
            }

    except Exception as e:
        raise ImageOperationError(f"Failed to get image statistics: {e}")


@with_operation_logging("get_image_usage")
def get_image_usage(image_id: str) -> dict[str, object]:
    """
    Return containers currently using the target image.

    Args:
        image_id: Docker image id or reference

    Returns:
        Dictionary with usage counters and container rows
    """
    try:
        with docker_client_context() as adapter:
            image = adapter.images.get(image_id)
            target_image_id = str(getattr(image, "id", "") or "")
            if not target_image_id:
                raise ImageOperationError("Image id is unavailable")

            containers = adapter.containers.list(all=True)
            usage_rows: list[dict[str, str]] = []
            running_count = 0

            for container in containers:
                container_image = getattr(container, "image", None)
                container_image_id = str(getattr(container_image, "id", "") or "")
                if container_image_id != target_image_id:
                    continue

                attrs = getattr(container, "attrs", {})
                state = attrs.get("State", {}) if isinstance(attrs, dict) else {}
                status = str(
                    state.get("Status", getattr(container, "status", "unknown"))
                    or "unknown"
                )
                if status == "running":
                    running_count += 1

                usage_rows.append(
                    {
                        "name": str(getattr(container, "name", "unknown") or "unknown"),
                        "id": str(getattr(container, "short_id", "N/A") or "N/A"),
                        "status": status,
                        "started_at": _format_iso_timestamp(state.get("StartedAt")),
                    }
                )

            usage_rows.sort(
                key=lambda row: (0 if row["status"] == "running" else 1, row["name"])
            )
            total = len(usage_rows)
            stopped_count = total - running_count

            return {
                "containers": usage_rows,
                "containers_count": total,
                "running_count": running_count,
                "stopped_count": stopped_count,
            }

    except ImageNotFound:
        raise ImageNotFound(f"Image {image_id} not found")
    except Exception as e:
        raise ImageOperationError(f"Failed to get image usage: {e}")
