#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from functools import wraps
from typing import Callable, Dict, Any

from pytmbot.adapters.docker.utils import (
    get_container_safely,
    sanitize_kwargs_for_logging,
    build_container_context,
    get_container_basic_info,
)
from pytmbot.globals import settings, session_manager
from pytmbot.logs import Logger
from pytmbot.models.docker_models import (
    ContainerId,
    ContainerConfig,
    DockerResponse,
    ContainerAction,
)
from pytmbot.utils import sanitize_exception, is_new_name_valid

logger = Logger()


def validate_access(func: Callable) -> Callable:
    """Decorator for validating user access to container operations."""

    @wraps(func)
    def wrapper(self, user_id: int, container_id: ContainerId, *args, **kwargs) -> any:
        context = build_container_context(
            container_id=container_id,
            action="access_validation",
            user_id=user_id,
            operation=func.__name__,
        )

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

    @validate_access
    def __start_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Starts a Docker container with access validation."""
        context = build_container_context(
            container_id=container_id,
            action="container_start",
            user_id=user_id,
        )

        try:
            container = get_container_safely(container_id)

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
        context = build_container_context(
            container_id=container_id,
            action="container_stop",
            user_id=user_id,
        )

        try:
            container = get_container_safely(container_id)

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
        context = build_container_context(
            container_id=container_id,
            action="container_restart",
            user_id=user_id,
        )

        try:
            container = get_container_safely(container_id)

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
        context = build_container_context(
            container_id=container_id,
            action="container_rename",
            user_id=user_id,
            new_name=new_container_name,
        )

        # Validate new name
        if not is_new_name_valid(new_container_name):
            logger.warning(
                "Invalid container name rejected",
                validation_error="name_format_invalid",
                **context,
            )
            raise ValueError(f"Invalid container name: {new_container_name}")

        try:
            container = get_container_safely(container_id)

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
        # Sanitize kwargs for logging - remove sensitive data
        safe_kwargs = sanitize_kwargs_for_logging(kwargs)

        context = build_container_context(
            container_id=container_id,
            action="container_management",
            user_id=user_id,
            operation=action,
            params=safe_kwargs if safe_kwargs else None,
        )

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

    @staticmethod
    def get_container_status(container_id: ContainerId) -> Dict[str, Any]:
        """Get container status information for monitoring."""
        context = build_container_context(
            container_id=container_id,
            action="container_status",
        )

        try:
            container = get_container_safely(container_id)

            # Get basic container info using utility
            status = get_container_basic_info(container)

            # Add additional status information
            status.update(
                {
                    "created": container.attrs.get("Created", "unknown"),
                }
            )

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
