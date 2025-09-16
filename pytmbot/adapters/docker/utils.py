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
from functools import wraps, lru_cache
from time import sleep
from typing import Dict, Any, Optional, Final, TypeAlias, List
from threading import RLock

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

# Module constants for better maintainability
MAX_STATE_CHECK_ATTEMPTS: Final[int] = 5
DEFAULT_STATE_CHECK_INTERVAL: Final[float] = 1.5
MIN_STATE_CHECK_INTERVAL: Final[float] = 0.5
MAX_STATE_CHECK_INTERVAL: Final[float] = 5.0
OPERATION_TIMEOUT: Final[float] = 30.0


class ContainerState(str, Enum):
    """Enhanced container state enumeration with validation."""

    RUNNING = "running"
    EXITED = "exited"
    STOPPED = "stopped"
    CREATED = "created"
    RESTARTING = "restarting"
    REMOVING = "removing"
    PAUSED = "paused"
    DEAD = "dead"

    @classmethod
    def from_str(cls, value: str) -> "ContainerState":
        """Convert string to ContainerState with enhanced error handling."""
        if not value or not isinstance(value, str):
            raise ValueError("State value must be a non-empty string")

        normalized_value = value.lower().strip()
        try:
            return cls(normalized_value)
        except ValueError:
            valid_states = [state.value for state in cls]
            raise ValueError(
                f"Invalid container state: '{value}'. Valid states: {valid_states}"
            ) from None

    @property
    def is_active(self) -> bool:
        """Check if container state indicates active/running state."""
        return self in {self.RUNNING, self.RESTARTING}

    @property
    def is_stopped(self) -> bool:
        """Check if container state indicates stopped state."""
        return self in {self.EXITED, self.STOPPED, self.CREATED}

    @property
    def is_transitional(self) -> bool:
        """Check if container state indicates transitional state."""
        return self in {self.RESTARTING, self.REMOVING}


@dataclass(frozen=True, slots=True)
class StateCheckConfig:
    """Configuration for container state checking with validation."""

    max_attempts: int = MAX_STATE_CHECK_ATTEMPTS
    interval: float = DEFAULT_STATE_CHECK_INTERVAL

    def __post_init__(self):
        """Validate configuration parameters."""
        if not isinstance(self.max_attempts, int) or self.max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")

        if not isinstance(self.interval, (int, float)) or self.interval <= 0:
            raise ValueError("interval must be a positive number")

        # Clamp interval to reasonable bounds
        if not (MIN_STATE_CHECK_INTERVAL <= self.interval <= MAX_STATE_CHECK_INTERVAL):
            object.__setattr__(
                self,
                "interval",
                max(
                    MIN_STATE_CHECK_INTERVAL,
                    min(self.interval, MAX_STATE_CHECK_INTERVAL),
                ),
            )


def check_container_state(
    container_name: ContainerName,
    target_state: str = ContainerState.RUNNING,
    config: StateCheckConfig = StateCheckConfig(),
) -> Optional[ContainerState]:
    """
    Checks if container reaches target state within configured attempts with enhanced monitoring.

    Args:
        container_name: Container identifier
        target_state: Desired container state
        config: Check configuration parameters

    Returns:
        Final container state or None on error

    Raises:
        ValueError: If target state is invalid or container_name is empty
        DockerOperationException: If Docker operations fail
    """
    # Input validation
    if not container_name or not isinstance(container_name, str):
        raise ValueError("container_name must be a non-empty string")

    try:
        target = ContainerState.from_str(target_state)
        containers_state = ContainersState()

        # Validate target state exists in containers state model
        if target.value not in containers_state.__dict__.values():
            raise ValueError(f"Invalid target state: {target}")

        operation_start = time.time()
        current_state = None

        for attempt in range(1, config.max_attempts + 1):
            attempt_start = time.time()

            log_context = {
                "container": container_name,
                "target": target.value,
                "attempt": attempt,
                "max_attempts": config.max_attempts,
                "operation_time": f"{time.time() - operation_start:.2f}s",
            }

            logger.debug(
                f"Checking state (attempt {attempt}/{config.max_attempts})",
                **log_context,
            )

            try:
                current_state_str = get_container_state(container_name)
                if current_state_str is None:
                    logger.error("Failed to get container state", **log_context)
                    return None

                current_state = ContainerState.from_str(current_state_str)
                attempt_time = time.time() - attempt_start

                log_context.update(
                    {
                        "state": current_state.value,
                        "attempt_time": f"{attempt_time:.3f}s",
                    }
                )

                if current_state == target:
                    total_time = time.time() - operation_start
                    logger.info(
                        "Target state reached",
                        total_time=f"{total_time:.2f}s",
                        **log_context,
                    )
                    return current_state

                # Check if we're in a transitional state that might lead to target
                if current_state.is_transitional and target.is_active:
                    logger.debug(
                        f"Container in transitional state {current_state.value}, continuing to wait",
                        **log_context,
                    )
                elif current_state.is_stopped and target.is_active:
                    logger.warning(
                        f"Container stopped unexpectedly while waiting for {target.value}",
                        **log_context,
                    )

                if attempt < config.max_attempts:
                    logger.debug(
                        f"State mismatch: {current_state.value}, retrying in {config.interval}s",
                        **log_context,
                    )
                    sleep(config.interval)

            except Exception as e:
                attempt_time = time.time() - attempt_start
                logger.error(
                    "State check failed",
                    error=sanitize_exception(e),
                    error_type=type(e).__name__,
                    attempt_time=f"{attempt_time:.3f}s",
                    **log_context,
                )
                # Don't return immediately, try remaining attempts
                if attempt < config.max_attempts:
                    sleep(config.interval)
                else:
                    return None

        total_time = time.time() - operation_start
        logger.warning(
            "Failed to reach target state",
            container=container_name,
            target=target.value,
            final_state=current_state.value if current_state else "unknown",
            attempts=config.max_attempts,
            total_time=f"{total_time:.2f}s",
        )
        return current_state

    except ValueError as e:
        logger.error(
            "Invalid target state",
            container=container_name,
            state=target_state,
            error=str(e),
        )
        raise
    except Exception as e:
        logger.error(
            "Unexpected error during state check",
            container=container_name,
            target_state=target_state,
            error=sanitize_exception(e),
        )
        raise


def with_operation_logging(operation_name: str, slow_threshold: float = 1.0):
    """
    Enhanced decorator for logging Docker operations with timing, context, and performance monitoring.

    Args:
        operation_name: Name of the Docker operation being performed
        slow_threshold: Threshold in seconds to consider operation slow
    """
    if not operation_name or not isinstance(operation_name, str):
        raise ValueError("operation_name must be a non-empty string")

    if slow_threshold <= 0:
        raise ValueError("slow_threshold must be positive")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            operation_id = f"{operation_name}_{int(start_time * 1000) % 10000}"

            # Build enhanced base context
            context = {
                "action": f"docker_{operation_name}",
                "operation": operation_name,
                "operation_id": operation_id,
                "start_time": datetime.now().isoformat(),
            }

            # Add function arguments context (sanitized)
            if args:
                context["args_count"] = len(args)
                # Add first argument if it's a string (usually container_id)
                if args and isinstance(args[0], str):
                    context["container_id"] = args[0][:12]  # Truncate long IDs

            if kwargs:
                # Sanitize kwargs using utility
                safe_kwargs = sanitize_kwargs_for_logging(kwargs)
                if safe_kwargs:
                    context["params"] = safe_kwargs

            # Log operation start for slow operations
            if getattr(settings.docker, "debug_docker_client", False):
                logger.debug(f"Starting Docker operation: {operation_name}", **context)

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
                elif isinstance(result, str):
                    context["result_length"] = len(result)

                # Enhanced logging based on execution time and settings
                if execution_time > slow_threshold:
                    # Slow operations should be logged at warning level
                    logger.warning(
                        f"Docker operation completed (SLOW): {operation_name}",
                        **context,
                    )
                elif execution_time > slow_threshold / 2:
                    # Moderately slow operations at info level
                    logger.info(
                        f"Docker operation completed: {operation_name}",
                        **context,
                    )
                elif getattr(settings.docker, "debug_docker_client", False):
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
                        "error_type": type(e).__name__,
                    }
                )

                logger.error(f"Docker operation failed: {operation_name}", **context)
                raise

        return wrapper

    return decorator


# Thread-safe cache for container states
_state_cache: Dict[str, tuple[str, float]] = {}
_state_cache_lock = RLock()
_STATE_CACHE_TTL = 2.0  # Cache container states for 2 seconds


@with_operation_logging("get_container_state", slow_threshold=0.5)
def get_container_state(container_id: str) -> Optional[str]:
    """
    Retrieves the status of a Docker container with caching and enhanced error handling.

    Args:
        container_id: The ID of the container.

    Returns:
        Container status string or None if not found.

    Raises:
        ValueError: If container_id is invalid
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    container_id = container_id.strip()

    # Check cache first
    with _state_cache_lock:
        if container_id in _state_cache:
            cached_state, timestamp = _state_cache[container_id]
            if time.time() - timestamp < _STATE_CACHE_TTL:
                return cached_state

    context = build_container_context(
        container_id=container_id,
        action="container_state_check",
    )

    try:
        container = get_container_safely(container_id)
        status = container.status

        # Cache the result
        with _state_cache_lock:
            _state_cache[container_id] = (status, time.time())

            # Clean old cache entries
            if len(_state_cache) > 100:
                current_time = time.time()
                expired_keys = [
                    key
                    for key, (_, ts) in _state_cache.items()
                    if current_time - ts >= _STATE_CACHE_TTL
                ]
                for key in expired_keys:
                    del _state_cache[key]

        logger.debug("Container state retrieved", status=status, **context)
        return status

    except ContainerNotFoundError:
        logger.debug("Container not found for state check", **context)
        return None

    except Exception as e:
        logger.error(
            "Failed to get container state",
            error=sanitize_exception(e),
            error_type=type(e).__name__,
            **context,
        )
        return None


def get_container_safely(container_id: str) -> Container:
    """
    Safely retrieves a container by ID with uniform error handling and validation.

    Args:
        container_id: Container ID

    Returns:
        Container: Container object

    Raises:
        ValueError: If container_id is invalid
        ContainerNotFoundError: If container is not found
        DockerOperationException: For other Docker errors
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    container_id = container_id.strip()

    context = {
        "action": "container_retrieval",
        "container_id": container_id,
        "container_id_length": len(container_id),
    }

    start_time = time.time()

    try:
        with DockerAdapter() as adapter:
            container = adapter.containers.get(container_id)

            execution_time = time.time() - start_time

            logger.debug(
                "Container retrieved successfully",
                execution_time=f"{execution_time:.3f}s",
                container_name=getattr(container, "name", "unknown"),
                container_status=getattr(container, "status", "unknown"),
                **context,
            )
            return container

    except NotFound:
        execution_time = time.time() - start_time
        logger.warning(
            "Container not found", execution_time=f"{execution_time:.3f}s", **context
        )
        raise ContainerNotFoundError(
            ErrorContext(
                message=f"Container not found: {container_id}",
                error_code="DOCKER_001",
                metadata={"container_id": container_id, "search_time": execution_time},
            )
        )
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(
            "Container retrieval failed",
            error=sanitize_exception(e),
            error_type=type(e).__name__,
            execution_time=f"{execution_time:.3f}s",
            **context,
        )
        raise DockerOperationException(
            ErrorContext(
                message=f"Failed to retrieve container: {container_id}",
                error_code="DOCKER_002",
                metadata={
                    "container_id": container_id,
                    "exception": str(e),
                    "execution_time": execution_time,
                },
            )
        )


def sanitize_kwargs_for_logging(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhanced sanitization of kwargs for safe logging by removing sensitive information.

    Args:
        kwargs: Dictionary of parameters

    Returns:
        Dict: Sanitized parameter dictionary
    """
    if not isinstance(kwargs, dict):
        return {}

    # Define comprehensive sensitive keys
    sensitive_keys = {
        "password",
        "passwd",
        "pass",
        "pwd",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "secret",
        "api_secret",
        "client_secret",
        "key",
        "private_key",
        "public_key",
        "api_key",
        "auth",
        "authorization",
        "credential",
        "credentials",
        "cert",
        "certificate",
        "ca_cert",
        "session",
        "session_id",
        "cookie",
    }

    safe_kwargs = {}
    for key, value in kwargs.items():
        key_lower = key.lower()

        # Check for sensitive keys
        if any(sensitive in key_lower for sensitive in sensitive_keys):
            safe_kwargs[key] = "[REDACTED]"
        elif isinstance(value, str):
            # Truncate very long strings
            if len(value) > 200:
                safe_kwargs[key] = f"{value[:100]}...[TRUNCATED:{len(value)} chars]"
            # Redact strings that look like tokens/keys
            elif (
                len(value) > 20
                and any(char in value for char in "abcdefABCDEF0123456789")
                and len(set(value)) > 10
            ):  # High entropy strings
                safe_kwargs[key] = f"[REDACTED:{len(value)} chars]"
            else:
                safe_kwargs[key] = value
        elif isinstance(value, (list, tuple)):
            # Limit collection size in logs
            if len(value) > 10:
                safe_kwargs[key] = f"[LIST:{len(value)} items]"
            else:
                safe_kwargs[key] = value
        elif isinstance(value, dict):
            # Recursively sanitize nested dicts
            if len(value) > 20:
                safe_kwargs[key] = f"[DICT:{len(value)} keys]"
            else:
                safe_kwargs[key] = sanitize_kwargs_for_logging(value)
        else:
            safe_kwargs[key] = value

    return safe_kwargs


def build_container_context(
    container_id: str, action: str, **extra_context
) -> Dict[str, Any]:
    """
    Creates a standard context for logging container operations with validation.

    Args:
        container_id: Container ID
        action: Action name
        **extra_context: Additional context fields

    Returns:
        Dict: Logging context

    Raises:
        ValueError: If required parameters are invalid
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    if not action or not isinstance(action, str):
        raise ValueError("action must be a non-empty string")

    context = {
        "action": action.strip(),
        "container_id": container_id.strip(),
        "timestamp": datetime.now().isoformat(),
    }

    # Sanitize extra context
    if extra_context:
        sanitized_extra = sanitize_kwargs_for_logging(extra_context)
        context.update(sanitized_extra)

    return context


@lru_cache(maxsize=128)
def get_container_basic_info(container: Container) -> Dict[str, Any]:
    """
    Extracts basic container information with caching and enhanced data.

    Args:
        container: Container object

    Returns:
        Dict: Enhanced container information

    Raises:
        ValueError: If container is None
    """
    if container is None:
        raise ValueError("Container object cannot be None")

    try:
        # Get image tags safely
        image_tags = []
        if hasattr(container, "image") and container.image:
            image_tags = getattr(container.image, "tags", [])

        image_name = image_tags[0] if image_tags else "unknown"

        basic_info = {
            "id": container.id,
            "short_id": container.short_id,
            "name": container.name.lstrip("/"),  # Remove leading slash
            "status": container.status,
            "image": image_name,
            "image_id": getattr(container.image, "short_id", "unknown")
            if hasattr(container, "image")
            else "unknown",
            "created": getattr(container.attrs, "get", lambda k, d: d)(
                "Created", "unknown"
            ),
            "ports": getattr(container, "ports", {}),
            "labels": getattr(container, "labels", {}),
        }

        # Add state information if available
        if hasattr(container, "attrs") and container.attrs:
            state = container.attrs.get("State", {})
            basic_info.update(
                {
                    "exit_code": state.get("ExitCode"),
                    "pid": state.get("Pid"),
                    "started_at": state.get("StartedAt"),
                    "finished_at": state.get("FinishedAt"),
                }
            )

        return basic_info

    except Exception as e:
        logger.warning(
            "Failed to extract complete container basic info",
            container_id=getattr(container, "id", "unknown"),
            error=sanitize_exception(e),
        )
        # Return minimal info on error
        return {
            "id": getattr(container, "id", "unknown"),
            "short_id": getattr(container, "short_id", "unknown"),
            "name": getattr(container, "name", "unknown"),
            "status": getattr(container, "status", "unknown"),
            "image": "unknown",
        }


def clear_state_cache() -> None:
    """Clear the container state cache."""
    global _state_cache
    with _state_cache_lock:
        _state_cache.clear()
    logger.debug("Container state cache cleared")


def get_cache_stats() -> Dict[str, Any]:
    """Get comprehensive cache statistics for monitoring."""
    with _state_cache_lock:
        cache_size = len(_state_cache)

        # Calculate cache hit ratio (approximate)
        if cache_size > 0:
            current_time = time.time()
            fresh_entries = sum(
                1
                for _, (_, timestamp) in _state_cache.items()
                if current_time - timestamp < _STATE_CACHE_TTL
            )
        else:
            fresh_entries = 0

    return {
        "state_cache_size": cache_size,
        "state_cache_fresh_entries": fresh_entries,
        "state_cache_ttl": _STATE_CACHE_TTL,
        "basic_info_cache": get_container_basic_info.cache_info()._asdict(),
    }


def validate_container_operation_params(
    container_id: str, operation: str, **kwargs
) -> Dict[str, Any]:
    """
    Validate parameters for container operations.

    Args:
        container_id: Container ID to validate
        operation: Operation name
        **kwargs: Additional operation-specific parameters

    Returns:
        Dict with validated parameters

    Raises:
        ValueError: If parameters are invalid
    """
    if not container_id or not isinstance(container_id, str):
        raise ValueError("container_id must be a non-empty string")

    if not operation or not isinstance(operation, str):
        raise ValueError("operation must be a non-empty string")

    container_id = container_id.strip()
    operation = operation.strip().lower()

    # Basic ID format validation
    if len(container_id) < 4:
        raise ValueError("container_id too short (minimum 4 characters)")

    if len(container_id) > 64:
        raise ValueError("container_id too long (maximum 64 characters)")

    # Operation-specific validation
    validated_params = {
        "container_id": container_id,
        "operation": operation,
    }

    if operation == "rename":
        new_name = kwargs.get("new_container_name", "").strip()
        if not new_name:
            raise ValueError("new_container_name required for rename operation")
        if len(new_name) > 64:
            raise ValueError("new_container_name too long (maximum 64 characters)")
        validated_params["new_container_name"] = new_name

    elif operation in ["stop", "restart"]:
        timeout = kwargs.get("timeout", 10)
        if not isinstance(timeout, (int, float)) or timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        if timeout > 300:  # 5 minutes max
            raise ValueError("timeout too large (maximum 300 seconds)")
        validated_params["timeout"] = timeout

    return validated_params


class ContainerOperationTracker:
    """Track container operations for monitoring and rate limiting."""

    def __init__(self):
        self._operations: Dict[str, List[float]] = {}
        self._lock = RLock()
        self._max_history = 100
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()

    def record_operation(self, container_id: str, operation: str) -> None:
        """Record a container operation."""
        with self._lock:
            key = f"{container_id}:{operation}"
            current_time = time.time()

            if key not in self._operations:
                self._operations[key] = []

            self._operations[key].append(current_time)

            # Limit history size
            if len(self._operations[key]) > self._max_history:
                self._operations[key] = self._operations[key][-self._max_history :]

            # Periodic cleanup
            if current_time - self._last_cleanup > self._cleanup_interval:
                self._cleanup_old_operations()
                self._last_cleanup = current_time

    def get_recent_operations(
        self, container_id: str, since_seconds: float = 3600
    ) -> List[Dict]:
        """Get recent operations for a container."""
        with self._lock:
            current_time = time.time()
            cutoff_time = current_time - since_seconds

            recent_ops = []
            for key, timestamps in self._operations.items():
                if key.startswith(f"{container_id}:"):
                    operation = key.split(":", 1)[1]
                    recent_timestamps = [ts for ts in timestamps if ts > cutoff_time]

                    if recent_timestamps:
                        recent_ops.append(
                            {
                                "operation": operation,
                                "count": len(recent_timestamps),
                                "last_time": max(recent_timestamps),
                                "first_time": min(recent_timestamps),
                            }
                        )

            return sorted(recent_ops, key=lambda x: x["last_time"], reverse=True)

    def _cleanup_old_operations(self) -> None:
        """Remove old operation records."""
        current_time = time.time()
        cutoff_time = current_time - 86400  # 24 hours

        for key in list(self._operations.keys()):
            self._operations[key] = [
                ts for ts in self._operations[key] if ts > cutoff_time
            ]

            # Remove empty entries
            if not self._operations[key]:
                del self._operations[key]

    def clear(self) -> None:
        """Clear all operation history."""
        with self._lock:
            self._operations.clear()


# Global operation tracker
_operation_tracker = ContainerOperationTracker()


def record_container_operation(container_id: str, operation: str) -> None:
    """Record a container operation for monitoring."""
    _operation_tracker.record_operation(container_id, operation)


def get_container_operation_history(
    container_id: str, since_seconds: float = 3600
) -> List[Dict]:
    """Get recent operation history for a container."""
    return _operation_tracker.get_recent_operations(container_id, since_seconds)
