#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from functools import wraps
from typing import Callable, Dict, Any

from docker.errors import NotFound
from docker.models.containers import Container

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.globals import settings, session_manager
from pytmbot.logs import Logger
from pytmbot.models.docker_models import (
    ContainerId,
    ContainerConfig,
    DockerResponse,
    ContainerAction,
)
from pytmbot.utils import is_new_name_valid, sanitize_exception

logger = Logger()


def validate_access(func: Callable) -> Callable:
    """Decorator for validating user access to container operations."""

    @wraps(func)
    def wrapper(self, user_id: int, container_id: ContainerId, *args, **kwargs) -> any:
        context = {
            "action": "access_validation",
            "user_id": user_id,
            "container_id": container_id,
            "operation": func.__name__,
        }

        # Check authorization
        if not (
            user_id in settings.access_control.allowed_admins_ids
            and session_manager.is_authenticated(user_id)
        ):
            logger.critical("Unauthorized container access attempt", **context)
            raise PermissionError(f"User {user_id} not authorized to manage containers")

        # Log successful authorization at debug level to avoid noise
        logger.debug("Container access authorized", **context)
        return func(self, user_id, container_id, *args, **kwargs)

    return wrapper


class ContainerManager:
    """Securely manages Docker containers with strict access control."""

    @staticmethod
    def __get_container(container_id: ContainerId) -> Container:
        """Safely retrieves a container reference."""
        context = {
            "action": "container_retrieval",
            "container_id": container_id,
        }

        try:
            with DockerAdapter() as adapter:
                container = adapter.containers.get(container_id)
                logger.debug("Container retrieved successfully", **context)
                return container

        except NotFound:
            logger.error("Container not found", **context)
            raise
        except Exception as e:
            logger.error(
                "Container retrieval failed", error=sanitize_exception(e), **context
            )
            raise

    @validate_access
    def __start_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Starts a Docker container with access validation."""
        context = {
            "action": "container_start",
            "container_id": container_id,
            "user_id": user_id,
        }

        try:
            container = self.__get_container(container_id)

            # Business logic operation - log at info level
            logger.info("Starting container", **context)

            result = container.start()

            # Log successful completion
            logger.info("Container started successfully", **context)
            return result

        except Exception as e:
            logger.error(
                "Container start failed", error=sanitize_exception(e), **context
            )
            raise

    @validate_access
    def __stop_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Stops a Docker container with access validation."""
        context = {
            "action": "container_stop",
            "container_id": container_id,
            "user_id": user_id,
        }

        try:
            container = self.__get_container(container_id)

            # Business logic operation - log at info level
            logger.info("Stopping container", **context)

            result = container.stop()

            # Log successful completion
            logger.info("Container stopped successfully", **context)
            return result

        except Exception as e:
            logger.error(
                "Container stop failed", error=sanitize_exception(e), **context
            )
            raise

    @validate_access
    def __restart_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Restarts a Docker container with access validation."""
        context = {
            "action": "container_restart",
            "container_id": container_id,
            "user_id": user_id,
        }

        try:
            container = self.__get_container(container_id)

            # Business logic operation - log at info level
            logger.info("Restarting container", **context)

            result = container.restart()

            # Log successful completion
            logger.info("Container restarted successfully", **context)
            return result

        except Exception as e:
            logger.error(
                "Container restart failed", error=sanitize_exception(e), **context
            )
            raise

    @validate_access
    def __rename_container(
        self, user_id: int, container_id: ContainerId, new_container_name: str
    ) -> DockerResponse:
        """Renames a Docker container with access and input validation."""
        context = {
            "action": "container_rename",
            "container_id": container_id,
            "user_id": user_id,
            "new_name": new_container_name,
        }

        # Validate new name
        if not is_new_name_valid(new_container_name):
            logger.warning(
                "Invalid container name rejected",
                validation_error="name_format_invalid",
                **context,
            )
            raise ValueError(f"Invalid container name: {new_container_name}")

        try:
            container = self.__get_container(container_id)

            # Business logic operation - log at info level
            logger.info("Renaming container", **context)

            result = container.rename(new_container_name)

            # Log successful completion
            logger.info("Container renamed successfully", **context)
            return result

        except Exception as e:
            logger.error(
                "Container rename failed", error=sanitize_exception(e), **context
            )
            raise

    def managing_container(
        self,
        user_id: int,
        container_id: ContainerId,
        action: str,
        **kwargs: ContainerConfig,
    ) -> DockerResponse:
        """Manages container operations with comprehensive validation."""
        context = {
            "action": "container_management",
            "user_id": user_id,
            "container_id": container_id,
            "operation": action,
        }

        # Sanitize kwargs for logging - remove sensitive data
        safe_kwargs = self._sanitize_kwargs(kwargs)
        if safe_kwargs:
            context["params"] = safe_kwargs

        try:
            container_action = ContainerAction.from_str(action)

            # Define action mapping
            actions = {
                ContainerAction.START: self.__start_container,
                ContainerAction.STOP: self.__stop_container,
                ContainerAction.RESTART: self.__restart_container,
                ContainerAction.RENAME: lambda u, c: self.__rename_container(
                    u, c, kwargs.get("new_container_name", "")
                ),
            }

            # Log business operation request at info level
            logger.info("Container management request received", **context)

            # Execute the action
            result = actions[container_action](user_id, container_id)

            # Log successful completion
            logger.info("Container management completed successfully", **context)
            return result

        except (ValueError, KeyError) as e:
            logger.warning(
                "Invalid container action requested",
                error=sanitize_exception(e),
                available_actions=list(ContainerAction),
                **context,
            )
            raise ValueError(f"Invalid action: {action}")

        except PermissionError as e:
            # Already logged in validator, just re-raise
            raise

        except Exception as e:
            logger.error(
                "Container management failed", error=sanitize_exception(e), **context
            )
            raise

    def _sanitize_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize kwargs for safe logging, removing sensitive information."""
        # Define sensitive keys that should not be logged
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

    def get_container_status(self, container_id: ContainerId) -> Dict[str, Any]:
        """Get container status information for monitoring."""
        context = {
            "action": "container_status",
            "container_id": container_id,
        }

        try:
            container = self.__get_container(container_id)

            # Get container status
            status = {
                "id": container.id,
                "name": container.name,
                "status": container.status,
                "image": container.image.tags[0] if container.image.tags else "unknown",
                "created": container.attrs.get("Created", "unknown"),
            }

            logger.debug(
                "Container status retrieved", status=status["status"], **context
            )
            return status

        except Exception as e:
            logger.error(
                "Container status retrieval failed",
                error=sanitize_exception(e),
                **context,
            )
            raise
