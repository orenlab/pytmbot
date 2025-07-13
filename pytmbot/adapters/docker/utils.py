#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import wraps
from time import sleep
from typing import Dict, Any, Optional
from typing import TypeAlias

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
from pytmbot.utils import sanitize_exception

logger = Logger()

ContainerName: TypeAlias = str


class ContainerState(str, Enum):
    RUNNING = "running"
    EXITED = "exited"
    STOPPED = "stopped"

    @classmethod
    def from_str(cls, value: str) -> "ContainerState":
        try:
            return cls(value.lower())
        except ValueError:
            valid_states = [state.value for state in cls]
            raise ValueError(f"State must be one of: {valid_states}")


@dataclass(frozen=True)
class StateCheckConfig:
    max_attempts: int = 3
    interval: float = 1.5


def check_container_state(
    container_name: ContainerName,
    target_state: str = ContainerState.RUNNING,
    config: StateCheckConfig = StateCheckConfig(),
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
        ValueError: If target state is invalid
    """
    try:
        target = ContainerState.from_str(target_state)
        containers_state = ContainersState()

        if target.value not in containers_state.__dict__.values():
            raise ValueError(f"Invalid state: {target}")

        for attempt in range(1, config.max_attempts + 1):
            log_context = {
                "container": container_name,
                "target": target.value,
                "attempt": attempt,
                "max_attempts": config.max_attempts,
            }

            logger.info(
                f"Checking state (attempt {attempt}/{config.max_attempts})",
                extra=log_context,
            )

            try:
                current_state = ContainerState.from_str(
                    get_container_state(container_name)
                )
                log_context["state"] = current_state.value

                if current_state == target:
                    logger.info("Target state reached", extra=log_context)
                    return current_state

                logger.warning(
                    f"State mismatch: {current_state.value}, retrying in {config.interval}s",
                    extra=log_context,
                )
                sleep(config.interval)

            except Exception as e:
                logger.error(
                    "State check failed",
                    extra={
                        **log_context,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                return None

        logger.warning(
            "Failed to reach target state",
            extra={
                "container": container_name,
                "target": target.value,
                "attempts": config.max_attempts,
            },
        )
        return current_state

    except ValueError as e:
        logger.error(
            "Invalid target state",
            extra={"container": container_name, "state": target_state, "error": str(e)},
        )
        raise


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
                # Sanitize kwargs using utility
                safe_kwargs = sanitize_kwargs_for_logging(kwargs)
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


@with_operation_logging("get_container_state")
def get_container_state(container_id: str) -> Optional[str]:
    """
    Retrieves the status of a Docker container.

    Args:
        container_id: The ID of the container.

    Returns:
        Container status string or None if not found.
    """
    context = build_container_context(
        container_id=container_id,
        action="container_state_check",
    )

    try:
        container = get_container_safely(container_id)
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


def get_container_safely(container_id: str) -> Container:
    """
    Safely retrieves a container by ID with uniform error handling.

    Args:
        container_id: Container ID

    Returns:
        Container: Container object

    Raises:
        ContainerNotFoundError: If container is not found
        DockerOperationException: For other Docker errors
    """
    context = {
        "action": "container_retrieval",
        "container_id": container_id,
    }

    if not container_id:
        logger.warning("Empty container ID provided", **context)
        raise ValueError("Container ID cannot be empty")

    try:
        with DockerAdapter() as adapter:
            container = adapter.containers.get(container_id)
            logger.debug("Container retrieved successfully", **context)
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
            "Container retrieval failed", error=sanitize_exception(e), **context
        )
        raise DockerOperationException(
            ErrorContext(
                message="Failed to retrieve container",
                error_code="DOCKER_002",
                metadata={"container_id": container_id, "exception": str(e)},
            )
        )


def sanitize_kwargs_for_logging(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitizes kwargs for safe logging by removing sensitive information.

    Args:
        kwargs: Dictionary of parameters

    Returns:
        Dict: Sanitized parameter dictionary
    """
    # Define sensitive keys that shouldn't be logged
    sensitive_keys = {
        "password",
        "token",
        "secret",
        "key",
        "auth",
        "credential",
        "private_key",
        "cert",
        "certificate",
        "passwd",
        "pass",
    }

    safe_kwargs = {}
    for key, value in kwargs.items():
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            safe_kwargs[key] = "[REDACTED]"
        elif isinstance(value, str) and len(value) > 100:
            # Truncate very long strings
            safe_kwargs[key] = f"{value[:50]}...[TRUNCATED]"
        else:
            safe_kwargs[key] = value

    return safe_kwargs


def build_container_context(
    container_id: str, action: str, **extra_context
) -> Dict[str, Any]:
    """
    Creates a standard context for logging container operations.

    Args:
        container_id: Container ID
        action: Action name
        **extra_context: Additional context fields

    Returns:
        Dict: Logging context
    """
    context = {
        "action": action,
        "container_id": container_id,
    }
    context.update(extra_context)
    return context


def get_container_basic_info(container: Container) -> Dict[str, Any]:
    """
    Extracts basic container information.

    Args:
        container: Container object

    Returns:
        Dict: Basic container information
    """
    return {
        "id": container.id,
        "short_id": container.short_id,
        "name": container.name,
        "status": container.status,
        "image": container.image.tags[0] if container.image.tags else "unknown",
    }
