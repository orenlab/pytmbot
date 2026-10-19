#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from threading import Lock, RLock
from typing import Final, NoReturn

from docker.errors import NotFound
from docker.models.containers import Container

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.utils import (
    build_container_context,
    docker_unavailable_as_connection_error,
    get_container_safely,
    invalidate_container_state_cache,
    sanitize_kwargs_for_logging,
    validate_container_reference,
)
from pytmbot.exceptions import (
    ContainerActionInProgressError,
    ContainerException,
    ContainerStateConflictError,
    ErrorContext,
)
from pytmbot.globals import get_session_manager, settings
from pytmbot.logs import Logger
from pytmbot.models.docker_models import (
    ContainerAction,
    ContainerId,
    DockerResponse,
)
from pytmbot.utils import is_new_name_valid, sanitize_exception

logger = Logger()
session_manager = get_session_manager()

MIN_OPERATION_INTERVAL_SECONDS: Final[float] = 1.0
RATE_LIMIT_CACHE_TTL_SECONDS: Final[float] = 300.0
MAX_RATE_LIMITED_USERS: Final[int] = 2048
DEFAULT_SESSION_MAX_AGE_SECONDS: Final[int] = 3600
DEFAULT_STOP_TIMEOUT_SECONDS: Final[int] = 10


class _UserRateLimiter:
    """Minimum interval between container actions per user, across all actions."""

    def __init__(
        self, *, min_interval: float, stale_after: float, max_users: int
    ) -> None:
        self._min_interval = min_interval
        self._stale_after = stale_after
        self._max_users = max_users
        self._last_operation: dict[int, float] = {}
        self._lock = RLock()

    @property
    def min_interval(self) -> float:
        return self._min_interval

    def _evict(self, now: float) -> None:
        if len(self._last_operation) <= self._max_users:
            return
        stale_threshold = now - self._stale_after
        for user_id, last_seen in list(self._last_operation.items()):
            if last_seen < stale_threshold:
                self._last_operation.pop(user_id, None)
        while len(self._last_operation) > self._max_users:
            oldest = min(self._last_operation, key=self._last_operation.__getitem__)
            self._last_operation.pop(oldest, None)

    def register(self, user_id: int) -> float | None:
        """Record an operation; return seconds since the last one if too soon."""
        with self._lock:
            now = time.time()
            self._evict(now)
            elapsed = now - self._last_operation.get(user_id, 0.0)
            if elapsed < self._min_interval:
                return elapsed
            self._last_operation[user_id] = now
            return None


class _InFlightActions:
    """Non-blocking per-container lock for lifecycle/rename actions."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active: set[str] = set()

    @contextmanager
    def hold(self, container_key: str, operation: str) -> Iterator[None]:
        with self._lock:
            if container_key in self._active:
                raise ContainerActionInProgressError(
                    ErrorContext(
                        message="Another action on this container is in progress",
                        error_code="DOCKER_014",
                        metadata={
                            "container_id": container_key[:12],
                            "operation": operation,
                        },
                    )
                )
            self._active.add(container_key)
        try:
            yield
        finally:
            with self._lock:
                self._active.discard(container_key)


# Shared by every ContainerManager instance in the process.
_rate_limiter = _UserRateLimiter(
    min_interval=MIN_OPERATION_INTERVAL_SECONDS,
    stale_after=RATE_LIMIT_CACHE_TTL_SECONDS,
    max_users=MAX_RATE_LIMITED_USERS,
)
_in_flight_actions = _InFlightActions()


@dataclass(frozen=True, slots=True)
class _LifecycleSpec:
    """Static description of a start/stop/restart operation."""

    operation: str
    start_event: str
    success_event: str
    fail_event: str
    expected_statuses: frozenset[str]
    conflict_statuses: frozenset[str]
    tolerate_removal: bool = False


# Start is rejected while the container already runs (paused/restarting
# containers are running from Docker's point of view). Stop is rejected unless
# the container runs. Restart is allowed for stopped containers (Docker starts
# them). A stopped ``--rm`` container disappears: that is a successful stop.
_START_SPEC: Final[_LifecycleSpec] = _LifecycleSpec(
    operation="start",
    start_event="docker.containers.container.start",
    success_event="docker.containers.container.start.ok",
    fail_event="docker.containers.container.start.fail",
    expected_statuses=frozenset({"running", "restarting"}),
    conflict_statuses=frozenset({"running", "restarting", "paused", "removing"}),
)
_STOP_SPEC: Final[_LifecycleSpec] = _LifecycleSpec(
    operation="stop",
    start_event="docker.containers.container.stop",
    success_event="docker.containers.container.stop.ok",
    fail_event="docker.containers.container.stop.fail",
    expected_statuses=frozenset({"exited", "dead", "removing"}),
    conflict_statuses=frozenset({"created", "exited", "dead", "removing"}),
    tolerate_removal=True,
)
_RESTART_SPEC: Final[_LifecycleSpec] = _LifecycleSpec(
    operation="restart",
    start_event="docker.containers.restarting.container.start",
    success_event="docker.containers.container.restarted.start",
    fail_event="docker.containers.container.restart.fail",
    expected_statuses=frozenset({"running", "restarting"}),
    conflict_statuses=frozenset({"removing"}),
)


def _deny_access(
    *,
    log_method: Callable[..., object],
    event_name: str,
    message: str,
    context: dict[str, object],
    **details: object,
) -> NoReturn:
    """Log an access denial once and raise a consistent permission error."""
    log_method(event_name, **context, **details)
    raise PermissionError(message)


def _log_action_failure(
    event_name: str, error: Exception, started_at: float, context: dict[str, object]
) -> None:
    """Log a failed action; expected outcomes (conflict, not found...) as warnings."""
    log_method = (
        logger.warning if isinstance(error, ContainerException) else logger.error
    )
    log_method(
        event_name,
        error=sanitize_exception(error),
        error_type=type(error).__name__,
        execution_time=f"{time.time() - started_at:.2f}s",
        **context,
    )


def _check_rate_limit(user_id: int, context: dict[str, object]) -> None:
    elapsed = _rate_limiter.register(user_id)
    if elapsed is None:
        return
    _deny_access(
        log_method=logger.warning,
        event_name="docker.containers.rate.limit.warn",
        message=(
            "Rate limit exceeded. "
            f"Wait {_rate_limiter.min_interval}s between operations"
        ),
        context=context,
        time_since_last=f"{elapsed:.2f}s",
        min_interval=_rate_limiter.min_interval,
    )


def _session_created_at(user_id: int) -> float | None:
    session_info_getter = getattr(session_manager, "get_session_info", None)
    if not callable(session_info_getter):
        return None
    session_info = session_info_getter(user_id)
    if not isinstance(session_info, dict) or not session_info:
        return None
    created_at_raw = session_info.get("created_at", 0)
    return float(created_at_raw) if isinstance(created_at_raw, (int, float)) else 0.0


def _check_authorization(user_id: int, context: dict[str, object]) -> None:
    if user_id not in settings.access_control.allowed_admins_ids:
        _deny_access(
            log_method=logger.critical,
            event_name="docker.containers.unauthorized.container.deny",
            message=f"User {user_id} not authorized to manage containers",
            context=context,
        )

    if not session_manager.is_authenticated(user_id):
        _deny_access(
            log_method=logger.critical,
            event_name="docker.containers.unauthorized.container.deny",
            message=f"User {user_id} session invalid or expired",
            context=context,
        )

    created_at = _session_created_at(user_id)
    if created_at is None:
        return
    session_age = time.time() - created_at
    max_session_age = getattr(
        settings.access_control, "max_session_age", DEFAULT_SESSION_MAX_AGE_SECONDS
    )
    if session_age > max_session_age:
        _deny_access(
            log_method=logger.warning,
            event_name="docker.containers.session.too.warn",
            message="Session expired. Please re-authenticate",
            context=context,
            session_age=f"{session_age:.1f}s",
            max_age=f"{max_session_age}s",
        )


def validate_access(
    func: Callable[..., DockerResponse],
) -> Callable[..., DockerResponse]:
    """
    Validate user access to container operations.

    - Container reference validation (exact name or ID)
    - Rate limiting per user, shared by all container actions
    - Admin, session and session-age checks
    """

    @wraps(func)
    def wrapper(
        self: "ContainerManager",
        user_id: int,
        container_id: ContainerId,
        *args: object,
        **kwargs: object,
    ) -> DockerResponse:
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("Invalid user_id: must be a positive integer")

        container_ref = ContainerManager._normalize_container_id(container_id)
        context = build_container_context(
            container_id=container_ref,
            action="access_validation",
            user_id=user_id,
            operation=func.__name__,
        )

        _check_rate_limit(user_id, context)
        try:
            _check_authorization(user_id, context)
        except (PermissionError, AttributeError, TypeError, ValueError) as e:
            logger.error(
                "docker.containers.authorization.check.fail",
                error=sanitize_exception(e),
                error_type=type(e).__name__,
                **context,
            )
            raise

        logger.debug("docker.containers.container.access.debug", **context)
        return func(self, user_id, container_ref, *args, **kwargs)

    return wrapper


class ContainerManager:
    """
    Manage Docker containers with strict access control and safe targeting.

    - The container is resolved by exact name or ID and the resolved target is
      verified before any action (never acts on a different container).
    - One action at a time per container (non-blocking in-flight lock).
    - Start/stop are rejected with ContainerStateConflictError when they do not
      fit the current state.
    - Operations are bounded by the Docker client's HTTP timeout (stop/restart
      add their own grace period), not by a background thread.
    """

    def __init__(self) -> None:
        self._lock = RLock()  # Thread safety
        self._operation_history: dict[str, datetime] = {}

    @staticmethod
    def _normalize_container_id(container_id: ContainerId) -> str:
        """Validate a container reference (raises InvalidContainerReferenceError)."""
        return validate_container_reference(str(container_id))

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
        container: Container, spec: _LifecycleSpec
    ) -> None:
        """Reject actions that do not fit the container's current state."""
        current_status = str(getattr(container, "status", "") or "").lower()
        if current_status not in spec.conflict_statuses:
            return
        raise ContainerStateConflictError(
            ErrorContext(
                message=f"Cannot {spec.operation} container in state '{current_status}'",
                error_code="DOCKER_013",
                metadata={"operation": spec.operation, "state": current_status},
            ),
            state=current_status,
        )

    @staticmethod
    def _perform_and_verify(
        container: Container,
        spec: _LifecycleSpec,
        execute_operation: Callable[[Container], None],
        context: dict[str, object],
    ) -> str:
        """Run the operation, then confirm the resulting state."""
        try:
            execute_operation(container)
            container.reload()
        except NotFound:
            if not spec.tolerate_removal:
                raise
            return "removed"

        current_status = str(container.status).lower()
        if current_status in spec.expected_statuses:
            return current_status

        logger.error(
            spec.fail_event,
            expected_status="/".join(sorted(spec.expected_statuses)),
            actual_status=current_status,
            **context,
        )
        raise RuntimeError(
            f"{spec.operation.capitalize()} operation failed, "
            f"current status: {current_status}"
        )

    def _execute_lifecycle_operation(
        self,
        *,
        user_id: int,
        container_id: ContainerId,
        spec: _LifecycleSpec,
        execute_operation: Callable[[Container], None],
    ) -> DockerResponse:
        """Execute shared lifecycle operation flow for start/stop/restart."""
        container_ref = self._normalize_container_id(container_id)
        context = build_container_context(
            container_id=container_ref,
            action=f"container_{spec.operation}",
            user_id=user_id,
        )
        start_time = time.time()

        try:
            with (
                docker_unavailable_as_connection_error(f"container {spec.operation}"),
                docker_client_context() as adapter,
            ):
                container = get_container_safely(container_ref, docker_client=adapter)
                with _in_flight_actions.hold(str(container.id), spec.operation):
                    self._validate_container_state_for_operation(container, spec)
                    self._record_operation(spec.operation, container_ref)
                    logger.info(spec.start_event, **context)
                    final_status = self._perform_and_verify(
                        container, spec, execute_operation, context
                    )
        except Exception as e:
            _log_action_failure(spec.fail_event, e, start_time, context)
            raise
        finally:
            invalidate_container_state_cache()

        logger.info(
            spec.success_event,
            execution_time=f"{time.time() - start_time:.2f}s",
            final_status=final_status,
            **context,
        )
        return None

    @validate_access
    def _start_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Start a stopped container."""
        return self._execute_lifecycle_operation(
            user_id=user_id,
            container_id=container_id,
            spec=_START_SPEC,
            execute_operation=lambda container: container.start(),
        )

    @validate_access
    def _stop_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Stop a running container (graceful timeout, then SIGKILL)."""
        timeout = getattr(settings.docker, "stop_timeout", DEFAULT_STOP_TIMEOUT_SECONDS)
        return self._execute_lifecycle_operation(
            user_id=user_id,
            container_id=container_id,
            spec=_STOP_SPEC,
            execute_operation=lambda container: container.stop(timeout=timeout),
        )

    @validate_access
    def _restart_container(
        self, user_id: int, container_id: ContainerId
    ) -> DockerResponse:
        """Restart a container (a stopped container is started)."""
        timeout = getattr(
            settings.docker, "restart_timeout", DEFAULT_STOP_TIMEOUT_SECONDS
        )
        return self._execute_lifecycle_operation(
            user_id=user_id,
            container_id=container_id,
            spec=_RESTART_SPEC,
            execute_operation=lambda container: container.restart(timeout=timeout),
        )

    @staticmethod
    def _validate_new_name(new_container_name: object) -> str:
        if not new_container_name or not isinstance(new_container_name, str):
            raise ValueError("New container name must be a non-empty string")

        new_name = new_container_name.strip()
        if len(new_name) > 64:  # Docker limit
            raise ValueError("Container name too long (max 64 characters)")
        if len(new_name) < 1:
            raise ValueError("Container name too short (min 1 character)")
        return new_name

    def _apply_rename(
        self,
        container: Container,
        container_ref: str,
        new_name: str,
        context: dict[str, object],
    ) -> str | None:
        """Rename and verify; return the old name, or None when unchanged."""
        old_name = str(container.name)
        if old_name == new_name:
            logger.info("docker.containers.container.name.info", **context)
            return None

        self._record_operation("rename", container_ref)
        logger.info(
            "docker.containers.renaming.container.info", old_name=old_name, **context
        )
        container.rename(new_name)
        container.reload()
        if container.name != new_name:
            logger.error(
                "docker.containers.container.rename.fail",
                expected_name=new_name,
                actual_name=container.name,
                **context,
            )
            raise RuntimeError(
                f"Rename operation failed: name is still '{container.name}'"
            )
        return old_name

    @validate_access
    def _rename_container(
        self, user_id: int, container_id: ContainerId, new_container_name: str
    ) -> DockerResponse:
        """Rename a container after validating the new name."""
        container_ref = self._normalize_container_id(container_id)
        new_name = self._validate_new_name(new_container_name)
        context = build_container_context(
            container_id=container_ref,
            action="container_rename",
            user_id=user_id,
            new_name=new_name,
        )
        start_time = time.time()

        try:
            if not is_new_name_valid(new_name):
                logger.warning(
                    "docker.containers.invalid.container.warn",
                    validation_error="name_format_invalid",
                    **context,
                )
                raise ValueError(f"Invalid container name format: {new_name}")

            with (
                docker_unavailable_as_connection_error("container rename"),
                docker_client_context() as adapter,
            ):
                container = get_container_safely(container_ref, docker_client=adapter)
                with _in_flight_actions.hold(str(container.id), "rename"):
                    old_name = self._apply_rename(
                        container, container_ref, new_name, context
                    )
        except Exception as e:
            _log_action_failure(
                "docker.containers.container.rename.fail", e, start_time, context
            )
            raise
        finally:
            invalidate_container_state_cache()

        if old_name is not None:
            logger.info(
                "docker.containers.container.renamed.ok",
                old_name=old_name,
                execution_time=f"{time.time() - start_time:.2f}s",
                **context,
            )
        return None

    @staticmethod
    def _parse_action(action: str, context: dict[str, object]) -> ContainerAction:
        try:
            return ContainerAction.from_str(action)
        except (ValueError, KeyError) as e:
            logger.warning(
                "docker.containers.invalid.container.warn",
                error=sanitize_exception(e),
                available_actions=[item.value for item in ContainerAction],
                **context,
            )
            raise ValueError(f"Invalid action: {action}") from e

    def _dispatch_action(
        self,
        user_id: int,
        container_ref: str,
        container_action: ContainerAction,
        kwargs: dict[str, object],
    ) -> DockerResponse:
        if container_action == ContainerAction.RENAME:
            new_container_name_raw = kwargs.get("new_container_name")
            new_container_name = (
                new_container_name_raw
                if isinstance(new_container_name_raw, str)
                else ""
            )
            return self._rename_container(user_id, container_ref, new_container_name)

        operations: dict[str, Callable[[int, str], DockerResponse]] = {
            ContainerAction.START: self._start_container,
            ContainerAction.STOP: self._stop_container,
            ContainerAction.RESTART: self._restart_container,
        }
        operation = operations.get(container_action)
        if operation is None:
            raise ValueError(f"Invalid action: {container_action}")
        return operation(user_id, container_ref)

    def managing_container(
        self,
        user_id: int,
        container_id: ContainerId,
        action: str,
        **kwargs: object,
    ) -> DockerResponse:
        """
        Run a container action and return normally on success.

        Raises:
            ValueError: Invalid action/user id or rename input.
            InvalidContainerReferenceError: Invalid container reference.
            ContainerNotFoundError: No such container, or the reference resolved
                to a different container.
            ContainerActionInProgressError: Another action on the container runs.
            ContainerStateConflictError: Start on a running container or stop on
                a container that does not run.
            DockerConnectionError: Docker is unavailable or timed out.
            PermissionError: Authorization, session or rate-limit failures.
        """
        if not isinstance(action, str) or not action.strip():
            raise ValueError("Action must be a non-empty string")

        action = action.strip().lower()
        container_ref = self._normalize_container_id(container_id)
        safe_kwargs = sanitize_kwargs_for_logging(kwargs)
        context = build_container_context(
            container_id=container_ref,
            action="container_management",
            user_id=user_id,
            operation=action,
            params=safe_kwargs if safe_kwargs else None,
        )
        container_action = self._parse_action(action, context)
        operation_start = time.time()
        logger.info("docker.containers.container.management.info", **context)

        try:
            result = self._dispatch_action(
                user_id, container_ref, container_action, kwargs
            )
        except PermissionError:
            # Already logged by the access validator.
            raise
        except Exception as e:
            _log_action_failure(
                "docker.containers.container.management.fail",
                e,
                operation_start,
                context,
            )
            raise

        logger.info(
            "docker.containers.container.management.ok",
            total_execution_time=f"{time.time() - operation_start:.2f}s",
            **context,
        )
        return result
