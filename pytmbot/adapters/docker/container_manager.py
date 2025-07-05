from functools import wraps
from typing import Callable

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
from pytmbot.utils import is_new_name_valid

logger = Logger()


def validate_access(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(self, user_id: int, container_id: ContainerId, *args, **kwargs) -> any:
        if not (
            user_id in settings.access_control.allowed_admins_ids
            and session_manager.is_authenticated(user_id)
        ):
            logger.critical(
                "Unauthorized container access attempt",
                extra={
                    "user_id": user_id,
                    "container_id": container_id,
                    "action": func.__name__,
                },
            )
            raise PermissionError(f"User {user_id} not authorized to manage containers")
        return func(self, user_id, container_id, *args, **kwargs)

    return wrapper


class ContainerManager:
    """Securely manages Docker containers with strict access control."""

    @staticmethod
    def __get_container(container_id: ContainerId) -> Container:
        """Safely retrieves a container reference."""
        try:
            with DockerAdapter() as adapter:
                return adapter.containers.get(container_id)
        except NotFound:
            logger.error("Container access error", extra={"container_id": container_id})
            raise
        except Exception as e:
            logger.error(
                "Container retrieval failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "container_id": container_id,
                },
            )
            raise

    @validate_access
    def __start_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Starts a Docker container with access validation."""
        try:
            container = self.__get_container(container_id)
            logger.info(
                "Starting container",
                extra={"container_id": container_id, "user_id": user_id},
            )
            return container.start()
        except Exception as e:
            logger.error(
                "Container start failed",
                extra={
                    "error": str(e),
                    "container_id": container_id,
                    "user_id": user_id,
                },
            )
            raise

    @validate_access
    def __stop_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Stops a Docker container with access validation."""
        try:
            container = self.__get_container(container_id)
            logger.info(
                "Stopping container",
                extra={"container_id": container_id, "user_id": user_id},
            )
            return container.stop()
        except Exception as e:
            logger.error(
                "Container stop failed",
                extra={
                    "error": str(e),
                    "container_id": container_id,
                    "user_id": user_id,
                },
            )
            raise

    @validate_access
    def __restart_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Restarts a Docker container with access validation."""
        try:
            container = self.__get_container(container_id)
            logger.info(
                "Restarting container",
                extra={"container_id": container_id, "user_id": user_id},
            )
            return container.restart()
        except Exception as e:
            logger.error(
                "Container restart failed",
                extra={
                    "error": str(e),
                    "container_id": container_id,
                    "user_id": user_id,
                },
            )
            raise

    @validate_access
    def __rename_container(
        self, user_id: int, container_id: ContainerId, new_container_name: str
    ) -> DockerResponse:
        """Renames a Docker container with access and input validation."""
        if not is_new_name_valid(new_container_name):
            logger.error(
                "Invalid container name attempt",
                extra={
                    "user_id": user_id,
                    "container_id": container_id,
                    "attempted_name": new_container_name,
                },
            )
            raise ValueError(f"Invalid container name: {new_container_name}")

        try:
            container = self.__get_container(container_id)
            logger.info(
                "Renaming container",
                extra={
                    "container_id": container_id,
                    "user_id": user_id,
                    "new_name": new_container_name,
                },
            )
            return container.rename(new_container_name)
        except Exception as e:
            logger.error(
                "Container rename failed",
                extra={
                    "error": str(e),
                    "container_id": container_id,
                    "user_id": user_id,
                    "new_name": new_container_name,
                },
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
        try:
            container_action = ContainerAction.from_str(action)
            actions = {
                ContainerAction.START: self.__start_container,
                ContainerAction.STOP: self.__stop_container,
                ContainerAction.RESTART: self.__restart_container,
                ContainerAction.RENAME: lambda u, c: self.__rename_container(
                    u, c, kwargs.get("new_container_name", "")
                ),
            }

            logger.info(
                "Container management request",
                extra={
                    "user_id": user_id,
                    "container_id": container_id,
                    "action": action,
                    "params": kwargs,
                },
            )

            return actions[container_action](user_id, container_id)

        except (ValueError, KeyError) as e:
            logger.error(
                "Invalid container action",
                extra={"error": str(e), "user_id": user_id, "action": action},
            )
            raise ValueError(f"Invalid action: {action}")
        except Exception as e:
            logger.error(
                "Container management failed",
                extra={
                    "error": str(e),
                    "user_id": user_id,
                    "container_id": container_id,
                    "action": action,
                },
            )
            raise
