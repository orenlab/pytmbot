from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest
from docker.errors import NotFound
from docker.models.containers import Container

import pytmbot.adapters.docker.utils as docker_utils
from pytmbot.exceptions import ContainerNotFoundError, DockerOperationException


@dataclass
class _ImageStub:
    tags: list[str]
    short_id: str = "sha256:abc123"


class _ContainerStub:
    def __init__(self, *, status: str = "running", name: str = "/test") -> None:
        self.id = "1234567890abcdef"
        self.short_id = "1234567890ab"
        self.name = name
        self.status = status
        self.image = _ImageStub(tags=["repo:tag"])
        self.attrs = {
            "Created": "2026-01-01T00:00:00Z",
            "State": {
                "ExitCode": 0,
                "Pid": 123,
                "StartedAt": "2026-01-01T00:00:01Z",
                "FinishedAt": "2026-01-01T00:00:02Z",
            },
            "HostConfig": {"Memory": 1024 * 1024 * 1024},
        }
        self.ports: dict[str, str] = {}
        self.labels: dict[str, str] = {}

    def stats(self, *, stream: bool, one_shot: bool = False) -> dict[str, object]:
        if stream:
            return {}
        if one_shot:
            return {"memory_stats": {"usage": 1024, "limit": 2048}}
        return {"memory_stats": {"usage": 1024, "limit": 2048}}


def test_container_state_helpers_and_validation() -> None:
    running = docker_utils.ContainerState.from_str("RUNNING")
    assert running is docker_utils.ContainerState.RUNNING
    assert running.is_active is True
    assert running.is_stopped is False

    stopped = docker_utils.ContainerState.STOPPED
    assert stopped.is_stopped is True
    assert stopped.is_transitional is False

    with pytest.raises(ValueError):
        docker_utils.ContainerState.from_str("invalid-state")


def test_state_check_config_validation_and_clamping() -> None:
    config = docker_utils.StateCheckConfig(max_attempts=2, interval=100.0)
    assert config.interval == docker_utils.MAX_STATE_CHECK_INTERVAL

    with pytest.raises(ValueError):
        docker_utils.StateCheckConfig(max_attempts=0)
    with pytest.raises(ValueError):
        docker_utils.StateCheckConfig(interval=0.0)


def test_container_state_cache_expiry_and_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(docker_utils.time, "time", lambda: clock[0])

    cache = docker_utils.ContainerStateCache(ttl=1.0, max_size=2)
    cache.set("c1", "running")
    assert cache.get("c1") == "running"
    assert cache.get_stats()["fresh_entries"] == 1

    clock[0] = 102.0
    assert cache.get("c1") is None
    assert cache.get_stats()["fresh_entries"] == 0


def test_get_container_stats_snapshot_handles_one_shot_and_iterator() -> None:
    class _IteratorContainer(_ContainerStub):
        def stats(self, *, stream: bool, one_shot: bool = False) -> Iterator[dict[str, object]]:  # type: ignore[override]
            del stream, one_shot
            return iter([{"memory_stats": {"usage": 5, "limit": 10}}])

    iterator_container = cast(Container, _IteratorContainer())
    snapshot = docker_utils.get_container_stats_snapshot(iterator_container)
    assert snapshot["memory_stats"]["usage"] == 5


def test_get_container_stats_snapshot_handles_errors() -> None:
    class _BrokenContainer(_ContainerStub):
        def stats(self, *, stream: bool, one_shot: bool = False) -> dict[str, object]:  # type: ignore[override]
            del stream, one_shot
            raise RuntimeError("boom")

    assert docker_utils.get_container_stats_snapshot(cast(Container, _BrokenContainer())) == {}


def test_check_container_state_reaches_target(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter(["created", "restarting", "running"])
    monkeypatch.setattr(docker_utils, "sleep", lambda _interval: None)
    monkeypatch.setattr(
        docker_utils,
        "get_container_state",
        lambda _container_name, docker_client=None: next(states),
    )

    result = docker_utils.check_container_state(
        "abc123",
        target_state="running",
        config=docker_utils.StateCheckConfig(max_attempts=3, interval=0.5),
    )
    assert result == docker_utils.ContainerState.RUNNING


def test_check_container_state_returns_none_on_unavailable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_utils,
        "get_container_state",
        lambda _container_name, docker_client=None: None,
    )
    result = docker_utils.check_container_state(
        "abc123",
        config=docker_utils.StateCheckConfig(max_attempts=1, interval=0.5),
    )
    assert result is None


def test_with_operation_logging_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_utils,
        "settings",
        SimpleNamespace(docker=SimpleNamespace(debug_docker_client=False)),
    )

    @docker_utils.with_operation_logging("op_success")
    def _ok(value: int) -> list[int]:
        return [value]

    @docker_utils.with_operation_logging("op_fail")
    def _fail() -> int:
        raise RuntimeError("fail")

    assert _ok(2) == [2]
    with pytest.raises(RuntimeError):
        _fail()


def test_get_container_state_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    docker_utils.clear_state_cache()
    calls = {"count": 0}

    def _get_container(container_id: str, docker_client: object | None = None) -> Container:
        del docker_client
        calls["count"] += 1
        return cast(Container, _ContainerStub(status="running", name=f"/{container_id}"))

    monkeypatch.setattr(docker_utils, "get_container_safely", _get_container)
    first = docker_utils.get_container_state("cid1234")
    second = docker_utils.get_container_state("cid1234")
    assert first == "running"
    assert second == "running"
    assert calls["count"] == 1


def test_get_container_safely_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ContainersAPI:
        def __init__(self, result: object) -> None:
            self._result = result

        def get(self, _container_id: str) -> Container:
            if isinstance(self._result, Exception):
                raise self._result
            return cast(Container, self._result)

    container = cast(Container, _ContainerStub())

    client = SimpleNamespace(containers=_ContainersAPI(container))
    resolved = docker_utils.get_container_safely("cid1234", docker_client=client)
    assert resolved is container

    with pytest.raises(ContainerNotFoundError):
        docker_utils.get_container_safely(
            "cid1234", docker_client=SimpleNamespace(containers=_ContainersAPI(NotFound("missing")))
        )

    with pytest.raises(DockerOperationException):
        docker_utils.get_container_safely(
            "cid1234",
            docker_client=SimpleNamespace(containers=_ContainersAPI(RuntimeError("boom"))),
        )


def test_get_container_safely_uses_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    container = cast(Container, _ContainerStub())

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield SimpleNamespace(containers=SimpleNamespace(get=lambda _cid: container))

    monkeypatch.setattr(docker_utils, "docker_client_context", _client_context)
    resolved = docker_utils.get_container_safely("cid1234")
    assert resolved is container


def test_get_container_memory_stats_fallback_order(monkeypatch: pytest.MonkeyPatch) -> None:
    container = cast(Container, _ContainerStub(status="running"))
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider,
        "from_cgroups",
        lambda _cid: {"mem_usage": "1 MiB", "mem_limit": "2 MiB", "mem_percent": "50.0%"},
    )
    result = docker_utils.get_container_memory_stats(container)
    assert result["mem_percent"] == "50.0%"


def test_get_container_basic_info_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    container = cast(Container, _ContainerStub(status="running"))
    monkeypatch.setattr(
        docker_utils,
        "get_container_memory_stats",
        lambda _container: {"mem_usage": "3 MiB", "mem_limit": "4 MiB", "mem_percent": "75.0%"},
    )
    info = docker_utils.get_container_basic_info(container)
    assert info["name"] == "test"
    assert info["mem_percent"] == "75.0%"

    class _BadContainer(_ContainerStub):
        @property
        def name(self) -> str:  # type: ignore[override]
            raise RuntimeError("bad")

        @name.setter
        def name(self, value: str) -> None:
            del value
            return

    bad = cast(Container, _BadContainer())
    minimal = docker_utils.get_container_basic_info(bad)
    assert "status" in minimal


def test_sanitize_and_validate_helpers() -> None:
    sanitized = docker_utils.sanitize_kwargs_for_logging(
        {
            "password": "secret",
            "token_value": "ABCDEF1234567890ABCDEF",
            "plain": "ok",
            "nested": {"api_key": "x"},
            "big_list": list(range(20)),
        }
    )
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"
    assert sanitized["plain"] == "ok"

    context = docker_utils.build_container_context("cid1234", "action", token="secret")
    assert context["container_id"] == "cid1234"
    assert context["token"] == "[REDACTED]"

    rename = docker_utils.validate_container_operation_params(
        "cid1234",
        "rename",
        new_container_name="new-name",
    )
    assert rename["new_container_name"] == "new-name"

    restart = docker_utils.validate_container_operation_params(
        "cid1234",
        "restart",
        timeout=5,
    )
    assert restart["timeout"] == 5

    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params("abc", "rename")


def test_operation_tracker_history_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = docker_utils.ContainerOperationTracker()
    clock = [100.0]
    monkeypatch.setattr(docker_utils.time, "time", lambda: clock[0])

    tracker.record_operation("cid1234", "restart")
    clock[0] = 120.0
    tracker.record_operation("cid1234", "restart")
    history = tracker.get_recent_operations("cid1234", since_seconds=3600)

    assert len(history) == 1
    assert history[0]["operation"] == "restart"
    assert history[0]["count"] == 2

    tracker.clear()
    assert tracker.get_recent_operations("cid1234") == []
