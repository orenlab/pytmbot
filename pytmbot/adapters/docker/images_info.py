#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from docker.client import DockerClient
from docker.errors import APIError, ImageNotFound
from docker.models.images import Image

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.utils import (
    MIN_CONTAINER_ID_PREFIX_LENGTH,
    command_executable,
    docker_unavailable_as_connection_error,
    mask_build_step,
    mask_command_args,
    mask_entrypoint_and_cmd,
    mask_environment_variables,
    mask_healthcheck_test,
    mask_secrets_in_text,
    mask_url_credentials,
    parse_docker_timestamp,
    with_operation_logging,
)
from pytmbot.exceptions import DockerConnectionError, ImageOperationError
from pytmbot.logs import Logger
from pytmbot.utils import (
    as_object_dict,
    sanitize_exception,
    set_naturalsize,
    set_naturaltime,
)

logger = Logger()


IMAGE_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_.:/@-]{0,511}$"
)
_HEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-f0-9]+$")
_HEALTHCHECK_KINDS: Final[frozenset[str]] = frozenset({"CMD", "CMD-SHELL"})


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
        labels[key] = mask_url_credentials(str(raw_value))
    return labels


def _parse_created(created_raw: object) -> tuple[datetime | None, str]:
    """Parse image creation time as a timezone-aware UTC datetime."""
    created_time = parse_docker_timestamp(created_raw)
    if created_time is None:
        return None, "N/A"
    return created_time, created_time.strftime("%Y-%m-%d %H:%M:%S UTC")


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
    parsed = parse_docker_timestamp(raw)
    return parsed.strftime("%Y-%m-%d %H:%M:%S UTC") if parsed else "N/A"


def _healthcheck_test_text(test: list[str], *, show_arguments: bool) -> str:
    """The masked test, or only its kind and executable (``CMD-SHELL curl``)."""
    masked = mask_healthcheck_test(test)
    if show_arguments:
        return " ".join(masked)
    kind = masked[:1] if masked[0] in _HEALTHCHECK_KINDS else []
    executable = command_executable(masked[len(kind) :])
    return " ".join([*kind, executable] if executable else kind)


def _format_healthcheck(
    config: dict[str, object], *, show_arguments: bool = True
) -> str:
    raw_health = _safe_dict(config.get("Healthcheck"))
    if not raw_health:
        return "none"

    test = _safe_list_strings(raw_health.get("Test"))
    if not test:
        return "none"

    parts = [f"test={_healthcheck_test_text(test, show_arguments=show_arguments)}"]
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

        entrypoint, cmd = mask_entrypoint_and_cmd(
            _safe_list_strings(
                config.get("Entrypoint", container_config.get("Entrypoint"))
            ),
            _safe_list_strings(config.get("Cmd", container_config.get("Cmd"))),
        )
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
            "comment": mask_secrets_in_text(str(attrs.get("Comment") or "N/A")),
            "parent_id": parent_id,
            "rootfs_type": rootfs.get("Type", "N/A"),
            "layers_count": len(rootfs_layers),
            "labels": labels,
            "label_count": len(labels),
            "exposed_ports": sorted(str(port) for port in exposed_ports_dict.keys()),
            "env_variables": mask_environment_variables(
                _safe_list_strings(config.get("Env", container_config.get("Env")))
            ),
            "entrypoint": entrypoint,
            "cmd": cmd,
            "shell": mask_command_args(
                _safe_list_strings(config.get("Shell", container_config.get("Shell")))
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
            "healthcheck": _format_healthcheck(config),
            # Non-admin view: the test's kind and executable, no arguments.
            "healthcheck_without_arguments": _format_healthcheck(
                config, show_arguments=False
            ),
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


def list_images_tolerant(
    adapter: DockerClient, *, include_intermediate: bool
) -> list[Image]:
    """List images, skipping images removed between the list and the inspect."""
    images: list[Image] = []
    for summary in adapter.api.images(all=include_intermediate):
        image_id = summary.get("Id") if isinstance(summary, dict) else None
        if not isinstance(image_id, str) or not image_id:
            continue
        try:
            images.append(adapter.images.get(image_id))
        except ImageNotFound:
            logger.debug("docker.images.image.vanished.debug", image_id=image_id[:19])
    return images


@with_operation_logging("fetch_image_details")
def fetch_image_details() -> list[dict[str, object]]:
    """
    Fetch detailed information about Docker images.

    Raises:
        DockerConnectionError: If Docker is unavailable.
        ImageOperationError: If the operation fails for another reason.
    """
    try:
        with (
            docker_unavailable_as_connection_error("image listing"),
            docker_client_context() as adapter,
        ):
            images = list_images_tolerant(adapter, include_intermediate=True)
    except DockerConnectionError:
        raise
    except APIError as e:
        raise ImageOperationError(f"Docker API error: {e}") from e
    except Exception as e:
        raise ImageOperationError(f"Unexpected error: {e}") from e

    return [process_image_attrs(image) for image in images]


def _validate_image_reference(image_id: object) -> str:
    candidate = image_id.strip() if isinstance(image_id, str) else ""
    if (
        not candidate
        or ".." in candidate
        or "//" in candidate
        or not IMAGE_REFERENCE_PATTERN.fullmatch(candidate)
    ):
        raise ImageOperationError("Invalid image reference")
    return candidate


def _image_names(image: object) -> set[str]:
    attrs = as_object_dict(getattr(image, "attrs", {}))
    return set(_safe_list_strings(attrs.get("RepoTags"))) | set(
        _safe_list_strings(attrs.get("RepoDigests"))
    )


def _image_matches_reference(image: object, reference: str) -> bool:
    """
    Check that dockerd resolved ``reference`` to the intended image.

    Accepts an exact tag/digest (``name`` means ``name:latest``) or an image ID
    prefix of at least 12 hex characters (optionally ``sha256:``-prefixed).
    """
    hex_reference = reference.removeprefix("sha256:")
    image_hex_id = str(getattr(image, "id", "") or "").removeprefix("sha256:")
    if (
        len(hex_reference) >= MIN_CONTAINER_ID_PREFIX_LENGTH
        and _HEX_PATTERN.fullmatch(hex_reference)
        and image_hex_id.startswith(hex_reference)
    ):
        return True

    names = _image_names(image)
    untagged = "@" not in reference and ":" not in reference.rsplit("/", 1)[-1]
    return reference in names or (untagged and f"{reference}:latest" in names)


def _get_verified_image(adapter: DockerClient, reference: str) -> Image | None:
    try:
        image = adapter.images.get(reference)
    except ImageNotFound:
        return None
    if not _image_matches_reference(image, reference):
        logger.warning(
            "docker.images.image.reference.mismatch.warn",
            reference=reference[:64],
            resolved_id=str(getattr(image, "id", ""))[:19],
        )
        return None
    return image


def _run_image_lookup[T](
    image_id: str,
    operation: str,
    handler: Callable[[DockerClient, Image], T],
) -> T | None:
    """Resolve and verify an image, then run ``handler``; None when not found."""
    reference = _validate_image_reference(image_id)
    try:
        with (
            docker_unavailable_as_connection_error(operation),
            docker_client_context() as adapter,
        ):
            image = _get_verified_image(adapter, reference)
            return None if image is None else handler(adapter, image)
    except (DockerConnectionError, ImageOperationError):
        raise
    except ImageNotFound:
        # Image removed while the operation was running.
        return None
    except Exception as e:
        raise ImageOperationError(
            f"Failed to {operation}: {sanitize_exception(e)}"
        ) from e


def _format_history_layer(layer: dict[str, object]) -> dict[str, object]:
    created_raw = layer.get("Created")
    created = (
        datetime.fromtimestamp(created_raw, tz=UTC)
        if isinstance(created_raw, (int, float)) and created_raw > 0
        else None
    )
    return {
        "id": str(layer.get("Id", "N/A"))[:12],
        "created": set_naturaltime(created) if created else "N/A",
        "created_by": mask_build_step(str(layer.get("CreatedBy", "N/A"))),
        "size": set_naturalsize(_safe_int(layer.get("Size"))),
        "comment": mask_secrets_in_text(str(layer.get("Comment") or "")),
        "tags": layer.get("Tags") or [],
    }


def _collect_image_history(
    _adapter: DockerClient, image: Image
) -> list[dict[str, object]]:
    history = image.history()
    return [
        _format_history_layer(layer) for layer in history if isinstance(layer, dict)
    ]


@with_operation_logging("get_image_history")
def get_image_history(image_id: str) -> list[dict[str, object]] | None:
    """
    Fetch the history of a Docker image (short/full ID or exact tag).

    Build-step values (``ENV``/``ARG``/``KEY=VALUE``) and URL credentials in
    ``created_by`` are masked.

    Returns:
        History rows, or None if the image does not exist.

    Raises:
        DockerConnectionError: If Docker is unavailable.
        ImageOperationError: If the reference is invalid or the operation fails.
    """
    return _run_image_lookup(image_id, "get image history", _collect_image_history)


def _container_image_id(container: object) -> str:
    attrs = as_object_dict(getattr(container, "attrs", {}))
    return str(attrs.get("Image") or "")


def _build_usage_row(container: object) -> dict[str, str]:
    attrs = as_object_dict(getattr(container, "attrs", {}))
    state = as_object_dict(attrs.get("State"))
    status = str(
        state.get("Status", getattr(container, "status", "unknown")) or "unknown"
    )
    return {
        "name": str(getattr(container, "name", "unknown") or "unknown"),
        "id": str(getattr(container, "short_id", "N/A") or "N/A"),
        "status": status,
        "started_at": _format_iso_timestamp(state.get("StartedAt")),
    }


def _collect_image_usage(adapter: DockerClient, image: Image) -> dict[str, object]:
    target_image_id = str(getattr(image, "id", "") or "")
    if not target_image_id:
        raise ImageOperationError("Image id is unavailable")

    # Compare the container's image ID attribute instead of ``container.image``:
    # the latter inspects the image and fails for force-removed images.
    usage_rows = [
        _build_usage_row(container)
        for container in adapter.containers.list(all=True, ignore_removed=True)
        if _container_image_id(container) == target_image_id
    ]
    usage_rows.sort(
        key=lambda row: (0 if row["status"] == "running" else 1, row["name"])
    )
    running_count = sum(1 for row in usage_rows if row["status"] == "running")
    return {
        "containers": usage_rows,
        "containers_count": len(usage_rows),
        "running_count": running_count,
        "stopped_count": len(usage_rows) - running_count,
    }


@with_operation_logging("get_image_usage")
def get_image_usage(image_id: str) -> dict[str, object] | None:
    """
    Return containers currently using the target image.

    Returns:
        Usage counters and container rows, or None if the image does not exist.

    Raises:
        DockerConnectionError: If Docker is unavailable.
        ImageOperationError: If the reference is invalid or the operation fails.
    """
    return _run_image_lookup(image_id, "get image usage", _collect_image_usage)
