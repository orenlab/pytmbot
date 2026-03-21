#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import os
import time
import warnings
from contextlib import suppress
from datetime import datetime
from functools import cached_property
from inspect import signature
from pathlib import Path
from threading import Lock, RLock
from types import SimpleNamespace, TracebackType
from typing import Final
from uuid import uuid4

from docker.client import DockerClient
from docker.errors import DockerException
from docker.tls import TLSConfig

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


class _UnavailableDockerClient:
    """Fallback client for non-strict mode when Docker is inaccessible."""

    def __init__(self, reason: str) -> None:
        self._reason = reason
        self.api = SimpleNamespace(_version="unavailable")
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


type DockerClientLike = DockerClient | _UnavailableDockerClient


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
    _DEFAULT_TIMEOUT: Final[int] = 30
    _MIN_TIMEOUT: Final[int] = 5
    _MAX_TIMEOUT: Final[int] = 300
    _CONNECTION_TEST_TIMEOUT: Final[float] = 5.0
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
        docker_settings = getattr(settings, "docker", None)
        if docker_settings is None:
            self._handle_configuration_issue("Docker configuration is missing")
            return

        host_value = getattr(docker_settings, "host", None)
        if not isinstance(host_value, (list, tuple)) or not host_value:
            self._handle_configuration_issue("Docker host must be a non-empty list")
            return

        docker_url = str(host_value[0]).strip()
        if not docker_url:
            self._handle_configuration_issue("Docker host URL cannot be empty")
            return
        self._docker_url = docker_url

        # Validate timeout if provided; degrade to default in non-strict mode
        timeout = getattr(docker_settings, "timeout", self._DEFAULT_TIMEOUT)
        if not isinstance(timeout, int):
            message = "Docker timeout must be an integer"
            if self._strict_docker_access:
                raise ValueError(message)
            self._configured_timeout = self._DEFAULT_TIMEOUT
            self._log.warning(
                "docker.adapter.timeout.default.warn",
                invalid_timeout=timeout,
                fallback_timeout=self._DEFAULT_TIMEOUT,
            )
            return

        if not (self._MIN_TIMEOUT <= timeout <= self._MAX_TIMEOUT):
            message = (
                f"Docker timeout must be between {self._MIN_TIMEOUT} "
                f"and {self._MAX_TIMEOUT} seconds"
            )
            if self._strict_docker_access:
                raise ValueError(message)
            self._configured_timeout = self._DEFAULT_TIMEOUT
            self._log.warning(
                "docker.adapter.timeout.default.warn",
                invalid_timeout=timeout,
                fallback_timeout=self._DEFAULT_TIMEOUT,
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
                if attempt >= self._CONNECTION_TEST_RETRIES - 1:
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

    def _build_unavailable_client(self, reason: str) -> _UnavailableDockerClient:
        """Build a fallback client for degraded non-strict mode."""
        self._log.warning(
            "docker.adapter.degraded.mode.warn",
            reason=reason,
            **self._base_context,
        )
        return _UnavailableDockerClient(reason)

    def _create_client(self) -> DockerClient:
        """Create and configure Docker client with enhanced security and error handling."""
        context = self._get_context("client_creation")

        try:
            tls_config = self._create_tls_config()

            # Enhanced client configuration
            client_kwargs = {
                "base_url": self._docker_url,
                "tls": tls_config,
                "version": "auto",  # Auto-negotiate API version
                "user_agent": f"pyTMBot/{getattr(settings, 'version', '1.0')}",
                **self._timeout_config,
            }

            client = DockerClient(**client_kwargs)

            # Test connection with timeout
            docker_info = self._test_connection(client)
            if docker_info is None:
                raise DockerException("Connection test failed")

            # Reset failure counter on successful connection
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

        except DockerException as e:
            self._connection_failures += 1
            self._log.error(
                "docker.adapter.client.creation.fail",
                error=sanitize_exception(e),
                failure_count=self._connection_failures,
                **context,
            )
            raise DockerConnectionError(f"Failed to create Docker client: {e}") from e

        except Exception as e:
            self._connection_failures += 1
            self._log.error(
                "docker.adapter.unexpected.fail",
                error=sanitize_exception(e),
                error_type=type(e).__name__,
                failure_count=self._connection_failures,
                **context,
            )
            raise DockerConnectionError(
                f"Unexpected error creating Docker client: {e}"
            ) from e

    def _should_recreate_client(self) -> bool:
        """Determine if client should be recreated based on health and age."""
        if self._client is None:
            return True

        # Check if we need a health check
        now = datetime.now()
        if (
            self._last_health_check is None
            or (now - self._last_health_check).total_seconds()
            > self._HEALTH_CHECK_INTERVAL
        ):
            # Quick health check
            try:
                self._client.ping()
                self._last_health_check = now
                return False
            except Exception:
                self._log.trace(
                    "docker.adapter.health.check.fail",
                    **self._base_context,
                )
                return True

        return False

    def __enter__(self) -> DockerClientLike:
        """Enter Docker context manager - create and return client with thread safety."""
        self._span_id = uuid4().hex[:8]
        context = self._get_context("context_enter")

        try:
            with self._lock:
                if self._disabled_reason and not self._strict_docker_access:
                    if self._client is None:
                        self._client = self._build_unavailable_client(
                            self._disabled_reason
                        )
                    return self._client

                if not self._should_recreate_client():
                    if self._client is None:
                        raise DockerConnectionError("Docker client is not initialized")
                    self._log.trace("docker.adapter.context.entered.debug", **context)
                    return self._client

            # Slow path: create client outside the primary lock.
            with self._create_lock:
                with self._lock:
                    if not self._should_recreate_client():
                        if self._client is None:
                            raise DockerConnectionError(
                                "Docker client is not initialized"
                            )
                        self._log.trace(
                            "docker.adapter.context.entered.debug", **context
                        )
                        return self._client

                    old_client = self._client
                    self._client = None

                if old_client:
                    with suppress(Exception):
                        old_client.close()

                created_client = self._create_client()

                with self._lock:
                    self._client = created_client
                    self._log.trace("docker.adapter.context.entered.debug", **context)
                    return self._client

        except Exception as e:
            if not self._strict_docker_access:
                with self._lock:
                    self._client = self._build_unavailable_client(sanitize_exception(e))
                    return self._client
            self._log.error(
                "docker.adapter.enter.context.fail",
                error=sanitize_exception(e),
                **context,
            )
            raise DockerConnectionError(f"Docker client init failed: {e}") from e

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
            if issubclass(exc_type, (DockerException, DockerConnectionError)):
                self._log.error(
                    "docker.adapter.context.exited.fail",
                    exception_type=exc_type.__name__,
                    exception_message=str(exc_val),
                    **context,
                )
                # Mark client for recreation on Docker errors
                self._last_health_check = None
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

                # Test container listing (lightweight operation)
                containers = client.containers.list(limit=1)

                execution_time = (datetime.now() - start_time).total_seconds()

                self._log.info(
                    "docker.adapter.health.check.info",
                    execution_time=f"{execution_time:.3f}s",
                    docker_version=info.get("ServerVersion", "unknown"),
                    containers_accessible=len(containers) >= 0,
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
