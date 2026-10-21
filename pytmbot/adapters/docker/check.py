#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

# Docker API check behind `entrypoint.sh --check-docker`:
# ``python -m pytmbot.adapters.docker.check``.
#
# Exit codes: 0 the Docker API answered a ping, 1 it did not. With a config file the
# bot's own Docker client and settings are used (host, TLS, timeout); without one, as
# in the documented `docker run ... --check-docker`, the default local socket is pinged.
# Nothing that loads the settings is imported unless the config file exists.

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Final, NoReturn

from pytmbot.settings import config_file_exists

DEFAULT_DOCKER_URL: Final[str] = "unix:///var/run/docker.sock"
PING_TIMEOUT_SECONDS: Final[int] = 5
_MAX_REASON_LENGTH: Final[int] = 300


@dataclass(frozen=True, slots=True)
class DockerCheckResult:
    ok: bool
    target: str
    detail: str


def _describe(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    return text[:_MAX_REASON_LENGTH]


def _check_with_bot_settings() -> DockerCheckResult:
    """Ping through the bot's Docker client gateway, as the running bot would."""
    from pytmbot.adapters.docker.client import (
        docker_client_context,
        reset_docker_client_context,
    )
    from pytmbot.globals import settings
    from pytmbot.utils import sanitize_exception

    hosts = getattr(getattr(settings, "docker", None), "host", None) or ["?"]
    target = f"{hosts[0]} from the config file"
    try:
        with docker_client_context() as client:
            client.ping()
            version = client.version()
    except Exception as error:
        return DockerCheckResult(False, target, sanitize_exception(error))
    finally:
        reset_docker_client_context()
    return DockerCheckResult(True, target, f"Docker {version.get('Version', '?')}")


def _check_default_socket() -> DockerCheckResult:
    """Ping the default local socket when there is no config file."""
    from docker.client import DockerClient

    try:
        client = DockerClient(base_url=DEFAULT_DOCKER_URL, timeout=PING_TIMEOUT_SECONDS)
    except Exception as error:
        return DockerCheckResult(False, DEFAULT_DOCKER_URL, _describe(error))
    try:
        client.ping()
        version = client.version()
    except Exception as error:
        return DockerCheckResult(False, DEFAULT_DOCKER_URL, _describe(error))
    finally:
        client.close()
    return DockerCheckResult(
        True, DEFAULT_DOCKER_URL, f"Docker {version.get('Version', '?')}"
    )


def check_docker_api() -> DockerCheckResult:
    """Return whether the Docker API answers, and how it was reached."""
    if config_file_exists():
        return _check_with_bot_settings()
    return _check_default_socket()


def main() -> NoReturn:
    result = check_docker_api()
    if result.ok:
        print(f"Docker API reachable ({result.target}): {result.detail}")
        sys.exit(0)
    print(
        f"Docker API not reachable ({result.target}): {result.detail}",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
