from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from pytmbot.adapters.docker import check
from pytmbot.adapters.docker import client as client_module
from pytmbot.exceptions import DockerConnectionError


class _FakeDockerClient:
    def __init__(self, ping_error: Exception | None = None) -> None:
        self.ping_error = ping_error
        self.closed = False

    def ping(self) -> bool:
        if self.ping_error is not None:
            raise self.ping_error
        return True

    def version(self) -> dict[str, str]:
        return {"Version": "29.0.1"}

    def close(self) -> None:
        self.closed = True


def _without_config(
    monkeypatch: pytest.MonkeyPatch, client: _FakeDockerClient | Exception
) -> dict[str, object]:
    monkeypatch.setattr(check, "config_file_exists", lambda: False)
    created: dict[str, object] = {}

    def factory(**kwargs: object) -> _FakeDockerClient:
        created.update(kwargs)
        if isinstance(client, Exception):
            raise client
        return client

    monkeypatch.setattr("docker.client.DockerClient", factory)
    return created


def _with_config(
    monkeypatch: pytest.MonkeyPatch, client: _FakeDockerClient
) -> list[str]:
    monkeypatch.setattr(check, "config_file_exists", lambda: True)
    events: list[str] = []

    @contextmanager
    def fake_context() -> Iterator[_FakeDockerClient]:
        events.append("enter")
        yield client

    monkeypatch.setattr(client_module, "docker_client_context", fake_context)
    monkeypatch.setattr(
        client_module, "reset_docker_client_context", lambda: events.append("reset")
    )
    return events


def test_without_config_pings_the_default_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeDockerClient()
    created = _without_config(monkeypatch, client)

    result = check.check_docker_api()

    assert result == check.DockerCheckResult(
        True, check.DEFAULT_DOCKER_URL, "Docker 29.0.1"
    )
    assert created == {
        "base_url": check.DEFAULT_DOCKER_URL,
        "timeout": check.PING_TIMEOUT_SECONDS,
    }
    assert client.closed is True


def test_without_config_reports_a_failed_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeDockerClient(PermissionError(13, "Permission denied"))
    _without_config(monkeypatch, client)

    result = check.check_docker_api()

    assert result.ok is False
    assert result.detail == "PermissionError: [Errno 13] Permission denied"
    assert client.closed is True


def test_without_config_reports_a_client_that_cannot_be_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_config(monkeypatch, RuntimeError("x" * 1000))

    result = check.check_docker_api()

    assert result.ok is False
    assert result.detail.startswith("RuntimeError: x")
    assert len(result.detail) == 300


def test_with_config_uses_the_bots_docker_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _with_config(monkeypatch, _FakeDockerClient())

    result = check.check_docker_api()

    assert result.ok is True
    assert result.target == "unix:///var/run/docker.sock from the config file"
    assert result.detail == "Docker 29.0.1"
    assert events == ["enter", "reset"]


def test_with_config_reports_an_unavailable_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = _FakeDockerClient(DockerConnectionError("Docker is unavailable"))
    events = _with_config(monkeypatch, unavailable)

    result = check.check_docker_api()

    assert result.ok is False
    assert "Docker is unavailable" in result.detail
    assert events == ["enter", "reset"]


@pytest.mark.parametrize(
    ("result", "code", "stream", "text"),
    [
        (
            check.DockerCheckResult(True, "unix:///x", "Docker 29.0.1"),
            0,
            "out",
            "Docker API reachable (unix:///x): Docker 29.0.1",
        ),
        (
            check.DockerCheckResult(False, "unix:///x", "PermissionError: denied"),
            1,
            "err",
            "Docker API not reachable (unix:///x): PermissionError: denied",
        ),
    ],
)
def test_main_exit_code_and_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: check.DockerCheckResult,
    code: int,
    stream: str,
    text: str,
) -> None:
    monkeypatch.setattr(check, "check_docker_api", lambda: result)

    with pytest.raises(SystemExit) as exit_info:
        check.main()

    assert exit_info.value.code == code
    captured = capsys.readouterr()
    assert text in (captured.out if stream == "out" else captured.err)
