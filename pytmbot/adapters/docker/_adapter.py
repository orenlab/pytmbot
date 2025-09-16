#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import warnings
from contextlib import suppress
from datetime import datetime
from functools import cached_property, lru_cache
from pathlib import Path
from threading import RLock
from types import TracebackType
from typing import Any, Dict, Optional, Type, Final

import docker
from docker import DockerClient
from docker.errors import DockerException

from pytmbot.exceptions import DockerConnectionError
from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.utils import sanitize_exception


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
    _HEALTH_CHECK_INTERVAL: Final[float] = 30.0

    def __init__(self) -> None:
        self._validate_configuration()

        self._docker_url: str = str(settings.docker.host[0])
        self._client: Optional[DockerClient] = None
        self._start_time: datetime = datetime.now()
        self._log = Logger()
        self._lock = RLock()  # Thread safety for client operations
        self._connection_failures = 0
        self._last_health_check: Optional[datetime] = None

        # Initialize base context for all operations
        self._base_context = {
            "action": "docker_adapter",
            "docker_url": self._docker_url,
            "adapter_id": id(self),
        }

        self._perform_security_checks()
        self._log.debug("DockerAdapter initialized", **self._base_context)

    def _validate_configuration(self) -> None:
        """Validate Docker configuration with comprehensive checks."""
        if not hasattr(settings, "docker") or not settings.docker.host:
            raise ValueError("Docker configuration is missing or invalid")

        if (
            not isinstance(settings.docker.host, (list, tuple))
            or not settings.docker.host
        ):
            raise ValueError("Docker host must be a non-empty list")

        # Validate timeout if provided
        timeout = getattr(settings.docker, "timeout", self._DEFAULT_TIMEOUT)
        if not isinstance(timeout, int) or not (
            self._MIN_TIMEOUT <= timeout <= self._MAX_TIMEOUT
        ):
            raise ValueError(
                f"Docker timeout must be between {self._MIN_TIMEOUT} and {self._MAX_TIMEOUT} seconds"
            )

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
                "Insecure Docker connection detected",
                docker_url=self._docker_url,
                security_risk="unencrypted_connection",
                **self._base_context,
            )

        # Check for TCP socket without TLS
        if self._docker_url.startswith("tcp://") and not self._docker_url.startswith(
            "tcp+tls://"
        ):
            self._log.warning(
                "TCP connection without TLS detected",
                docker_url=self._docker_url,
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
                "TLS client certificate not found",
                cert_path=cert_path,
                **self._base_context,
            )

        if key_path and not Path(key_path).exists():
            self._log.warning(
                "TLS client key not found",
                key_path=key_path,
                **self._base_context,
            )

        if isinstance(ca_cert, str) and not Path(ca_cert).exists():
            self._log.warning(
                "TLS CA certificate not found",
                ca_cert=ca_cert,
                **self._base_context,
            )

    @cached_property
    def _timeout_config(self) -> Dict[str, int]:
        """Get timeout configuration for Docker client with validation."""
        timeout = getattr(settings.docker, "timeout", self._DEFAULT_TIMEOUT)

        # Ensure timeout is within safe bounds
        timeout = max(self._MIN_TIMEOUT, min(timeout, self._MAX_TIMEOUT))

        return {"timeout": timeout}

    def _get_context(
        self, action: str, extra: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build context dictionary for logging with consistent structure."""
        uptime_seconds = (datetime.now() - self._start_time).total_seconds()

        context = {
            **self._base_context,
            "action": action,
            "uptime": f"{uptime_seconds:.2f}s",
            "connection_failures": self._connection_failures,
        }

        if extra:
            # Sanitize any potentially sensitive information
            safe_extra = {}
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

    def _create_tls_config(self) -> Optional[docker.tls.TLSConfig]:
        """Create TLS configuration with enhanced security."""
        if not self._docker_url.startswith("https://"):
            return None

        try:
            cert_path = getattr(settings.docker, "cert_path", None)
            key_path = getattr(settings.docker, "key_path", None)
            ca_cert = getattr(settings.docker, "ca_cert", True)
            verify_hostname = getattr(settings.docker, "verify_hostname", True)

            # Enhanced TLS configuration
            tls_config = docker.tls.TLSConfig(
                client_cert=(cert_path, key_path) if cert_path and key_path else None,
                verify=ca_cert,
            )

            self._log.debug(
                "TLS configuration created",
                has_client_cert=bool(cert_path and key_path),
                verify_server=bool(ca_cert),
                **self._base_context,
            )

            return tls_config

        except Exception as e:
            self._log.error(
                "Failed to create TLS configuration",
                error=sanitize_exception(e),
                **self._base_context,
            )
            raise

    def _test_connection(self, client: DockerClient) -> bool:
        """Test Docker connection with timeout and error handling."""
        try:
            # Use ping with timeout
            client.ping()

            # Additional validation - try to get Docker info
            info = client.info()
            if not info:
                return False

            self._log.debug(
                "Connection test successful",
                docker_version=info.get("ServerVersion", "unknown"),
                **self._base_context,
            )
            return True

        except Exception as e:
            self._log.warning(
                "Connection test failed",
                error=sanitize_exception(e),
                **self._base_context,
            )
            return False

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

            client = docker.DockerClient(**client_kwargs)

            # Test connection with timeout
            if not self._test_connection(client):
                raise DockerException("Connection test failed")

            # Reset failure counter on successful connection
            self._connection_failures = 0
            self._last_health_check = datetime.now()

            self._log.info(
                "Docker client created successfully",
                tls_enabled=bool(tls_config),
                timeout=self._timeout_config.get("timeout"),
                api_version=getattr(client.api, "_version", "unknown"),
                **context,
            )

            return client

        except DockerException as e:
            self._connection_failures += 1
            self._log.error(
                "Docker client creation failed",
                error=sanitize_exception(e),
                failure_count=self._connection_failures,
                **context,
            )
            raise DockerConnectionError(f"Failed to create Docker client: {e}") from e

        except Exception as e:
            self._connection_failures += 1
            self._log.error(
                "Unexpected error during client creation",
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
                self._log.debug(
                    "Health check failed, client recreation needed",
                    **self._base_context,
                )
                return True

        return False

    @lru_cache(maxsize=1)
    def _get_docker_info(self) -> Dict[str, Any]:
        """Get Docker daemon information (cached)."""
        try:
            with self:
                info = self._client.info()
                return {
                    "version": info.get("ServerVersion", "unknown"),
                    "api_version": info.get("ApiVersion", "unknown"),
                    "kernel_version": info.get("KernelVersion", "unknown"),
                    "operating_system": info.get("OperatingSystem", "unknown"),
                    "architecture": info.get("Architecture", "unknown"),
                }
        except Exception as e:
            self._log.warning(
                "Failed to get Docker info",
                error=sanitize_exception(e),
                **self._base_context,
            )
            return {}

    def __enter__(self) -> DockerClient:
        """Enter Docker context manager - create and return client with thread safety."""
        with self._lock:
            context = self._get_context("context_enter")

            try:
                # Recreate client if needed
                if self._should_recreate_client():
                    if self._client:
                        with suppress(Exception):
                            self._client.close()
                        self._client = None

                    self._client = self._create_client()

                # Log entry at debug level to avoid noise
                self._log.debug("Docker context entered", **context)
                return self._client

            except Exception as e:
                self._log.error(
                    "Failed to enter Docker context",
                    error=sanitize_exception(e),
                    **context,
                )
                raise DockerConnectionError(f"Docker client init failed: {e}") from e

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
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
                    "Docker context exited with Docker-related exception",
                    exception_type=exc_type.__name__,
                    exception_message=str(exc_val),
                    **context,
                )
                # Mark client for recreation on Docker errors
                self._last_health_check = None
            else:
                # Other exceptions - log at debug to reduce noise
                self._log.debug(
                    "Docker context exited with exception",
                    exception_type=exc_type.__name__,
                    exception_message=str(exc_val),
                    **context,
                )
        else:
            # Normal exit - only debug level
            self._log.debug("Docker context exited normally", **context)

    def health_check(self) -> bool:
        """
        Perform comprehensive health check on Docker connection.

        Returns:
            bool: True if healthy, False otherwise
        """
        context = self._get_context("health_check")
        start_time = datetime.now()

        try:
            with self:
                # Test basic connectivity
                self._client.ping()

                # Test API functionality
                info = self._client.info()
                if not info:
                    raise DockerException("Docker info returned empty")

                # Test container listing (lightweight operation)
                containers = self._client.containers.list(limit=1)

                execution_time = (datetime.now() - start_time).total_seconds()

                self._log.info(
                    "Docker health check passed",
                    execution_time=f"{execution_time:.3f}s",
                    docker_version=info.get("ServerVersion", "unknown"),
                    containers_accessible=len(containers) >= 0,
                    **context,
                )
                return True

        except DockerConnectionError as e:
            self._log.warning(
                "Docker health check failed", error=sanitize_exception(e), **context
            )
            return False

        except Exception as e:
            self._log.error(
                "Docker health check encountered unexpected error",
                error=sanitize_exception(e),
                error_type=type(e).__name__,
                **context,
            )
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive Docker adapter status information."""
        uptime_seconds = (datetime.now() - self._start_time).total_seconds()

        status = {
            "docker_url": self._docker_url,
            "uptime": f"{uptime_seconds:.2f}s",
            "client_active": self._client is not None,
            "secure_connection": self._docker_url.startswith(
                ("https://", "tcp+tls://")
            ),
            "connection_failures": self._connection_failures,
            "last_health_check": (
                self._last_health_check.isoformat() if self._last_health_check else None
            ),
            "timeout_config": self._timeout_config,
        }

        # Add Docker daemon info if available
        docker_info = self._get_docker_info()
        if docker_info:
            status["docker_info"] = docker_info

        return status

    def close(self) -> None:
        """Explicitly close the Docker client connection."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                    self._log.debug(
                        "Docker client connection closed", **self._base_context
                    )
                except Exception as e:
                    self._log.warning(
                        "Error closing Docker client",
                        error=sanitize_exception(e),
                        **self._base_context,
                    )
                finally:
                    self._client = None

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass  # Suppress exceptions during cleanup

    def force_reconnect(self) -> None:
        """Force recreation of Docker client connection."""
        with self._lock:
            self.close()
            self._last_health_check = None
            self._log.info("Forced Docker client reconnection", **self._base_context)
