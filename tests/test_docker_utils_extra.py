from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest
from docker.errors import NotFound
from docker.models.containers import Container

import pytmbot.adapters.docker.utils as docker_utils
from pytmbot.exceptions import (
    ContainerNotFoundError,
    DockerConnectionError,
    DockerOperationException,
)

type _StatsValue = int | dict[str, int]
type _StatsDict = dict[str, _StatsValue]
type _ObjectDict = dict[str, object]


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

    def stats(
        self, *, stream: bool, one_shot: bool = False
    ) -> _StatsDict | Iterator[_StatsDict]:
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


def test_container_state_cache_expiry_and_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr("pytmbot.adapters.docker.utils.time.time", lambda: clock[0])

    cache = docker_utils.ContainerStateCache(ttl=1.0, max_size=2)
    cache.set("c1", "running")
    assert cache.get("c1") == "running"
    assert cache.get_stats()["fresh_entries"] == 1

    clock[0] = 102.0
    assert cache.get("c1") is None
    assert cache.get_stats()["fresh_entries"] == 0


def test_get_container_stats_snapshot_handles_one_shot_and_iterator() -> None:
    class _IteratorContainer(_ContainerStub):
        def stats(
            self, *, stream: bool, one_shot: bool = False
        ) -> Iterator[_StatsDict]:
            del stream, one_shot
            return iter([{"memory_stats": {"usage": 5, "limit": 10}}])

    iterator_container = cast(Container, _IteratorContainer())
    snapshot = docker_utils.get_container_stats_snapshot(iterator_container)
    memory_stats = snapshot.get("memory_stats")
    assert isinstance(memory_stats, dict)
    assert memory_stats.get("usage") == 5


def test_get_container_stats_snapshot_handles_errors() -> None:
    class _BrokenContainer(_ContainerStub):
        def stats(self, *, stream: bool, one_shot: bool = False) -> _StatsDict:
            del stream, one_shot
            raise RuntimeError("boom")

    assert (
        docker_utils.get_container_stats_snapshot(cast(Container, _BrokenContainer()))
        == {}
    )


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

    def _get_container(
        container_id: str, docker_client: SimpleNamespace | None = None
    ) -> Container:
        del docker_client
        calls["count"] += 1
        return cast(
            Container, _ContainerStub(status="running", name=f"/{container_id}")
        )

    monkeypatch.setattr(docker_utils, "get_container_safely", _get_container)
    first = docker_utils.get_container_state("cid1234")
    second = docker_utils.get_container_state("cid1234")
    assert first == "running"
    assert second == "running"
    assert calls["count"] == 1


def test_get_container_safely_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ContainersAPI:
        def __init__(self, result: Container | Exception) -> None:
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
            "cid1234",
            docker_client=SimpleNamespace(
                containers=_ContainersAPI(NotFound("missing"))
            ),
        )

    with pytest.raises(DockerOperationException):
        docker_utils.get_container_safely(
            "cid1234",
            docker_client=SimpleNamespace(
                containers=_ContainersAPI(RuntimeError("boom"))
            ),
        )

    with pytest.raises(DockerConnectionError):
        docker_utils.get_container_safely(
            "cid1234",
            docker_client=SimpleNamespace(
                containers=_ContainersAPI(DockerConnectionError("docker unavailable"))
            ),
        )


def test_get_container_safely_uses_context_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = cast(Container, _ContainerStub())

    @contextmanager
    def _client_context() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(containers=SimpleNamespace(get=lambda _cid: container))

    monkeypatch.setattr(docker_utils, "docker_client_context", _client_context)
    resolved = docker_utils.get_container_safely("cid1234")
    assert resolved is container


def test_get_container_memory_stats_fallback_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = cast(Container, _ContainerStub(status="running"))
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider,
        "from_cgroups",
        lambda _cid: {
            "mem_usage": "1 MiB",
            "mem_limit": "2 MiB",
            "mem_percent": "50.0%",
        },
    )
    result = docker_utils.get_container_memory_stats(container)
    assert result["mem_percent"] == "50.0%"


def test_get_container_basic_info_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    container = cast(Container, _ContainerStub(status="running"))
    monkeypatch.setattr(
        docker_utils,
        "get_container_memory_stats",
        lambda _container: {
            "mem_usage": "3 MiB",
            "mem_limit": "4 MiB",
            "mem_percent": "75.0%",
        },
    )
    info = docker_utils.get_container_basic_info(container)
    assert info["name"] == "test"
    assert info["mem_percent"] == "75.0%"

    class _BadContainer(_ContainerStub):
        @property
        def name(self) -> str:
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
    nested = sanitized.get("nested")
    assert isinstance(nested, dict)
    assert nested.get("api_key") == "[REDACTED]"
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
    monkeypatch.setattr("pytmbot.adapters.docker.utils.time.time", lambda: clock[0])

    tracker.record_operation("cid1234", "restart")
    clock[0] = 120.0
    tracker.record_operation("cid1234", "restart")
    history = tracker.get_recent_operations("cid1234", since_seconds=3600)

    assert len(history) == 1
    assert history[0]["operation"] == "restart"
    assert history[0]["count"] == 2

    tracker.clear()
    assert tracker.get_recent_operations("cid1234") == []


def test_container_state_and_decorator_validation_errors() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        docker_utils.ContainerState.from_str("")

    with pytest.raises(ValueError, match="non-empty string"):
        docker_utils.ContainerState.from_str(cast(str, None))

    with pytest.raises(ValueError, match="operation_name"):
        docker_utils.with_operation_logging("")

    with pytest.raises(ValueError, match="slow_threshold"):
        docker_utils.with_operation_logging("op", slow_threshold=0)


def test_state_cache_cleanup_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("pytmbot.adapters.docker.utils.time.time", lambda: clock[0])
    cache = docker_utils.ContainerStateCache(ttl=1.0, max_size=1)

    cache._cache["old"] = docker_utils.CacheEntry(data="running", timestamp=90.0)  # noqa: SLF001
    cache.set("new", "exited")
    assert "old" not in cache._cache  # noqa: SLF001
    assert cache.get("new") == "exited"


def test_memory_stats_provider_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    path_map = {
        "/sys/fs/cgroup/system.slice/docker-cid.scope/memory.current": "2048",
        "/sys/fs/cgroup/system.slice/docker-cid.scope/memory.max": "4096",
        "/sys/fs/cgroup/memory/docker/cid/memory.usage_in_bytes": "1024",
        "/sys/fs/cgroup/memory/docker/cid/memory.limit_in_bytes": "2048",
    }
    monkeypatch.setattr(
        "pytmbot.adapters.docker.utils.Path.exists",
        lambda self: str(self) in path_map,
    )
    monkeypatch.setattr(
        "pytmbot.adapters.docker.utils.Path.read_text",
        lambda self: path_map[str(self)],
    )

    v2 = docker_utils.MemoryStatsProvider.from_cgroups("cid")
    assert v2 and v2["mem_usage"]

    path_map["/sys/fs/cgroup/system.slice/docker-cid.scope/memory.current"] = (
        "broken-number"
    )
    v1 = docker_utils.MemoryStatsProvider.from_cgroups("cid")
    assert v1 and v1["mem_limit"] == "2.0 KiB"

    path_map.clear()
    path_map.update(
        {
            "/sys/fs/cgroup/memory/docker/cid/memory.usage_in_bytes": "broken",
            "/sys/fs/cgroup/memory/docker/cid/memory.limit_in_bytes": "broken",
        }
    )
    assert docker_utils.MemoryStatsProvider.from_cgroups("cid") is None

    monkeypatch.setattr(
        "pytmbot.adapters.docker.utils.Path.exists",
        lambda self: str(self).startswith("/sys/fs/cgroup/"),
    )
    monkeypatch.setattr(
        "pytmbot.adapters.docker.utils.Path.read_text",
        lambda self: (_ for _ in ()).throw(RuntimeError("fs failed")),
    )
    assert docker_utils.MemoryStatsProvider.from_cgroups("cid") is None

    run_result = SimpleNamespace(returncode=0, stdout="1.0MiB / 2.0MiB,50.0%")
    monkeypatch.setattr(
        "pytmbot.adapters.docker.utils.subprocess.run", lambda *a, **k: run_result
    )
    cli_stats = docker_utils.MemoryStatsProvider.from_docker_cli("cid")
    assert cli_stats and cli_stats["mem_percent"] == "50.0%"

    monkeypatch.setattr(
        "pytmbot.adapters.docker.utils.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="docker", timeout=1.0)
        ),
    )
    assert docker_utils.MemoryStatsProvider.from_docker_cli("cid") is None

    inspect_container = cast(Container, _ContainerStub())
    inspect_container.attrs["HostConfig"]["Memory"] = 1024
    inspect_with_limit = docker_utils.MemoryStatsProvider.from_inspect(
        inspect_container
    )
    assert inspect_with_limit and inspect_with_limit["mem_limit"] == "1.0 KiB"

    inspect_container.attrs["HostConfig"]["Memory"] = 0
    inspect_stats = docker_utils.MemoryStatsProvider.from_inspect(inspect_container)
    assert inspect_stats and inspect_stats["mem_limit"] == "No Limit"

    inspect_container.attrs = cast(dict[str, str], None)
    assert docker_utils.MemoryStatsProvider.from_inspect(inspect_container) is None

    class _BrokenStatsContainer(_ContainerStub):
        def stats(self, *, stream: bool, one_shot: bool = False) -> _StatsDict:
            del stream, one_shot
            raise RuntimeError("no stats")

    assert docker_utils.MemoryStatsProvider.from_container_stats(
        cast(Container, _BrokenStatsContainer())
    ) == {"mem_usage": "N/A", "mem_limit": "N/A", "mem_percent": "N/A"}

    good_stats = docker_utils.MemoryStatsProvider.from_container_stats(
        cast(Container, _ContainerStub())
    )
    assert good_stats and good_stats["mem_percent"] == "50.0%"

    monkeypatch.setattr(
        docker_utils,
        "get_container_stats_snapshot",
        lambda _container: (_ for _ in ()).throw(RuntimeError("snapshot fail")),
    )
    assert (
        docker_utils.MemoryStatsProvider.from_container_stats(
            cast(Container, _ContainerStub())
        )
        is None
    )


def test_stats_snapshot_and_state_check_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TypeErrorContainer(_ContainerStub):
        def stats(self, *, stream: bool, one_shot: bool = False) -> _StatsDict:
            if one_shot:
                raise TypeError("one_shot unsupported")
            del stream
            return {"memory_stats": {"usage": 7, "limit": 14}}

    type_error_snapshot = docker_utils.get_container_stats_snapshot(
        cast(Container, _TypeErrorContainer())
    )
    type_error_memory_stats = type_error_snapshot.get("memory_stats")
    assert isinstance(type_error_memory_stats, dict)
    assert type_error_memory_stats.get("usage") == 7

    class _OneShotErrorContainer(_ContainerStub):
        def stats(self, *, stream: bool, one_shot: bool = False) -> _StatsDict:
            if one_shot:
                raise RuntimeError("one_shot disabled")
            del stream
            return {"memory_stats": {"usage": 9, "limit": 18}}

    one_shot_snapshot = docker_utils.get_container_stats_snapshot(
        cast(Container, _OneShotErrorContainer())
    )
    one_shot_memory_stats = one_shot_snapshot.get("memory_stats")
    assert isinstance(one_shot_memory_stats, dict)
    assert one_shot_memory_stats.get("usage") == 9

    with pytest.raises(ValueError):
        docker_utils.check_container_state("")

    default_result = docker_utils.check_container_state(
        "cid1234", target_state="running"
    )
    assert default_result == docker_utils.ContainerState.RUNNING

    monkeypatch.setattr(
        docker_utils, "ContainersState", SimpleNamespace(RUNNING="running")
    )
    with pytest.raises(ValueError):
        docker_utils.check_container_state("cid1234", target_state="exited")

    monkeypatch.setattr(
        docker_utils,
        "ContainersState",
        SimpleNamespace(RUNNING="running", EXITED="exited"),
    )
    monkeypatch.setattr(docker_utils, "sleep", lambda _interval: None)
    monkeypatch.setattr(
        docker_utils,
        "get_container_state",
        lambda _container_name, docker_client=None: "exited",
    )
    state = docker_utils.check_container_state(
        "cid1234",
        target_state="running",
        config=docker_utils.StateCheckConfig(max_attempts=1, interval=0.5),
    )
    assert state == docker_utils.ContainerState.EXITED

    monkeypatch.setattr(
        docker_utils,
        "get_container_state",
        lambda _container_name, docker_client=None: (_ for _ in ()).throw(
            RuntimeError("loop fail")
        ),
    )
    state_on_exception = docker_utils.check_container_state(
        "cid1234",
        target_state="running",
        config=docker_utils.StateCheckConfig(max_attempts=1, interval=0.5),
    )
    assert state_on_exception is None

    # Generic check_container_state error path.
    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            docker_utils.ContainerState,
            "from_str",
            classmethod(
                lambda cls, value: (_ for _ in ()).throw(RuntimeError("bad state"))
            ),
        )
        with pytest.raises(RuntimeError, match="bad state"):
            docker_utils.check_container_state("cid1234", target_state="running")

    # _execute_state_check_loop error retry path (attempt < max_attempts).
    attempts: Iterator[RuntimeError | str] = iter(
        [RuntimeError("transient"), "running"]
    )

    def _flaky_state(
        _container_name: str, docker_client: SimpleNamespace | None = None
    ) -> str:
        del docker_client
        next_value = next(attempts)
        if isinstance(next_value, Exception):
            raise next_value
        return next_value

    monkeypatch.setattr(docker_utils, "sleep", lambda _interval: None)
    monkeypatch.setattr(docker_utils, "get_container_state", _flaky_state)
    retried = docker_utils.check_container_state(
        "cid1234",
        target_state="running",
        config=docker_utils.StateCheckConfig(max_attempts=2, interval=0.5),
    )
    assert retried == docker_utils.ContainerState.RUNNING


def test_logging_helpers_and_get_container_state_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docker_utils,
        "settings",
        SimpleNamespace(docker=SimpleNamespace(debug_docker_client=True)),
    )

    @docker_utils.with_operation_logging("debug_op", slow_threshold=0.5)
    def _debug_ok() -> str:
        return "ok"

    assert _debug_ok() == "ok"

    context: _ObjectDict = {}
    docker_utils._log_operation_success("op", context, 1.0, [1], 0.5)  # noqa: SLF001
    assert context["result_size"] == 1
    docker_utils._log_operation_success("op", context, 0.3, {"a": 1}, 0.5)  # noqa: SLF001
    docker_utils._log_operation_success("op", context, 0.1, "x", 0.5)  # noqa: SLF001
    assert context["result_length"] == 1

    with pytest.raises(ValueError):
        docker_utils.get_container_state("")

    from pytmbot.exceptions import ErrorContext

    docker_utils.clear_state_cache()
    not_found = ContainerNotFoundError(
        ErrorContext(message="missing", error_code="DOCKER_001", metadata={})
    )
    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            docker_utils,
            "get_container_safely",
            lambda _container_id, docker_client=None: (_ for _ in ()).throw(not_found),
        )
        assert docker_utils.get_container_state("cid1234") is None

        local_patch.setattr(
            docker_utils,
            "get_container_safely",
            lambda _container_id, docker_client=None: (_ for _ in ()).throw(
                RuntimeError("state fail")
            ),
        )
        assert docker_utils.get_container_state("cid1234") is None

    with pytest.raises(ValueError):
        docker_utils.get_container_safely("")


def test_basic_info_sanitize_context_and_validation_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError):
        docker_utils.get_container_basic_info(cast(Container, None))

    running_container = cast(Container, _ContainerStub(status="running"))
    monkeypatch.setattr(
        docker_utils,
        "get_container_memory_stats",
        lambda _container: (_ for _ in ()).throw(RuntimeError("mem fail")),
    )
    info = docker_utils.get_container_basic_info(running_container)
    assert "mem_usage" not in info

    assert docker_utils.sanitize_kwargs_for_logging(cast(_ObjectDict, "bad")) == {}
    sanitized = docker_utils.sanitize_kwargs_for_logging(
        {
            "long_text": "x" * 250,
            "entropy": "abcdef0123456789ABCDEF0123456789",
            "small_list": [1, 2],
            "big_dict": {str(i): i for i in range(25)},
        }
    )
    long_text = sanitized.get("long_text")
    assert isinstance(long_text, str)
    assert "[TRUNCATED:" in long_text
    entropy = sanitized.get("entropy")
    assert isinstance(entropy, str)
    assert entropy.startswith("[REDACTED:")
    assert sanitized["small_list"] == [1, 2]
    assert sanitized["big_dict"] == "[DICT:25 keys]"

    with pytest.raises(ValueError):
        docker_utils.build_container_context("", "action")
    with pytest.raises(ValueError):
        docker_utils.build_container_context("cid", "")
    assert "size" in docker_utils.get_cache_stats()

    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params("", "start")
    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params("cid1234", "")
    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params("abc", "start")
    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params("x" * 65, "start")
    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params("cid1234", "rename")
    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params(
            "cid1234",
            "rename",
            new_container_name="x" * 65,
        )
    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params(
            "cid1234", "restart", timeout=-1
        )
    with pytest.raises(ValueError):
        docker_utils.validate_container_operation_params("cid1234", "stop", timeout=301)


def test_get_container_memory_stats_fallback_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running_from_stats = cast(Container, _ContainerStub(status="running"))
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider, "from_cgroups", lambda _cid: None
    )
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider,
        "from_container_stats",
        lambda _container: {
            "mem_usage": "10 MiB",
            "mem_limit": "20 MiB",
            "mem_percent": "50.0%",
        },
    )
    from_stats = docker_utils.get_container_memory_stats(running_from_stats)
    assert from_stats["mem_usage"] == "10 MiB"

    stopped_container = cast(Container, _ContainerStub(status="stopped"))
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider, "from_cgroups", lambda _cid: None
    )
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider,
        "from_inspect",
        lambda _container: {
            "mem_usage": "N/A",
            "mem_limit": "No Limit",
            "mem_percent": "N/A",
        },
    )
    inspect_fallback = docker_utils.get_container_memory_stats(stopped_container)
    assert inspect_fallback["mem_limit"] == "No Limit"

    running_container = cast(Container, _ContainerStub(status="running"))
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider, "from_container_stats", lambda _c: None
    )
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider, "from_inspect", lambda _c: None
    )
    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider,
        "from_docker_cli",
        lambda _cid: {
            "mem_usage": "5 MiB",
            "mem_limit": "15 MiB",
            "mem_percent": "33.3%",
        },
    )
    from_cli = docker_utils.get_container_memory_stats(running_container)
    assert from_cli["mem_percent"] == "33.3%"

    monkeypatch.setattr(
        docker_utils.MemoryStatsProvider, "from_docker_cli", lambda _cid: None
    )
    unavailable = docker_utils.get_container_memory_stats(running_container)
    assert unavailable["mem_usage"] == "Unavailable"


def test_operation_tracker_limits_cleanup_and_global_wrappers() -> None:
    tracker = docker_utils.ContainerOperationTracker()
    tracker._max_history = 1  # noqa: SLF001
    tracker._cleanup_interval = 0.0  # noqa: SLF001
    tracker._last_cleanup = 0.0  # noqa: SLF001
    tracker.record_operation("cid1234", "restart")
    tracker.record_operation("cid1234", "restart")

    assert len(tracker._operations["cid1234:restart"]) == 1  # noqa: SLF001

    tracker._operations = {  # noqa: SLF001
        "cid1234:start": [0.0],
        "cid9999:stop": [0.0],
    }
    tracker._cleanup_old_operations()  # noqa: SLF001
    assert tracker._operations == {}  # noqa: SLF001

    calls: dict[str, tuple[str, str] | tuple[str, float]] = {}

    class _TrackerStub(docker_utils.ContainerOperationTracker):
        def record_operation(self, container_id: str, operation: str) -> None:
            calls["record"] = (container_id, operation)

        def get_recent_operations(
            self, container_id: str, since_seconds: float = 3600
        ) -> list[_ObjectDict]:
            calls["history"] = (container_id, since_seconds)
            return [{"operation": "start", "count": 1}]

    original_tracker = docker_utils._operation_tracker  # noqa: SLF001
    docker_utils._operation_tracker = _TrackerStub()  # noqa: SLF001
    try:
        docker_utils.record_container_operation("cid1234", "start")
        history = docker_utils.get_container_operation_history(
            "cid1234", since_seconds=10
        )
    finally:
        docker_utils._operation_tracker = original_tracker  # noqa: SLF001

    assert calls["record"] == ("cid1234", "start")
    assert calls["history"] == ("cid1234", 10)
    assert history[0]["operation"] == "start"
