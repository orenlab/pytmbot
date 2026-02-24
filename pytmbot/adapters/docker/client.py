#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock, local

from docker import DockerClient

from pytmbot.adapters.docker._adapter import DockerAdapter

_adapter_state = local()
_adapter_lock = RLock()


def _get_thread_adapter() -> DockerAdapter:
    """Get or create thread-local DockerAdapter instance."""
    with _adapter_lock:
        adapter = getattr(_adapter_state, "adapter", None)
        if adapter is None:
            adapter = DockerAdapter()
            _adapter_state.adapter = adapter
        return adapter


def reset_docker_client_context() -> None:
    """Reset and close current thread DockerAdapter (mainly for tests/shutdown)."""
    with _adapter_lock:
        adapter = getattr(_adapter_state, "adapter", None)
        if adapter is not None:
            adapter.close()
            delattr(_adapter_state, "adapter")


@contextmanager
def docker_client_context() -> Iterator[DockerClient]:
    """
    Provide a managed Docker client via a single public gateway.

    The gateway reuses a thread-local adapter to avoid repeated adapter creation
    overhead while still delegating connection lifecycle checks to DockerAdapter.
    """
    adapter = _get_thread_adapter()
    with adapter as client:
        yield client
