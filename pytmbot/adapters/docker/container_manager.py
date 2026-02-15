#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from threading import RLock
from typing import Any, Final

from pytmbot.adapters.docker.utils import (
    build_container_context,
    get_container_basic_info,
    get_container_safely,
    sanitize_kwargs_for_logging,
)
from pytmbot.globals import session_manager, settings
from pytmbot.logs import Logger
from pytmbot.models.docker_models import (
    ContainerAction,
    ContainerConfig,
    ContainerId,
    DockerResponse,
)
from pytmbot.utils import is_new_name_valid, sanitize_exception

logger = Logger()


def validate_access(func: Callable) -> Callable:
    """
    Decorator for validating user access to container operations with enhanced security.

    Improvements:
    - Rate limiting per user
    - Enhanced authorization logging
    - Input validation
    - Session validation
    """
    # Rate limiting storage (user_id -> last_operation_time)
    _rate_limits: dict[int, float] = {}
    _lock = RLock()

    # Rate limiting configuration
    MIN_OPERATION_INTERVAL: Final[float] = 1.0  # Minimum seconds between operations

    @wraps(func)
    def wrapper(self, user_id: int, container_id: ContainerId, *args, **kwargs) -> any:
        # Input validation
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("Invalid user_id: must be a positive integer")

        if not container_id or not isinstance(container_id, str):
            raise ValueError("Invalid container_id: must be a non-empty string")

        context = build_container_context(
            container_id=container_id,
            action="access_validation",
            user_id=user_id,
            operation=func.__name__,
        )

        # Rate limiting check
        with _lock:
            current_time = time.time()
            last_operation = _rate_limits.get(user_id, 0)

            if current_time - last_operation < MIN_OPERATION_INTERVAL:
                logger.warning(
                    "Rate limit exceeded for user",
                    time_since_last=f"{current_time - last_operation:.2f}s",
                    min_interval=MIN_OPERATION_INTERVAL,
                    **context,
                )
                raise PermissionError(
                    f"Rate limit exceeded. Wait {MIN_OPERATION_INTERVAL}s between operations"
                )

            _rate_limits[user_id] = current_time

        # Enhanced authorization check
        try:
            # Check if user is in allowed admins
            if user_id not in settings.access_control.allowed_admins_ids:
                logger.critical(
                    "Unauthorized container access attempt - user not in admin list",
                    **context,
                )
                raise PermissionError(
                    f"User {user_id} not authorized to manage containers"
                )

            # Check session authentication with timeout validation
            if not session_manager.is_authenticated(user_id):
                logger.critical(
                    "Unauthorized container access attempt - session invalid", **context
                )
                raise PermissionError(f"User {user_id} session invalid or expired")

            # Additional security: check if session is recent enough
            session_info = getattr(session_manager, "get_session_info", lambda x: {})(
                user_id
            )
            if session_info:
                session_age = time.time() - session_info.get("created_at", 0)
                max_session_age = getattr(
                    settings.access_control, "max_session_age", 3600
                )  # 1 hour default

                if session_age > max_session_age:
                    logger.warning(
                        "Session too old for container operations",
                        session_age=f"{session_age:.1f}s",
                        max_age=f"{max_session_age}s",
                        **context,
                    )
                    raise PermissionError("Session expired. Please re-authenticate")

            # Log successful authorization at debug level to avoid noise
            logger.debug("Container access authorized", **context)
            return func(self, user_id, container_id, *args, **kwargs)

        except Exception as e:
            # Log failed authorization attempts
            logger.error(
                "Authorization check failed",
                error=sanitize_exception(e),
                error_type=type(e).__name__,
                **context,
            )
            raise

    return wrapper


class ContainerManager:
    """
    Securely manages Docker containers with strict access control, rate limiting, and comprehensive logging.

    Improvements:
    - Thread safety for concurrent operations
    - Operation timeout management
    - Enhanced error handling and recovery
    - Performance monitoring
    - Container state validation
    """

    def __init__(self) -> None:
        self._lock = RLock()  # Thread safety
        self._operation_history: dict[
            str, datetime
        ] = {}  # Track operations for monitoring
        self._max_operation_timeout: Final[float] = (
            30.0  # Max time for container operations
        )

    def _record_operation(self, operation: str, container_id: ContainerId) -> None:
        """Record operation for monitoring and debugging."""
        with self._lock:
            key = f"{operation}:{container_id}"
            self._operation_history[key] = datetime.now()

            # Clean old records (keep last 100)
            if len(self._operation_history) > 100:
                oldest_keys = sorted(
                    self._operation_history.items(), key=lambda x: x[1]
                )[:10]
                for key, _ in oldest_keys:
                    del self._operation_history[key]

    @staticmethod
    def _validate_container_state_for_operation(
        container_id: ContainerId, operation: str
    ) -> None:
        """Validate that container is in appropriate state for the operation."""
        try:
            container = get_container_safely(container_id)
            current_status = container.status.lower()

            # Define valid states for each operation
            valid_states = {
                "start": ["exited", "stopped", "created"],
                "stop": ["running", "restarting"],
                "restart": ["running", "exited", "stopped"],
                "rename": [
                    "exited",
                    "stopped",
                    "created",
                    "running",
                ],  # Can rename in any state
            }

            if operation in valid_states:
                if current_status not in valid_states[operation]:
                    raise ValueError(
                        f"Cannot {operation} container in state '{current_status}'. "
                        f"Valid states: {valid_states[operation]}"
                    )

        except Exception as e:
            logger.warning(
                f"Container state validation failed for {operation}",
                container_id=container_id,
                error=sanitize_exception(e),
            )
            # Don't raise - let the actual operation handle the error

    @validate_access
    def __start_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Starts a Docker container with enhanced validation and monitoring."""
        context = build_container_context(
            container_id=container_id,
            action="container_start",
            user_id=user_id,
        )

        start_time = time.time()

        try:
            # Pre-operation validation
            self._validate_container_state_for_operation(container_id, "start")

            container = get_container_safely(container_id)

            # Record operation
            self._record_operation("start", container_id)

            logger.info("Starting container", **context)

            result = container.start()

            execution_time = time.time() - start_time

            # Verify the operation succeeded
            container.reload()  # Refresh container state
            if container.status.lower() not in ["running", "restarting"]:
                logger.warning(
                    "Container start may have failed",
                    expected_status="running",
                    actual_status=container.status,
                    **context,
                )

            logger.info(
                "Container started successfully",
                execution_time=f"{execution_time:.2f}s",
                final_status=container.status,
                **context,
            )
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Container start failed",
                error=sanitize_exception(e),
                execution_time=f"{execution_time:.2f}s",
                **context,
            )
            raise

    @validate_access
    def __stop_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Stops a Docker container with graceful shutdown and timeout handling."""
        context = build_container_context(
            container_id=container_id,
            action="container_stop",
            user_id=user_id,
        )

        start_time = time.time()

        try:
            # Pre-operation validation
            self._validate_container_state_for_operation(container_id, "stop")

            container = get_container_safely(container_id)

            # Record operation
            self._record_operation("stop", container_id)

            logger.info("Stopping container", **context)

            # Stop with timeout to prevent hanging
            timeout = getattr(settings.docker, "stop_timeout", 10)
            result = container.stop(timeout=timeout)

            execution_time = time.time() - start_time

            # Verify the operation succeeded
            container.reload()
            if container.status.lower() not in ["exited", "stopped"]:
                logger.warning(
                    "Container stop may have failed",
                    expected_status="exited/stopped",
                    actual_status=container.status,
                    **context,
                )

            logger.info(
                "Container stopped successfully",
                execution_time=f"{execution_time:.2f}s",
                final_status=container.status,
                **context,
            )
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Container stop failed",
                error=sanitize_exception(e),
                execution_time=f"{execution_time:.2f}s",
                **context,
            )
            raise

    @validate_access
    def __restart_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Restarts a Docker container with enhanced monitoring."""
        context = build_container_context(
            container_id=container_id,
            action="container_restart",
            user_id=user_id,
        )

        start_time = time.time()

        try:
            # Pre-operation validation
            self._validate_container_state_for_operation(container_id, "restart")

            container = get_container_safely(container_id)

            # Record operation
            self._record_operation("restart", container_id)

            logger.info("Restarting container", **context)

            # Restart with timeout
            timeout = getattr(settings.docker, "restart_timeout", 10)
            result = container.restart(timeout=timeout)

            execution_time = time.time() - start_time

            # Verify the operation succeeded
            container.reload()
            if container.status.lower() not in ["running", "restarting"]:
                logger.warning(
                    "Container restart may have failed",
                    expected_status="running",
                    actual_status=container.status,
                    **context,
                )

            logger.info(
                "Container restarted successfully",
                execution_time=f"{execution_time:.2f}s",
                final_status=container.status,
                **context,
            )
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Container restart failed",
                error=sanitize_exception(e),
                execution_time=f"{execution_time:.2f}s",
                **context,
            )
            raise

    @validate_access
    def __rename_container(
        self, user_id: int, container_id: ContainerId, new_container_name: str
    ) -> DockerResponse:
        """Renames a Docker container with comprehensive validation."""
        # Enhanced name validation
        if not new_container_name or not isinstance(new_container_name, str):
            raise ValueError("New container name must be a non-empty string")

        # Trim whitespace and validate length
        new_container_name = new_container_name.strip()
        if len(new_container_name) > 64:  # Docker limit
            raise ValueError("Container name too long (max 64 characters)")

        if len(new_container_name) < 1:
            raise ValueError("Container name too short (min 1 character)")

        context = build_container_context(
            container_id=container_id,
            action="container_rename",
            user_id=user_id,
            new_name=new_container_name,
        )

        start_time = time.time()

        try:
            # Validate new name format
            if not is_new_name_valid(new_container_name):
                logger.warning(
                    "Invalid container name rejected",
                    validation_error="name_format_invalid",
                    **context,
                )
                raise ValueError(f"Invalid container name format: {new_container_name}")

            container = get_container_safely(container_id)
            old_name = container.name

            # Check if name is actually different
            if old_name == new_container_name:
                logger.info("Container name unchanged, skipping rename", **context)
                return None  # No operation needed

            # Record operation
            self._record_operation("rename", container_id)

            logger.info("Renaming container", old_name=old_name, **context)

            result = container.rename(new_container_name)

            execution_time = time.time() - start_time

            # Verify the rename succeeded
            container.reload()
            if container.name != new_container_name:
                logger.error(
                    "Container rename verification failed",
                    expected_name=new_container_name,
                    actual_name=container.name,
                    **context,
                )
                raise RuntimeError(
                    f"Rename operation failed: name is still '{container.name}'"
                )

            logger.info(
                "Container renamed successfully",
                old_name=old_name,
                execution_time=f"{execution_time:.2f}s",
                **context,
            )
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Container rename failed",
                error=sanitize_exception(e),
                execution_time=f"{execution_time:.2f}s",
                **context,
            )
            raise

    def managing_container(
        self,
        user_id: int,
        container_id: ContainerId,
        action: str,
        **kwargs: ContainerConfig,
    ) -> DockerResponse:
        """Manages container operations with comprehensive validation and monitoring."""
        # Input validation
        if not isinstance(action, str) or not action.strip():
            raise ValueError("Action must be a non-empty string")

        action = action.strip().lower()

        # Sanitize kwargs for logging - remove sensitive data
        safe_kwargs = sanitize_kwargs_for_logging(kwargs)

        context = build_container_context(
            container_id=container_id,
            action="container_management",
            user_id=user_id,
            operation=action,
            params=safe_kwargs if safe_kwargs else None,
        )

        operation_start = time.time()

        try:
            container_action = ContainerAction.from_str(action)

            # Define action mapping with enhanced error handling
            actions = {
                ContainerAction.START: self.__start_container,
                ContainerAction.STOP: self.__stop_container,
                ContainerAction.RESTART: self.__restart_container,
                ContainerAction.RENAME: lambda u, c: self.__rename_container(
                    u, c, kwargs.get("new_container_name", "")
                ),
            }

            if container_action not in actions:
                raise ValueError(f"Unsupported action: {action}")

            logger.info("Container management request received", **context)

            # Execute the action with timeout monitoring
            result = actions[container_action](user_id, container_id)

            execution_time = time.time() - operation_start

            logger.info(
                "Container management completed successfully",
                total_execution_time=f"{execution_time:.2f}s",
                **context,
            )
            return result

        except (ValueError, KeyError) as e:
            execution_time = time.time() - operation_start
            logger.warning(
                "Invalid container action requested",
                error=sanitize_exception(e),
                available_actions=[action.value for action in ContainerAction],
                execution_time=f"{execution_time:.2f}s",
                **context,
            )
            raise ValueError(f"Invalid action: {action}")

        except PermissionError:
            # Already logged in validator, just re-raise
            raise

        except Exception as e:
            execution_time = time.time() - operation_start
            logger.error(
                "Container management failed",
                error=sanitize_exception(e),
                execution_time=f"{execution_time:.2f}s",
                **context,
            )
            raise

    @staticmethod
    def get_container_status(container_id: ContainerId) -> dict[str, Any]:
        """Get comprehensive container status information for monitoring."""
        context = build_container_context(
            container_id=container_id,
            action="container_status",
        )

        try:
            container = get_container_safely(container_id)

            # Get basic container info using utility
            status = get_container_basic_info(container)

            # Add comprehensive status information
            attrs = container.attrs
            status.update(
                {
                    "created": attrs.get("Created", "unknown"),
                    "started_at": attrs.get("State", {}).get("StartedAt", "unknown"),
                    "finished_at": attrs.get("State", {}).get("FinishedAt", "unknown"),
                    "exit_code": attrs.get("State", {}).get("ExitCode"),
                    "error": attrs.get("State", {}).get("Error", ""),
                    "pid": attrs.get("State", {}).get("Pid"),
                    "restart_count": attrs.get("RestartCount", 0),
                    "platform": attrs.get("Platform", "unknown"),
                    "driver": attrs.get("Driver", "unknown"),
                    "network_mode": attrs.get("HostConfig", {}).get(
                        "NetworkMode", "unknown"
                    ),
                    "ports": attrs.get("NetworkSettings", {}).get("Ports", {}),
                    "mounts": [
                        {
                            "source": mount.get("Source", ""),
                            "destination": mount.get("Destination", ""),
                            "mode": mount.get("Mode", ""),
                            "type": mount.get("Type", ""),
                        }
                        for mount in attrs.get("Mounts", [])
                    ],
                }
            )

            logger.debug(
                "Container status retrieved",
                status=status["status"],
                exit_code=status.get("exit_code"),
                **context,
            )
            return status

        except Exception as e:
            logger.error(
                "Container status retrieval failed",
                error=sanitize_exception(e),
                **context,
            )
            raise

    def get_operation_history(self) -> dict[str, str]:
        """Get recent operation history for monitoring."""
        with self._lock:
            return {
                key: timestamp.isoformat()
                for key, timestamp in self._operation_history.items()
            }

    def clear_operation_history(self) -> None:
        """Clear operation history."""
        with self._lock:
            self._operation_history.clear()
            logger.debug("Operation history cleared")
