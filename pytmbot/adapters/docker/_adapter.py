#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import os
import time
import warnings
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from inspect import signature
from pathlib import Path
from threading import Lock, RLock
from types import TracebackType
from typing import Final, NoReturn
from uuid import uuid4

from docker.client import DockerClient
from docker.errors import DockerException
from docker.tls import TLSConfig
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from pytmbot.exceptions import DockerConnectionError
from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.utils import sanitize_exception


def _parse_bool_like(value: object) -> bool:
    """Parse boolean-like values from env/config strings."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class _UnavailableDockerCollection:
    """Fallback Docker collection that safely degrades list operations."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def list(self, *_args: object, **_kwargs: object) -> list[object]:
        raise DockerConnectionError(f"Docker is unavailable: {self._reason}")

    def get(self, *_args: object, **_kwargs: object) -> object:
        raise DockerConnectionError(f"Docker is unavailable: {self._reason}")


class _UnavailableDockerApi:
    """Fallback low-level API client: every call raises DockerConnectionError."""

    def __init__(self, reason: str) -> None:
        self._reason = reason
        self._version = "unavailable"

    def __getattr__(self, name: str) -> Callable[..., NoReturn]:
        if name.startswith("__"):
            raise AttributeError(name)
        reason = self._reason

        def _unavailable(*_args: object, **_kwargs: object) -> NoReturn:
            raise DockerConnectionError(f"Docker is unavailable: {reason}")

        return _unavailable


class _UnavailableDockerClient:
    """Fallback client for non-strict mode when Docker is inaccessible."""

    def __init__(self, reason: str) -> None:
        self._reason = reason
        self.api = _UnavailableDockerApi(reason)
        self.containers = _UnavailableDockerCollection(reason)
        self.images = _UnavailableDockerCollection(reason)

    def ping(self) -> None:
        raise DockerConnectionError(f"Docker is unavailable: {self._reason}")

    def version(self) -> dict[str, str]:
        raise DockerConnectionError(f"Docker is unavailable: {self._reason}")

    def info(self) -> dict[str, str]:
        raise DockerConnectionError(f"Docker is unavailable: {self._reason}")

    @staticmethod
    def close() -> None:
        return


@dataclass(slots=True)
class _BackoffEntry:
    failures: int
    retry_at: float
    reason: str


class _ConnectionBackoff:
    """
    Negative cache for failed Docker connections, shared by all adapters.

    Adapters are thread-local; sharing the backoff state means an outage costs
    one bounded probe per retry window for the whole process instead of one
    blocking probe per call and per thread.
    """

    def __init__(
        self,
        *,
        base_seconds: float,
        max_seconds: float,
        probe_window_seconds: float,
    ) -> None:
        self._base_seconds = base_seconds
        self._max_seconds = max_seconds
        self._probe_window_seconds = probe_window_seconds
        self._lock = Lock()
        self._entries: dict[str, _BackoffEntry] = {}

    def delay_for(self, failures: int) -> float:
        """Exponential delay for the given number of consecutive failures."""
        exponent = max(failures - 1, 0)
        return min(self._base_seconds * float(2**exponent), self._max_seconds)

    def try_acquire(self, key: str) -> str | None:
        """
        Return None if the caller may try to connect, else why to fail fast.

        After the retry deadline the first caller claims the probe; others
        keep failing fast until it reports success or failure (or the probe
        window elapses, so a crashed probe cannot block reconnects forever).
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            now = time.monotonic()
            if now < entry.retry_at:
                return f"{entry.reason} (retry in {entry.retry_at - now:.0f}s)"
            entry.retry_at = now + self._probe_window_seconds
            return None

    def record_failure(self, key: str, reason: str) -> float:
        """Register a failed attempt and return the delay before the next one."""
        with self._lock:
            entry = self._entries.setdefault(key, _BackoffEntry(0, 0.0, reason))
            entry.failures += 1
            entry.reason = reason
            delay = self.delay_for(entry.failures)
            entry.retry_at = time.monotonic() + delay
            return delay

    def record_success(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


_CONNECTION_BACKOFF: Final[_ConnectionBackoff] = _ConnectionBackoff(
    base_seconds=2.0,
    max_seconds=60.0,
    probe_window_seconds=30.0,
)


def reset_connection_backoff() -> None:
    """Forget previous connection failures (tests/shutdown)."""
    _CONNECTION_BACKOFF.reset()


type DockerClientLike = DockerClient | _UnavailableDockerClient

_CONNECTION_ERROR_TYPES: Final[tuple[type[BaseException], ...]] = (
    DockerConnectionError,
    RequestsConnectionError,
    RequestsTimeout,
)


class DockerAdapter:
    """
    Docker interaction wrapper with secure defaults, connection pooling, and contextual logging.

    Features:
    - Secure TLS configuration with certificate validation
    - Connection health monitoring and recovery
    - Thread-safe operations with connection pooling
    - Comprehensive security warnings and validation
    - Performance monitoring and timeout management
    """

    # Class constants for better maintainability
    # Interactive (Telegram) calls must not hang: keep the per-request HTTP
    # timeout short. stop/restart add their own grace period on top of it.
    _DEFAULT_TIMEOUT: Final[int] = 10
    _MIN_TIMEOUT: Final[int] = 5
    _MAX_TIMEOUT: Final[int] = 300
    # Connection probes (API negotiation + ping) use an even shorter timeout.
    _CONNECTION_TEST_TIMEOUT: Final[int] = 5
    _CONNECTION_TEST_RETRIES: Final[int] = 3
    _CONNECTION_TEST_BACKOFF_SECONDS: Final[float] = 0.5
    _HEALTH_CHECK_INTERVAL: Final[float] = 30.0
    _STRICT_DOCKER_ACCESS_ENV: Final[str] = "STRICT_DOCKER_ACCESS"
    _DOCKER_INFO_TTL_SECONDS: Final[float] = 30.0

    def __init__(self) -> None:
        self._log = Logger()
        self._lock = RLock()  # Thread safety for client operations
        self._create_lock = Lock()
        self._client: DockerClientLike | None = None
        self._start_time: datetime = datetime.now()
        self._connection_failures = 0
        self._last_health_check: datetime | None = None
        self._span_id: str | None = None
        self._strict_docker_access = self._is_strict_docker_access_enabled()
        self._configured_timeout = self._DEFAULT_TIMEOUT
        self._disabled_reason: str | None = None
        self._docker_url: str = ""
        self._docker_info_cache: dict[str, object] | None = None
        self._docker_info_cached_at = 0.0
        self._validate_configuration()

        # Initialize base context for all operations
        self._base_context = {
            "docker_url": self._docker_url,
            "adapter_id": id(self),
            "strict_docker_access": self._strict_docker_access,
        }

        if self._disabled_reason:
            self._log.warning(
                "docker.adapter.disabled.warn",
                reason=self._disabled_reason,
                **self._base_context,
            )
        else:
            self._perform_security_checks()
        self._log.trace("docker.adapter.init", **self._base_context)

    def _is_strict_docker_access_enabled(self) -> bool:
        """Resolve strict Docker access mode from env/config."""
        env_value = os.getenv(self._STRICT_DOCKER_ACCESS_ENV)
        if env_value is not None:
            return _parse_bool_like(env_value)

        docker_settings = getattr(settings, "docker", None)
        return _parse_bool_like(getattr(docker_settings, "strict_access", False))

    def _handle_configuration_issue(self, message: str) -> None:
        """Handle configuration issue according to strict mode."""
        if self._strict_docker_access:
            raise ValueError(message)
        self._disabled_reason = message

    def _validate_configuration(self) -> None:
        """Validate Docker configuration with comprehensive checks."""

        def fail_configuration(message: str) -> None:
            self._handle_configuration_issue(message)

        docker_settings = getattr(settings, "docker", None)
        validation_error: str | None = None
        docker_url = ""
        if docker_settings is None:
            validation_error = "Docker configuration is missing"
        else:
            host_value = getattr(docker_settings, "host", None)
            if not isinstance(host_value, (list, tuple)) or not host_value:
                validation_error = "Docker host must be a non-empty list"
            else:
                docker_url = str(host_value[0]).strip()
                if not docker_url:
                    validation_error = "Docker host URL cannot be empty"

        if validation_error is not None:
            fail_configuration(validation_error)
            return
        self._docker_url = docker_url

        # Validate timeout if provided; degrade to default in non-strict mode
        def use_default_timeout(message: str) -> None:
            if self._strict_docker_access:
                raise ValueError(message)
            self._configured_timeout = self._DEFAULT_TIMEOUT
            self._log.warning(
                "docker.adapter.timeout.default.warn",
                invalid_timeout=timeout,
                fallback_timeout=self._DEFAULT_TIMEOUT,
            )

        timeout = getattr(docker_settings, "timeout", self._DEFAULT_TIMEOUT)
        if not isinstance(timeout, int):
            use_default_timeout("Docker timeout must be an integer")
            return

        if not (self._MIN_TIMEOUT <= timeout <= self._MAX_TIMEOUT):
            use_default_timeout(
                f"Docker timeout must be between {self._MIN_TIMEOUT} "
                f"and {self._MAX_TIMEOUT} seconds"
            )
            return

        self._configured_timeout = timeout

    def _perform_security_checks(self) -> None:
        """Perform comprehensive security validation."""
        # Check for insecure connections
        if self._docker_url.startswith("http://"):
            warnings.warn(
                "Using unencrypted HTTP connection to Docker daemon. "
                "This poses security risks in production environments.",
                RuntimeWarning,
                stacklevel=2,
            )
            self._log.warning(
                "docker.adapter.insecure.connection.warn",
                security_risk="unencrypted_connection",
                **self._base_context,
            )

        # Check for TCP socket without TLS
        if self._docker_url.startswith("tcp://") and not self._docker_url.startswith(
            "tcp+tls://"
        ):
            self._log.warning(
                "docker.adapter.tcp.connection.warn",
                security_risk="tcp_without_tls",
                **self._base_context,
            )

        # Validate certificate paths if HTTPS is used
        if self._docker_url.startswith("https://"):
            self._validate_tls_configuration()

    def _validate_tls_configuration(self) -> None:
        """Validate TLS certificate configuration."""
        cert_path = getattr(settings.docker, "cert_path", None)
        key_path = getattr(settings.docker, "key_path", None)
        ca_cert = getattr(settings.docker, "ca_cert", None)

        if cert_path and not Path(cert_path).exists():
            self._log.warning(
                "docker.adapter.tls.client.warn",
                cert_path=cert_path,
                **self._base_context,
            )

        if key_path and not Path(key_path).exists():
            self._log.warning(
                "docker.adapter.tls.client.warn",
                key_path=key_path,
                **self._base_context,
            )

        if isinstance(ca_cert, str) and not Path(ca_cert).exists():
            self._log.warning(
                "docker.adapter.tls.ca.warn",
                ca_cert=ca_cert,
                **self._base_context,
            )

    @cached_property
    def _timeout_config(self) -> dict[str, int]:
        """Get timeout configuration for Docker client with validation."""
        timeout = max(
            self._MIN_TIMEOUT,
            min(self._configured_timeout, self._MAX_TIMEOUT),
        )
        return {"timeout": int(timeout)}

    def _get_context(
        self, action: str, extra: dict[str, object] | None = None
    ) -> dict[str, object]:
        """Build context dictionary for logging with consistent structure."""
        uptime_seconds = (datetime.now() - self._start_time).total_seconds()

        context = {
            **self._base_context,
            "action": action,
            "uptime": f"{uptime_seconds:.2f}s",
            "connection_failures": self._connection_failures,
        }

        if self._span_id:
            context["span_id"] = self._span_id

        if extra:
            # Sanitize any potentially sensitive information
            safe_extra: dict[str, object] = {}
            for key, value in extra.items():
                if any(
                    sensitive in key.lower()
                    for sensitive in ["password", "token", "secret", "key", "auth"]
                ):
                    safe_extra[key] = "[REDACTED]"
                else:
                    safe_extra[key] = value
            context.update(safe_extra)

        return context

    def _create_tls_config(self) -> TLSConfig | None:
        """Create TLS configuration with enhanced security."""
        if not self._docker_url.startswith("https://"):
            return None

        try:
            cert_path = getattr(settings.docker, "cert_path", None)
            key_path = getattr(settings.docker, "key_path", None)
            ca_cert = getattr(settings.docker, "ca_cert", True)
            verify_hostname = bool(getattr(settings.docker, "verify_hostname", True))
            if not ca_cert:
                verify_hostname = False

            # Enhanced TLS configuration
            tls_kwargs: dict[str, object] = {
                "client_cert": (
                    (cert_path, key_path) if cert_path and key_path else None
                ),
                "verify": ca_cert,
            }
            if "assert_hostname" in signature(TLSConfig.__init__).parameters:
                tls_kwargs["assert_hostname"] = verify_hostname
            elif not verify_hostname:
                self._log.warning(
                    "docker.adapter.tls.hostname.verify.unsupported.warn",
                    **self._base_context,
                )
            tls_config = TLSConfig(**tls_kwargs)

            self._log.trace(
                "docker.adapter.tls.config.debug",
                has_client_cert=bool(cert_path and key_path),
                verify_server=bool(ca_cert),
                verify_hostname=verify_hostname,
                **self._base_context,
            )

            return tls_config

        except Exception as e:
            self._log.error(
                "docker.adapter.create.tls.fail",
                error=sanitize_exception(e),
                **self._base_context,
            )
            raise

    def _test_connection(self, client: DockerClient) -> dict[str, object] | None:
        """Test Docker connection with timeout and error handling."""
        last_error: Exception | None = None

        for attempt in range(self._CONNECTION_TEST_RETRIES):
            try:
                # Fast liveness check.
                client.ping()

                # Lightweight metadata call (cheaper than full info()).
                version = client.version()
                if not isinstance(version, dict):
                    version = {}

                self._log.trace(
                    "docker.adapter.connection.test.ok",
                    docker_version=version.get("Version", "unknown"),
                    **self._base_context,
                )
                return version
            except Exception as error:
                last_error = error
                # A timed out daemon will not recover within the retry backoff.
                if attempt >= self._CONNECTION_TEST_RETRIES - 1 or isinstance(
                    error, RequestsTimeout
                ):
                    break

                backoff_seconds = self._CONNECTION_TEST_BACKOFF_SECONDS * (2**attempt)
                self._log.warning(
                    "docker.adapter.connection.test.retry.warn",
                    attempt=attempt + 1,
                    max_attempts=self._CONNECTION_TEST_RETRIES,
                    backoff_seconds=backoff_seconds,
                    error=sanitize_exception(error),
                    **self._base_context,
                )
                time.sleep(backoff_seconds)

        self._log.warning(
            "docker.adapter.connection.test.fail",
            error=sanitize_exception(last_error)
            if last_error is not None
            else "unknown",
            **self._base_context,
        )
        return None

    def _client_kwargs(self) -> dict[str, object]:
        """Build DockerClient kwargs; the probe runs with a short timeout."""
        return {
            "base_url": self._docker_url,
            "tls": self._create_tls_config(),
            "version": "auto",  # Auto-negotiate API version (one GET /version)
            "user_agent": f"pyTMBot/{getattr(settings, 'version', '1.0')}",
            "timeout": min(
                self._CONNECTION_TEST_TIMEOUT, self._timeout_config["timeout"]
            ),
        }

    def _drop_client_after_transport_failure(self, error: BaseException | None) -> None:
        """
        Forget a client whose request timed out or lost the connection.

        Recording the failure right away makes the next calls fail fast inside
        the backoff window instead of paying another full timeout on a health
        ping against the same hung daemon. Calls on the degraded client (no
        cached client) are not counted again.
        """
        with self._lock:
            client, self._client = self._client, None
            self._last_health_check = None
        if client is None:
            return
        self._close_quietly(client)
        reason = (
            sanitize_exception(error)
            if isinstance(error, Exception)
            else "transport error"
        )
        _CONNECTION_BACKOFF.record_failure(
            self._docker_url, f"Request failed: {reason}"
        )

    def _close_quietly(self, client: object | None) -> None:
        """Close a client that is no longer used; closing must never fail a call."""
        close = getattr(client, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception as error:
            self._log.trace(
                "docker.adapter.closing.client.fail",
                error=sanitize_exception(error),
                **self._base_context,
            )

    def _client_creation_error(
        self, error: Exception, context: dict[str, object]
    ) -> DockerConnectionError:
        self._connection_failures += 1
        if isinstance(error, DockerException):
            self._log.error(
                "docker.adapter.client.creation.fail",
                error=sanitize_exception(error),
                failure_count=self._connection_failures,
                **context,
            )
            return DockerConnectionError(f"Failed to create Docker client: {error}")
        self._log.error(
            "docker.adapter.unexpected.fail",
            error=sanitize_exception(error),
            error_type=type(error).__name__,
            failure_count=self._connection_failures,
            **context,
        )
        return DockerConnectionError(
            f"Unexpected error creating Docker client: {error}"
        )

    def _create_client(self) -> DockerClient:
        """Create, probe and configure a Docker client; close it if the probe fails."""
        context = self._get_context("client_creation")
        client: DockerClient | None = None

        try:
            client = DockerClient(**self._client_kwargs())
            docker_info = self._test_connection(client)
            if docker_info is None:
                raise DockerException("Connection test failed")
            # Probe passed: switch to the regular per-request timeout.
            client.api.timeout = self._timeout_config["timeout"]
        except Exception as e:
            self._close_quietly(client)
            raise self._client_creation_error(e, context) from e

        self._connection_failures = 0
        self._last_health_check = datetime.now()
        self._log.debug(
            "docker.adapter.connected.debug",
            docker_version=(
                docker_info.get("ServerVersion")
                or docker_info.get("Version")
                or "unknown"
            ),
            api_version=getattr(client.api, "_version", "unknown"),
            span_id=self._span_id,
        )
        return client

    def _reuse_cached_client(self) -> DockerClient | None:
        """
        Return the cached client if it is healthy.

        A failed health ping drops (and closes) the client, records the
        failure in the shared backoff and fails fast instead of immediately
        re-probing an unreachable daemon.
        """
        client = self._client
        if client is None:
            return None

        now = datetime.now()
        if (
            self._last_health_check is not None
            and (now - self._last_health_check).total_seconds()
            <= self._HEALTH_CHECK_INTERVAL
        ):
            return client

        try:
            client.ping()
        except Exception as error:
            self._log.trace("docker.adapter.health.check.fail", **self._base_context)
            self._client = None
            self._close_quietly(client)
            reason = f"Health check failed: {sanitize_exception(error)}"
            _CONNECTION_BACKOFF.record_failure(self._docker_url, reason)
            raise DockerConnectionError(f"Docker is unavailable: {reason}") from error

        self._last_health_check = now
        return client

    def _connect_new_client(self) -> DockerClient:
        """Replace the cached client with a freshly probed one."""
        with self._lock:
            old_client, self._client = self._client, None
        self._close_quietly(old_client)

        try:
            client = self._create_client()
        except DockerConnectionError as error:
            delay = _CONNECTION_BACKOFF.record_failure(
                self._docker_url, sanitize_exception(error)
            )
            self._log.warning(
                "docker.adapter.degraded.mode.warn",
                reason=sanitize_exception(error),
                retry_in_seconds=delay,
                **self._base_context,
            )
            raise

        _CONNECTION_BACKOFF.record_success(self._docker_url)
        with self._lock:
            self._client = client
        return client

    def _acquire_client(self) -> DockerClient:
        """Return a healthy client, or raise DockerConnectionError quickly."""
        with self._lock:
            cached = self._reuse_cached_client()
        if cached is not None:
            return cached

        blocked_reason = _CONNECTION_BACKOFF.try_acquire(self._docker_url)
        if blocked_reason is not None:
            raise DockerConnectionError(f"Docker is unavailable: {blocked_reason}")

        with self._create_lock:
            return self._connect_new_client()

    def _unavailable_or_raise(
        self, error: DockerConnectionError, context: dict[str, object]
    ) -> _UnavailableDockerClient:
        if self._strict_docker_access:
            self._log.error(
                "docker.adapter.enter.context.fail",
                error=sanitize_exception(error),
                **context,
            )
            raise error
        self._log.trace(
            "docker.adapter.degraded.client.debug",
            reason=sanitize_exception(error),
            **context,
        )
        return _UnavailableDockerClient(sanitize_exception(error))

    def __enter__(self) -> DockerClientLike:
        """
        Enter the Docker context and return a client.

        While Docker is unavailable (inside the backoff window) this returns
        immediately: a degraded client in non-strict mode, or raises
        DockerConnectionError in strict mode.
        """
        self._span_id = uuid4().hex[:8]
        context = self._get_context("context_enter")

        if self._disabled_reason:
            return _UnavailableDockerClient(self._disabled_reason)

        try:
            client = self._acquire_client()
        except DockerConnectionError as error:
            return self._unavailable_or_raise(error, context)

        self._log.trace("docker.adapter.context.entered.debug", **context)
        return client

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit Docker context manager - manage connection lifecycle."""
        context = self._get_context("context_exit")

        # Note: We don't always close the client here as we want connection reuse
        # The client will be closed when the adapter is garbage collected or
        # when health checks fail

        # Log exceptions at appropriate level
        if exc_type:
            if issubclass(exc_type, _CONNECTION_ERROR_TYPES):
                self._drop_client_after_transport_failure(exc_val)
            if issubclass(exc_type, (DockerException, *_CONNECTION_ERROR_TYPES)):
                self._log.error(
                    "docker.adapter.context.exited.fail",
                    exception_type=exc_type.__name__,
                    exception_message=str(exc_val),
                    **context,
                )
            else:
                # Other exceptions - log at debug to reduce noise
                self._log.trace(
                    "docker.adapter.context.exited.fail",
                    exception_type=exc_type.__name__,
                    exception_message=str(exc_val),
                    **context,
                )
        else:
            # Normal exit - only debug level
            self._log.trace("docker.adapter.context.exited.debug", **context)

        self._span_id = None

    def health_check(self) -> bool:
        """
        Perform comprehensive health check on Docker connection.

        Returns:
            bool: True if healthy, False otherwise
        """
        context = self._get_context("health_check")
        start_time = datetime.now()

        try:
            with self as client:
                # Test basic connectivity
                client.ping()

                # Test API functionality
                info = client.info()
                if not info:
                    raise DockerException("Docker info returned empty")

                # Test container listing (sparse: no per-container inspect race)
                containers = client.containers.list(limit=1, sparse=True)

                execution_time = (datetime.now() - start_time).total_seconds()

                self._log.info(
                    "docker.adapter.health.check.info",
                    execution_time=f"{execution_time:.3f}s",
                    docker_version=info.get("ServerVersion", "unknown"),
                    containers_accessible=True,
                    containers_checked=len(containers),
                    **context,
                )
                return True

        except DockerConnectionError as e:
            self._log.warning(
                "docker.adapter.health.check.fail",
                error=sanitize_exception(e),
                **context,
            )
            return False

        except Exception as e:
            self._log.error(
                "docker.adapter.health.check.fail",
                error=sanitize_exception(e),
                error_type=type(e).__name__,
                **context,
            )
            return False

    def close(self) -> None:
        """Explicitly close the Docker client connection."""
        with self._create_lock:
            with self._lock:
                client = self._client
                self._client = None
                self._docker_info_cache = None
                self._docker_info_cached_at = 0.0

            if client is not None:
                try:
                    client.close()
                    self._log.trace(
                        "docker.adapter.client.connection.debug", **self._base_context
                    )
                except Exception as e:
                    self._log.warning(
                        "docker.adapter.closing.client.fail",
                        error=sanitize_exception(e),
                        **self._base_context,
                    )

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        try:
            self.close()
        except Exception as error:
            with suppress(Exception):
                self._log.warning(
                    "docker.adapter.cleanup.fail",
                    error=sanitize_exception(error),
                    **self._base_context,
                )
