#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from docker import DockerClient

from pytmbot.adapters.docker._adapter import DockerAdapter


@contextmanager
def docker_client_context() -> Iterator[DockerClient]:
    """
    Provide a managed Docker client via a single public gateway.

    This hides direct usage of the internal adapter implementation and ensures
    the underlying connection is closed deterministically after use.
    """
    adapter = DockerAdapter()
    try:
        with adapter as client:
            yield client
    finally:
        adapter.close()
