#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Union, Literal

from docker.errors import NotFound, APIError

from pytmbot.adapters.docker._adapter import DockerAdapter
from pytmbot.globals import settings, session_manager
from pytmbot.logs import bot_logger
from pytmbot.utils.utilities import is_new_name_valid


class ContainerManager:
    """Class for managing Docker containers."""

    def __start_container(self, user_id: int, container_id):
        """
        Starts a Docker container.

        Args:
            user_id (int): The ID of the user attempting to start the container.
            container_id: The ID or name of the container to be started.

        Raises:
            ValueError: If the user is not allowed to manage the container.
            NotFound: If the container was not found.
            APIError: If there was an error communicating with the Docker API.

        Returns:
            bool: True if the container was started successfully, False otherwise.
        """
        if not self.__user_is_allowed_to_manage_container(user_id):
            raise ValueError(
                f"User {user_id} is not allowed to manage container {container_id}"
            )

        try:
            with DockerAdapter() as adapter:
                bot_logger.info(f"Starting container {container_id}")
                return adapter.containers.get(container_id).start()
        except NotFound as e:
            bot_logger.error(f"Container {container_id} not found: {e}")
            raise
        except APIError as e:
            bot_logger.error(f"API error when starting container {container_id}: {e}")
            raise
        except Exception as e:
            bot_logger.error(f"Failed to start container {container_id}: {e}")
            raise

    def __stop_container(self, user_id: int, container_id):
        """
        Stops a Docker container.

        Args:
            user_id (int): The ID of the user attempting to stop the container.
            container_id: The ID or name of the container to be stopped.

        Raises:
            ValueError: If the user is not allowed to manage the container.
            NotFound: If the container was not found.
            APIError: If there was an error communicating with the Docker API.

        Returns:
            bool: True if the container was stopped successfully, False otherwise.
        """
        if not self.__user_is_allowed_to_manage_container(user_id):
            raise ValueError(
                f"User {user_id} is not allowed to manage container {container_id}"
            )

        try:
            with DockerAdapter() as adapter:
                bot_logger.info(f"Stopping container {container_id}")
                return adapter.containers.get(container_id).stop()
        except NotFound as e:
            bot_logger.error(f"Container {container_id} not found: {e}")
            raise
        except APIError as e:
            bot_logger.error(f"API error when stopping container {container_id}: {e}")
            raise
        except Exception as e:
            bot_logger.error(f"Failed to stop container {container_id}: {e}")
            raise

    def __restart_container(self, user_id: int, container_id):
        """
        Restarts a Docker container.

        Args:
            user_id (int): The ID of the user attempting to restart the container.
            container_id (str): The ID of the container to be restarted.

        Raises:
            ValueError: If the user is not allowed to manage the container.
            NotFound: If the container was not found.
            APIError: If there was an error communicating with the Docker API.

        Returns:
            bool: True if the container was restarted successfully, False otherwise.
        """
        if not self.__user_is_allowed_to_manage_container(user_id):
            raise ValueError(
                f"User {user_id} is not allowed to manage container {container_id}"
            )

        try:
            with DockerAdapter() as adapter:
                bot_logger.info(f"Restarting container {container_id}")
                return adapter.containers.get(container_id).restart()
        except NotFound as e:
            bot_logger.error(f"Container {container_id} not found: {e}")
            raise
        except APIError as e:
            bot_logger.error(f"API error when restarting container {container_id}: {e}")
            raise
        except Exception as e:
            bot_logger.error(f"Failed to restart container {container_id}: {e}")
            raise

    def __rename_container(self, user_id: int, container_id, new_container_name: str):
        """
        Renames a Docker container based on the provided parameters.

        Args:
            user_id (int): The ID of the user attempting to rename the container.
            container_id: The ID or name of the container to be renamed.
            new_container_name (str): The new name for the container.

        Raises:
            ValueError: If the user is not allowed to manage the container or if the new container name is invalid.
            NotFound: If the container was not found.
            APIError: If there was an error communicating with the Docker API.

        Returns:
            bool: True if the container was renamed successfully, False otherwise.
        """
        if not self.__user_is_allowed_to_manage_container(user_id):
            raise ValueError(
                f"User {user_id} is not allowed to manage container {container_id}"
            )

        if not is_new_name_valid(new_container_name):
            raise ValueError(f"Invalid new container name: {new_container_name}")

        try:
            with DockerAdapter() as adapter:
                bot_logger.info(
                    f"Renaming container {container_id} to {new_container_name}"
                )
                return adapter.containers.get(container_id).rename(new_container_name)
        except NotFound as e:
            bot_logger.error(f"Container {container_id} not found: {e}")
            raise
        except APIError as e:
            bot_logger.error(f"API error when renaming container {container_id}: {e}")
            raise
        except Exception as e:
            bot_logger.error(f"Failed to rename container {container_id}: {e}")
            raise

    @staticmethod
    def __user_is_allowed_to_manage_container(user_id: int) -> bool:
        """
        Checks if the given user ID is allowed to manage a container.

        Args:
            user_id (int): The ID of the user to check.

        Returns:
            bool: True if the user is allowed to manage containers, False otherwise.
        """
        return (
                user_id in settings.access_control.allowed_admins_ids
                and session_manager.is_authenticated(user_id)
        )

    def managing_container(
            self,
            user_id: int,
            container_id: Union[str, int],
            action: Literal["start", "stop", "restart", "rename"],
            **kwargs,
    ):
        """
        Manages a Docker container based on the given action.

        Args:
            user_id (int): The ID of the user managing the container.
            container_id (Union[str, int]): The ID of the container to manage.
            action (Literal['start', 'stop', 'restart', 'rename']): The action to perform on the container.
            **kwargs: Additional keyword arguments depending on the action.

        Actions:
            - start: Starts the container.
            - stop: Stops the container.
            - restart: Restarts the container.
            - rename: Renames the container.

        Returns:
            None

        Raises:
            ValueError: If the action is invalid.
        """
        actions = {
            "start": self.__start_container,
            "stop": self.__stop_container,
            "restart": self.__restart_container,
            "rename": lambda x, y, **z: self.__rename_container(
                x, y, new_container_name=z.get("new_container_name")
            ),
        }
        if action in actions:
            bot_logger.info(
                f"User {user_id} is managing container {container_id} with action {action}"
            )
            if action == "rename":
                actions[action](user_id, container_id, **kwargs)
            else:
                actions[action](user_id, container_id)
        else:
            raise ValueError(f"Invalid action: {action}")
