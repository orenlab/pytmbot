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

    with pytest.raises(ValueError):
        docker_utils.ContainerState.from_str("invalid-state")


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


def test_get_container_memory_stats_fallback_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _patch_memory_source(name: str, value: dict[str, str] | None) -> None:
        monkeypatch.setattr(
            docker_utils.MemoryStatsProvider,
            name,
            lambda *_args: value,
        )

    def _assert_memory_fallback_case(
        *,
        status: str,
        patched_sources: dict[str, dict[str, str] | None],
        expected_key: str,
        expected_value: str,
    ) -> None:
        for source_name in (
            "from_cgroups",
            "from_container_stats",
            "from_inspect",
            "from_docker_cli",
        ):
            _patch_memory_source(source_name, patched_sources.get(source_name))

        resolved_stats = docker_utils.get_container_memory_stats(
            cast(Container, _ContainerStub(status=status))
        )
        assert resolved_stats[expected_key] == expected_value

    _assert_memory_fallback_case(
        status="running",
        patched_sources={
            "from_cgroups": None,
            "from_container_stats": {
                "mem_usage": "10 MiB",
                "mem_limit": "20 MiB",
                "mem_percent": "50.0%",
            },
        },
        expected_key="mem_usage",
        expected_value="10 MiB",
    )

    _assert_memory_fallback_case(
        status="stopped",
        patched_sources={
            "from_cgroups": None,
            "from_inspect": {
                "mem_usage": "N/A",
                "mem_limit": "No Limit",
                "mem_percent": "N/A",
            },
        },
        expected_key="mem_limit",
        expected_value="No Limit",
    )

    _assert_memory_fallback_case(
        status="running",
        patched_sources={
            "from_cgroups": None,
            "from_container_stats": None,
            "from_inspect": None,
            "from_docker_cli": {
                "mem_usage": "5 MiB",
                "mem_limit": "15 MiB",
                "mem_percent": "33.3%",
            },
        },
        expected_key="mem_percent",
        expected_value="33.3%",
    )

    _assert_memory_fallback_case(
        status="running",
        patched_sources={
            "from_cgroups": None,
            "from_container_stats": None,
            "from_inspect": None,
            "from_docker_cli": None,
        },
        expected_key="mem_usage",
        expected_value="Unavailable",
    )
