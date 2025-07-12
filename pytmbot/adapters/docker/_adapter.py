import uuid
import warnings
from contextlib import suppress
from datetime import datetime
from functools import cached_property
from types import TracebackType
from typing import Any, Dict, Optional, Type

import docker
from docker import DockerClient
from docker.errors import DockerException

from pytmbot.exceptions import DockerConnectionError
from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.utils import sanitize_exception


class DockerAdapter:
    """
    Docker interaction wrapper with secure defaults and contextual logging.
    """

    def __init__(self) -> None:
        if not hasattr(settings, "docker") or not settings.docker.host:
            raise ValueError("Docker configuration is missing or invalid")

        self._docker_url: str = str(settings.docker.host[0])
        self._client: Optional[DockerClient] = None
        self._session_id: str = str(uuid.uuid4())
        self._start_time: datetime = datetime.now()
        self._log = Logger()

        # Initialize base context for all operations
        self._base_context = {
            "action": "docker_adapter",
            "session_id": self._session_id,
            "docker_url": self._docker_url,
        }

        # Security warning for HTTP connections
        if self._docker_url.startswith("http://"):
            warnings.warn(
                "Using unencrypted HTTP connection to Docker daemon.",
                RuntimeWarning,
            )
            self._log.warning(
                "Insecure Docker connection detected",
                docker_url=self._docker_url,
                **self._base_context,
            )

        self._log.debug("DockerAdapter initialized", **self._base_context)

    @cached_property
    def _timeout_config(self) -> dict[str, int]:
        """Get timeout configuration for Docker client."""
        return {"timeout": getattr(settings.docker, "timeout", 30)}

    def _get_context(
        self, action: str, extra: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build context dictionary for logging with consistent structure."""
        context = {
            **self._base_context,
            "action": action,
            "uptime": f"{(datetime.now() - self._start_time).total_seconds():.2f}s",
        }

        if extra:
            context.update(extra)

        return context

    def _create_client(self) -> DockerClient:
        """Create and configure Docker client with appropriate security settings."""
        context = self._get_context("client_creation")

        try:
            tls_config = None
            if self._docker_url.startswith("https://"):
                tls_config = docker.tls.TLSConfig(
                    client_cert=(
                        getattr(settings.docker, "cert_path", None),
                        getattr(settings.docker, "key_path", None),
                    ),
                    verify=getattr(settings.docker, "ca_cert", True),
                )

            client = docker.DockerClient(
                base_url=self._docker_url, tls=tls_config, **self._timeout_config
            )

            # Test connection
            client.ping()

            self._log.debug(
                "Docker client created successfully",
                tls_enabled=bool(tls_config),
                timeout=self._timeout_config.get("timeout"),
                **context,
            )

            return client

        except DockerException as e:
            self._log.error(
                "Docker client creation failed", error=sanitize_exception(e), **context
            )
            raise DockerConnectionError(f"Failed to create Docker client: {e}") from e

    def __enter__(self) -> DockerClient:
        """Enter Docker context manager - create and return client."""
        context = self._get_context("context_enter")

        try:
            self._client = self._create_client()
            # Only log at debug level - context entry is routine
            self._log.debug("Docker context entered", **context)
            return self._client

        except Exception as e:
            self._log.error(
                "Failed to enter Docker context", error=sanitize_exception(e), **context
            )
            raise DockerConnectionError(f"Docker client init failed: {e}") from e

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit Docker context manager - cleanup client connection."""
        context = self._get_context("context_exit")

        # Clean up client connection
        if self._client is not None:
            with suppress(DockerException):
                self._client.close()
            self._client = None

        # Log exceptions at appropriate level
        if exc_type:
            # Only log at info level if it's an actual error, not routine cleanup
            if issubclass(exc_type, (DockerException, DockerConnectionError)):
                self._log.error(
                    "Docker context exited with Docker-related exception",
                    exception_type=exc_type.__name__,
                    exception_message=str(exc_val),
                    **context,
                )
            else:
                # Other exceptions might be less critical - log at debug
                self._log.debug(
                    "Docker context exited with exception",
                    exception_type=exc_type.__name__,
                    exception_message=str(exc_val),
                    **context,
                )
        else:
            # Normal exit - only debug level to reduce noise
            self._log.debug("Docker context exited normally", **context)

    def health_check(self) -> bool:
        """Perform health check on Docker connection."""
        context = self._get_context("health_check")

        try:
            with self:
                # Connection is tested in _create_client via ping()
                self._log.debug("Docker health check passed", **context)
                return True

        except DockerConnectionError:
            self._log.warning("Docker health check failed", **context)
            return False
        except Exception as e:
            self._log.error(
                "Docker health check encountered unexpected error",
                error=sanitize_exception(e),
                **context,
            )
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get current Docker adapter status information."""
        return {
            "session_id": self._session_id,
            "docker_url": self._docker_url,
            "uptime": f"{(datetime.now() - self._start_time).total_seconds():.2f}s",
            "client_active": self._client is not None,
            "secure_connection": self._docker_url.startswith("https://"),
        }
