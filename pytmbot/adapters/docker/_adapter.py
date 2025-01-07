import uuid
import warnings
from contextlib import suppress
from datetime import datetime
from functools import cached_property
from tracemalloc import Traceback
from typing import Optional, Type, Any, Dict

import docker
from docker import DockerClient
from docker.errors import DockerException

from pytmbot.exceptions import DockerConnectionError
from pytmbot.globals import settings
from pytmbot.logs import Logger

logger = Logger()


class DockerAdapter:
    """
    Class to handle Docker API interactions with enhanced security and error handling.

    Implements context manager protocol for safe resource management.
    Uses cached properties and strong typing for better performance and safety.
    """

    def __init__(self) -> None:
        """
        Initialize the DockerAdapter with configuration validation.

        Raises:
            ValueError: If Docker URL is not properly configured
            warnings.Warning: If using potentially unsafe Docker configuration
        """
        if not hasattr(settings, 'docker') or not settings.docker.host:
            raise ValueError("Docker configuration is missing or invalid")

        self._docker_url: str = str(settings.docker.host[0])
        self._client: Optional[DockerClient] = None
        self._session_id: str = str(uuid.uuid4())
        self._start_time: datetime = datetime.now()

        # Security check for non-TLS connections
        if self._docker_url.startswith('http://'):
            warnings.warn(
                "Using unencrypted HTTP connection to Docker daemon. "
                "This is potentially unsafe. Consider using HTTPS.",
                RuntimeWarning
            )

        # Log initialization with context
        self._log_with_context("Docker adapter initialized", level="debug")

    @cached_property
    def _timeout_config(self) -> dict[str, int]:
        """Get timeout configuration with safe defaults."""
        return {
            'timeout': getattr(settings.docker, 'timeout', 30),
        }

    def _get_log_context(self, additional_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create a context dictionary for logging.

        Args:
            additional_context: Additional context to include in the log

        Returns:
            Dict containing all context information
        """
        context = {
            'session_id': self._session_id,
            'docker_url': self._docker_url,
            'uptime': (datetime.now() - self._start_time).total_seconds(),
        }

        if additional_context:
            context.update(additional_context)

        return context

    def _log_with_context(
            self,
            message: str,
            level: str = "debug",
            additional_context: Optional[Dict[str, Any]] = None,
            error: Optional[Exception] = None
    ) -> None:
        """
        Log a message with context information.

        Args:
            message: The log message
            level: Logging level (debug, info, warning, error, critical)
            additional_context: Additional context to include
            error: Exception object if logging an error
        """
        context = self._get_log_context(additional_context)

        if error:
            context['error'] = {
                'type': type(error).__name__,
                'message': str(error),
                'traceback': getattr(error, '__traceback__', None)
            }

        log_func = getattr(logger, level)
        log_func(message, context=context)

    def _create_client(self) -> DockerClient:
        """
        Create a new Docker client with proper security configurations.

        Returns:
            DockerClient: Configured Docker client instance

        Raises:
            DockerConnectionError: If client creation fails
        """
        try:
            tls_config = None
            if self._docker_url.startswith('https://'):
                tls_config = docker.tls.TLSConfig(
                    client_cert=(
                        getattr(settings.docker, 'cert_path', None),
                        getattr(settings.docker, 'key_path', None)
                    ),
                    verify=getattr(settings.docker, 'ca_cert', True)
                )

            client = docker.DockerClient(
                base_url=self._docker_url,
                tls=tls_config,
                **self._timeout_config
            )

            # Verify connection
            client.ping()

            self._log_with_context(
                "Docker client created successfully",
                level="info",
                additional_context={'tls_enabled': bool(tls_config)}
            )

            return client

        except DockerException as e:
            self._log_with_context(
                "Failed to create Docker client",
                level="error",
                error=e
            )
            raise DockerConnectionError(f"Failed to create Docker client: {e}") from e

    def __enter__(self) -> DockerClient:
        """
        Enter the context manager with enhanced error handling.

        Returns:
            DockerClient: Initialized Docker client

        Raises:
            DockerConnectionError: If client initialization fails
        """
        try:
            self._client = self._create_client()

            self._log_with_context(
                "Entered Docker client context",
                level="debug"
            )

            return self._client

        except Exception as e:
            self._log_with_context(
                "Failed to initialize Docker client in context manager",
                level="error",
                error=e
            )
            raise DockerConnectionError(f"Docker client initialization failed: {e}") from e

    def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[Traceback]
    ) -> None:
        """
        Exit the context manager with graceful cleanup.

        Args:
            exc_type: Exception type if an error occurred
            exc_val: Exception instance if an error occurred
            exc_tb: Traceback if an error occurred
        """
        if self._client is not None:
            context = {
                'had_exception': exc_type is not None,
                'exception_type': exc_type.__name__ if exc_type else None,
                'exception_value': str(exc_val) if exc_val else None
            }

            with suppress(DockerException):
                self._client.close()

            self._client = None

            self._log_with_context(
                "Exited Docker client context",
                level="debug",
                additional_context=context
            )
