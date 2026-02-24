from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from pytmbot.adapters.docker.client import (
    docker_client_context,
    reset_docker_client_context,
)


@dataclass
class _DummyClient:
    ok: bool = True


class _DummyAdapter:
    def __init__(self) -> None:
        self.closed = False
        self.client = _DummyClient()

    def __enter__(self) -> _DummyClient:
        return self.client

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: Any | None,
    ) -> None:
        return

    def close(self) -> None:
        self.closed = True


def test_docker_client_context_yields_client_without_closing_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_docker_client_context()
    adapter = _DummyAdapter()
    monkeypatch.setattr(
        "pytmbot.adapters.docker.client.DockerAdapter",
        lambda: adapter,
    )

    with docker_client_context() as client:
        assert client.ok is True

    assert adapter.closed is False
    reset_docker_client_context()


def test_docker_client_context_does_not_close_adapter_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_docker_client_context()
    adapter = _DummyAdapter()
    monkeypatch.setattr(
        "pytmbot.adapters.docker.client.DockerAdapter",
        lambda: adapter,
    )

    with pytest.raises(RuntimeError):
        with docker_client_context():
            raise RuntimeError("boom")

    assert adapter.closed is False
    reset_docker_client_context()


def test_reset_docker_client_context_closes_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_docker_client_context()
    adapter = _DummyAdapter()
    monkeypatch.setattr(
        "pytmbot.adapters.docker.client.DockerAdapter",
        lambda: adapter,
    )

    with docker_client_context() as client:
        assert client.ok is True

    reset_docker_client_context()
    assert adapter.closed is True
