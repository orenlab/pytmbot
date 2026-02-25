from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from docker.errors import APIError, DockerException

from pytmbot.exceptions import DockerConnectionError
from pytmbot.models.docker_models import ContainerAction


class _FakeDockerClient:
    def __init__(self, *, ping_ok: bool = True) -> None:
        self._ping_ok = ping_ok
        self.closed = False
        self.info_calls = 0
        self.api = SimpleNamespace(_version="1.53")
        self.images = SimpleNamespace(list=lambda all=False: [1, 2])  # noqa: FBT002
        self.containers = SimpleNamespace(list=lambda all=True, limit=None: [])  # noqa: FBT002

    def ping(self) -> None:
        if not self._ping_ok:
            raise RuntimeError("ping failed")

    def version(self) -> dict[str, str]:
        return {"Version": "29.2.0", "ServerVersion": "29.2.0"}

    def info(self) -> dict[str, str]:
        self.info_calls += 1
        return {
            "ServerVersion": "29.2.0",
            "ApiVersion": "1.53",
            "KernelVersion": "6.0",
            "OperatingSystem": "Linux",
            "Architecture": "x86_64",
        }

    def close(self) -> None:
        self.closed = True


@dataclass
class _ManagedContainer:
    id: str = "abcdef1234567890"
    short_id: str = "abcdef123456"
    name: str = "demo"
    status: str = "running"

    def __post_init__(self) -> None:
        self.attrs: dict[str, object] = {
            "Created": "2026-01-01T00:00:00Z",
            "State": {
                "StartedAt": "2026-01-01T00:00:01Z",
                "FinishedAt": "2026-01-01T00:00:02Z",
                "ExitCode": 0,
                "Error": "",
                "Pid": 123,
                "Status": self.status,
                "Health": {"Status": "healthy"},
            },
            "RestartCount": 0,
            "Config": {"Image": "repo:tag"},
            "Name": f"/{self.name}",
            "Platform": "linux",
            "Driver": "overlay2",
            "HostConfig": {"NetworkMode": "bridge"},
            "NetworkSettings": {"Ports": {}},
            "Mounts": [],
        }
        self.image = SimpleNamespace(tags=["repo:tag"], short_id="sha256:img")
        self.ports: dict[str, str] = {}
        self.labels: dict[str, str] = {}

    def start(self) -> None:
        self.status = "running"
        self.attrs["State"] = {
            **cast(dict[str, object], self.attrs["State"]),
            "Status": "running",
        }

    def stop(self, *, timeout: int) -> None:
        del timeout
        self.status = "stopped"
        self.attrs["State"] = {
            **cast(dict[str, object], self.attrs["State"]),
            "Status": "stopped",
        }

    def restart(self, *, timeout: int) -> None:
        del timeout
        self.status = "running"
        self.attrs["State"] = {
            **cast(dict[str, object], self.attrs["State"]),
            "Status": "running",
        }

    def rename(self, new_name: str) -> None:
        self.name = new_name
        self.attrs["Name"] = f"/{new_name}"

    def reload(self) -> None:
        return

    def logs(self, **_kwargs: object) -> bytes:
        return b"line1\nline2\n"


def _docker_settings_stub() -> SimpleNamespace:
    return SimpleNamespace(
        docker=SimpleNamespace(
            host=["unix:///var/run/docker.sock"],
            timeout=30,
            cert_path=None,
            key_path=None,
            ca_cert=True,
            debug_docker_client=False,
            strict_access=False,
            stop_timeout=5,
            restart_timeout=5,
        ),
        version="0.3.0-dev",
    )


def test_docker_adapter_context_health_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    fake_client = _FakeDockerClient()
    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    monkeypatch.setattr(
        docker_adapter_module.docker, "DockerClient", lambda **kwargs: fake_client
    )

    adapter = docker_adapter_module.DockerAdapter()
    with adapter as client:
        assert client is fake_client

    assert adapter.health_check() is True
    status = adapter.get_status()
    assert status["client_active"] is True

    adapter.force_reconnect()
    assert adapter.get_status()["client_active"] is False
    adapter.close()


def test_docker_adapter_handles_invalid_config_and_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    bad_settings = SimpleNamespace(
        docker=SimpleNamespace(host=[], timeout=30, strict_access=False)
    )
    monkeypatch.setattr(docker_adapter_module, "settings", bad_settings)
    degraded_adapter = docker_adapter_module.DockerAdapter()
    degraded_status = degraded_adapter.get_status()
    assert degraded_status["degraded_mode"] is True

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    failing_client = _FakeDockerClient(ping_ok=False)
    monkeypatch.setattr(
        docker_adapter_module.docker, "DockerClient", lambda **kwargs: failing_client
    )
    adapter = docker_adapter_module.DockerAdapter()
    assert adapter.health_check() is False
    adapter.close()


def test_container_manager_manage_actions_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.container_manager as container_manager_module

    container = _ManagedContainer(status="running")
    manager = container_manager_module.ContainerManager()

    settings_stub = SimpleNamespace(
        access_control=SimpleNamespace(allowed_admins_ids=[1], max_session_age=3600),
        docker=SimpleNamespace(stop_timeout=5, restart_timeout=5),
    )
    monkeypatch.setattr(container_manager_module, "settings", settings_stub)
    monkeypatch.setattr(
        container_manager_module,
        "session_manager",
        SimpleNamespace(
            is_authenticated=lambda user_id: user_id == 1,
            get_session_info=lambda _user_id: {"created_at": time.time()},
        ),
    )
    monkeypatch.setattr(
        container_manager_module, "is_new_name_valid", lambda _name: True
    )
    monkeypatch.setattr(
        container_manager_module,
        "get_container_safely",
        lambda _cid, docker_client=None: container,
    )

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield SimpleNamespace()

    monkeypatch.setattr(
        container_manager_module, "docker_client_context", _client_context
    )

    assert manager.managing_container(1, container.id, "start") is None
    assert manager.managing_container(1, container.id, "stop") is None
    assert manager.managing_container(1, container.id, "restart") is None
    assert (
        manager.managing_container(
            1, container.id, "rename", new_container_name="renamed"
        )
        is None
    )

    status = manager.get_container_status(container.id)
    assert status["name"] == "renamed"
    assert "started_at" in status

    history = manager.get_operation_history()
    assert history
    manager.clear_operation_history()
    assert manager.get_operation_history() == {}

    with pytest.raises(ValueError):
        manager.managing_container(1, container.id, "unknown-action")


def test_container_manager_access_control_blocks_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.container_manager as container_manager_module

    manager = container_manager_module.ContainerManager()
    monkeypatch.setattr(
        container_manager_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_admins_ids=[]),
            docker=SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        container_manager_module,
        "session_manager",
        SimpleNamespace(
            is_authenticated=lambda _uid: False, get_session_info=lambda _uid: {}
        ),
    )

    with pytest.raises(PermissionError):
        manager.managing_container(77, "cid1234", "start")


def test_containers_info_retrieve_logs_counters_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.containers_info as containers_info_module
    import pytmbot.adapters.docker.utils as docker_utils_module

    container = _ManagedContainer(status="running")
    containers_info_module.clear_container_cache()

    fake_adapter = SimpleNamespace(
        containers=SimpleNamespace(list=lambda all=True: [container]),  # noqa: FBT002
        images=SimpleNamespace(list=lambda all=False: [1, 2]),  # noqa: FBT002
    )

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield fake_adapter

    monkeypatch.setattr(
        containers_info_module, "docker_client_context", _client_context
    )
    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: container,
    )
    monkeypatch.setattr(containers_info_module, "Container", _ManagedContainer)
    monkeypatch.setattr(docker_utils_module, "settings", _docker_settings_stub())

    stats = containers_info_module.retrieve_containers_stats()
    logs = containers_info_module.fetch_container_logs(container.id, tail_lines=10)
    counters_first = containers_info_module.fetch_docker_counters(force_refresh=True)
    counters_cached = containers_info_module.fetch_docker_counters()
    full = containers_info_module.fetch_full_container_details(container.id)

    assert len(stats) == 1
    assert "line1" in logs
    assert counters_first["images_count"] == 2
    assert counters_cached["containers_count"] == 1
    assert full is container

    cache_stats = containers_info_module.get_cache_stats()
    assert "cache_size" in cache_stats


def test_fetch_full_container_details_returns_none_for_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.containers_info as containers_info_module
    from pytmbot.exceptions import ErrorContext

    error = containers_info_module.ContainerNotFoundError(
        ErrorContext(
            message="missing",
            error_code="DOCKER_001",
            metadata={},
        )
    )
    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: (_ for _ in ()).throw(error),
    )

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield SimpleNamespace()

    monkeypatch.setattr(
        containers_info_module, "docker_client_context", _client_context
    )
    assert containers_info_module.fetch_full_container_details("missing") is None


def test_containers_info_cache_paths_and_counters_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.containers_info as containers_info_module

    cache = containers_info_module.ContainerInfoCache(ttl=1)

    # Force cleanup path that removes expired entries.
    cache._cache["expired"] = ({"ok": True}, 0.0)  # noqa: SLF001
    cache._cleanup_expired_entries(10.0, force=True)  # noqa: SLF001
    assert "expired" not in cache._cache  # noqa: SLF001

    # Expired read path in get().
    cache._cache["old"] = ({"value": 1}, 0.0)  # noqa: SLF001
    monkeypatch.setattr(containers_info_module.time, "time", lambda: 10.0)
    assert cache.get("old") is None

    # Fresh read path in get().
    cache._cache["fresh"] = ({"value": 2}, 10.0)  # noqa: SLF001
    assert cache.get("fresh") == {"value": 2}

    # Max entries eviction path in set().
    cache_eviction = containers_info_module.ContainerInfoCache(ttl=100)
    cache_eviction._max_entries = 1  # noqa: SLF001
    eviction_times = iter([20.0, 21.0])
    monkeypatch.setattr(
        containers_info_module.time,
        "time",
        lambda: next(eviction_times),
    )
    cache_eviction.set("first", {"value": 1})
    cache_eviction.set("second", {"value": 2})
    assert cache_eviction.size() == 1
    assert "second" in cache_eviction._cache  # noqa: SLF001

    # Docker counters cache: empty and expired branches.
    containers_info_module._clear_docker_counters_cache()  # noqa: SLF001
    assert containers_info_module._get_cached_docker_counters() is None  # noqa: SLF001

    containers_info_module._store_docker_counters({"containers_count": 1})  # noqa: SLF001
    cached_at = containers_info_module._docker_counters_cached_at  # noqa: SLF001
    monkeypatch.setattr(
        containers_info_module.time,
        "monotonic",
        lambda: cached_at + containers_info_module.DOCKER_COUNTERS_CACHE_TTL + 1,
    )
    assert containers_info_module._get_cached_docker_counters() is None  # noqa: SLF001


def test_containers_info_aggregate_details_edge_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.containers_info as containers_info_module
    from pytmbot.exceptions import ErrorContext

    containers_info_module.clear_container_cache()

    noisy_container = _ManagedContainer(name="")
    noisy_container.attrs["Created"] = "bad-created"
    noisy_container.attrs["State"] = {"StartedAt": "bad-started", "Status": "running"}
    noisy_container.attrs["Name"] = ""

    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: noisy_container,
    )

    details = containers_info_module.__aggregate_container_details(  # noqa: SLF001
        "container-xyz",
        docker_client=SimpleNamespace(),
    )
    assert details["name"] == "Container-Xy"
    assert details["created"] == "unknown"
    assert details["run_at"] == "N/A"

    # Cached read path.
    cached = containers_info_module.__aggregate_container_details(  # noqa: SLF001
        "container-xyz",
        docker_client=SimpleNamespace(),
    )
    assert cached == details

    no_created_container = _ManagedContainer(name="fallback")
    no_created_container.attrs["Created"] = ""
    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: no_created_container,
    )
    no_created = containers_info_module.__aggregate_container_details(  # noqa: SLF001
        "no-created",
        docker_client=SimpleNamespace(),
    )
    assert no_created["created"] == "unknown"

    not_found = containers_info_module.ContainerNotFoundError(
        ErrorContext(
            message="missing",
            error_code="DOCKER_001",
            metadata={},
        )
    )
    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: (_ for _ in ()).throw(not_found),
    )
    with pytest.raises(containers_info_module.ContainerNotFoundError):
        containers_info_module.__aggregate_container_details(  # noqa: SLF001
            "missing",
            docker_client=SimpleNamespace(),
        )

    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        containers_info_module.__aggregate_container_details(  # noqa: SLF001
            "broken",
            docker_client=SimpleNamespace(),
        )


def test_containers_info_retrieve_and_logs_error_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.containers_info as containers_info_module
    from pytmbot.exceptions import ErrorContext

    # retrieve_containers_stats: no containers branch.
    empty_adapter = SimpleNamespace(
        containers=SimpleNamespace(list=lambda all=True: [])
    )  # noqa: FBT002

    @contextmanager
    def _empty_context() -> Iterator[object]:
        yield empty_adapter

    monkeypatch.setattr(containers_info_module, "docker_client_context", _empty_context)
    assert containers_info_module.retrieve_containers_stats() == []

    # retrieve_containers_stats: per-container failures + sorting + warning.
    containers = [
        SimpleNamespace(id="id-not-found", short_id="id-not-found"),
        SimpleNamespace(id="id-error", short_id="id-error"),
        SimpleNamespace(id="id-b", short_id="id-b"),
        SimpleNamespace(id="id-a", short_id="id-a"),
    ]
    multi_adapter = SimpleNamespace(
        containers=SimpleNamespace(list=lambda all=True: containers),  # noqa: FBT002
    )

    @contextmanager
    def _multi_context() -> Iterator[object]:
        yield multi_adapter

    monkeypatch.setattr(containers_info_module, "docker_client_context", _multi_context)

    not_found = containers_info_module.ContainerNotFoundError(
        ErrorContext(
            message="missing",
            error_code="DOCKER_001",
            metadata={},
        )
    )

    def _aggregate(
        container_ref: object,
        docker_client: object | None = None,
    ) -> dict[str, str]:
        del docker_client
        identifier = str(getattr(container_ref, "short_id", ""))
        if identifier == "id-not-found":
            raise not_found
        if identifier == "id-error":
            raise RuntimeError("detail failure")
        if identifier == "id-b":
            return {"name": "Zulu", "id": "id-b", "status": "running"}
        return {"name": "alpha", "id": "id-a", "status": "running"}

    monkeypatch.setattr(
        containers_info_module, "__aggregate_container_details", _aggregate
    )
    rows = containers_info_module.retrieve_containers_stats()
    assert [row["name"] for row in rows] == ["alpha", "Zulu"]

    class _FailingContext:
        def __enter__(self) -> object:
            raise RuntimeError("list failure")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

    monkeypatch.setattr(
        containers_info_module,
        "docker_client_context",
        lambda: _FailingContext(),
    )
    with pytest.raises(RuntimeError, match="list failure"):
        containers_info_module.retrieve_containers_stats()

    # fetch_container_logs: validation, non-bytes output, truncation and errors.
    with pytest.raises(ValueError):
        containers_info_module.fetch_container_logs("cid", tail_lines=0)

    huge_log = "x" * 11_500
    log_container = SimpleNamespace(logs=lambda **_kwargs: huge_log)
    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: log_container,
    )

    @contextmanager
    def _logs_context() -> Iterator[object]:
        yield SimpleNamespace()

    monkeypatch.setattr(containers_info_module, "docker_client_context", _logs_context)
    content = containers_info_module.fetch_container_logs("cid", tail_lines=5)
    assert content.startswith("[LOG TRUNCATED")
    assert len(content) > 10_000

    not_found_for_logs = containers_info_module.ContainerNotFoundError(
        ErrorContext(
            message="missing",
            error_code="DOCKER_001",
            metadata={},
        )
    )
    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: (_ for _ in ()).throw(not_found_for_logs),
    )
    with pytest.raises(containers_info_module.ContainerNotFoundError):
        containers_info_module.fetch_container_logs("missing", tail_lines=5)

    def _unsupported_logs(**_kwargs: object) -> bytes:
        raise APIError("configured logging driver does not support reading")

    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: SimpleNamespace(logs=_unsupported_logs),
    )
    with pytest.raises(containers_info_module.ContainerLogsUnavailableError):
        containers_info_module.fetch_container_logs("cid", tail_lines=5)

    def _api_logs_failure(**_kwargs: object) -> bytes:
        raise APIError("transport failure")

    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: SimpleNamespace(logs=_api_logs_failure),
    )
    with pytest.raises(APIError, match="transport failure"):
        containers_info_module.fetch_container_logs("cid", tail_lines=5)

    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: (_ for _ in ()).throw(
            RuntimeError("logs fail")
        ),
    )
    with pytest.raises(RuntimeError, match="logs fail"):
        containers_info_module.fetch_container_logs("cid", tail_lines=5)


def test_containers_info_counters_and_full_details_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.containers_info as containers_info_module

    class _FailingContext:
        def __enter__(self) -> object:
            raise RuntimeError("docker unavailable")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: object,
        ) -> None:
            return None

    monkeypatch.setattr(
        containers_info_module,
        "docker_client_context",
        lambda: _FailingContext(),
    )
    with pytest.raises(RuntimeError, match="docker unavailable"):
        containers_info_module.fetch_docker_counters(force_refresh=True)

    @contextmanager
    def _context() -> Iterator[object]:
        yield SimpleNamespace()

    monkeypatch.setattr(containers_info_module, "docker_client_context", _context)
    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: (_ for _ in ()).throw(
            RuntimeError("full fail")
        ),
    )

    assert containers_info_module.fetch_full_container_details("cid") is None


def test_docker_adapter_security_checks_and_context_sanitization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    insecure_settings = SimpleNamespace(
        docker=SimpleNamespace(
            host=["http://127.0.0.1:2375"],
            timeout=30,
            cert_path=None,
            key_path=None,
            ca_cert=True,
            debug_docker_client=False,
        ),
        version="0.3.0-dev",
    )
    monkeypatch.setattr(docker_adapter_module, "settings", insecure_settings)
    with pytest.warns(RuntimeWarning):
        adapter = docker_adapter_module.DockerAdapter()

    context = adapter._get_context(
        "test",
        {
            "token_value": "abc",
            "password": "secret",
            "safe_value": "ok",
        },
    )
    assert context["token_value"] == "[REDACTED]"
    assert context["password"] == "[REDACTED]"
    assert context["safe_value"] == "ok"


def test_docker_adapter_tls_config_and_timeout_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    bad_timeout_settings = SimpleNamespace(
        docker=SimpleNamespace(
            host=["unix:///var/run/docker.sock"],
            timeout=1,
            strict_access=False,
        ),
        version="0.3.0-dev",
    )
    monkeypatch.setattr(docker_adapter_module, "settings", bad_timeout_settings)
    adapter_with_default_timeout = docker_adapter_module.DockerAdapter()
    assert adapter_with_default_timeout._timeout_config["timeout"] == 30

    strict_bad_timeout_settings = SimpleNamespace(
        docker=SimpleNamespace(
            host=["unix:///var/run/docker.sock"],
            timeout=1,
            strict_access=True,
        ),
        version="0.3.0-dev",
    )
    monkeypatch.setattr(docker_adapter_module, "settings", strict_bad_timeout_settings)
    with pytest.raises(ValueError):
        docker_adapter_module.DockerAdapter()

    https_settings = SimpleNamespace(
        docker=SimpleNamespace(
            host=["https://docker.example.com"],
            timeout=30,
            cert_path=None,
            key_path=None,
            ca_cert=True,
            verify_hostname=True,
            debug_docker_client=False,
            strict_access=False,
        ),
        version="0.3.0-dev",
    )
    monkeypatch.setattr(docker_adapter_module, "settings", https_settings)
    adapter = docker_adapter_module.DockerAdapter()
    assert adapter._create_tls_config() is not None

    monkeypatch.setattr(
        docker_adapter_module.docker.tls,
        "TLSConfig",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("tls boom")),
    )
    with pytest.raises(RuntimeError):
        adapter._create_tls_config()


def test_docker_adapter_health_check_and_exit_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    class _EmptyInfoClient(_FakeDockerClient):
        def info(self) -> dict[str, str]:
            return {}

    class _FailingCloseClient(_FakeDockerClient):
        def close(self) -> None:
            raise RuntimeError("close fail")

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    monkeypatch.setattr(
        docker_adapter_module.docker,
        "DockerClient",
        lambda **_kwargs: _EmptyInfoClient(),
    )
    adapter = docker_adapter_module.DockerAdapter()
    assert adapter.health_check() is False

    # Exercise __exit__ branches with Docker-specific and generic exceptions.
    adapter._last_health_check = datetime.now()
    adapter.__exit__(DockerException, DockerException("docker fail"), None)
    assert adapter._last_health_check is None
    adapter.__exit__(ValueError, ValueError("generic fail"), None)

    # Close path where client.close raises.
    adapter._client = _FailingCloseClient()
    adapter.close()
    assert adapter._client is None

    # Enter should wrap unexpected errors as DockerConnectionError.
    adapter._strict_docker_access = True
    monkeypatch.setattr(adapter, "_should_recreate_client", lambda: False)
    adapter._client = None
    with pytest.raises(DockerConnectionError):
        adapter.__enter__()


def test_parse_bool_like_and_unavailable_client_stubs() -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    assert docker_adapter_module._parse_bool_like(None) is False
    assert docker_adapter_module._parse_bool_like("YES") is True

    collection = docker_adapter_module._UnavailableDockerCollection("offline")
    with pytest.raises(DockerConnectionError):
        collection.list()
    with pytest.raises(DockerConnectionError):
        collection.get("id")

    client = docker_adapter_module._UnavailableDockerClient("offline")
    assert isinstance(
        client.containers, docker_adapter_module._UnavailableDockerCollection
    )
    assert isinstance(client.images, docker_adapter_module._UnavailableDockerCollection)
    with pytest.raises(DockerConnectionError):
        client.ping()
    with pytest.raises(DockerConnectionError):
        client.version()
    with pytest.raises(DockerConnectionError):
        client.info()
    client.close()


def test_strict_and_non_strict_configuration_validation_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setenv("STRICT_DOCKER_ACCESS", "1")
    monkeypatch.setattr(docker_adapter_module, "settings", SimpleNamespace())
    with pytest.raises(ValueError):
        docker_adapter_module.DockerAdapter()

    monkeypatch.delenv("STRICT_DOCKER_ACCESS", raising=False)
    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["   "],
                timeout=30,
                strict_access=False,
            ),
            version="0.3.0-dev",
        ),
    )
    empty_host_adapter = docker_adapter_module.DockerAdapter()
    assert empty_host_adapter.get_status()["degraded_mode"] is True

    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["unix:///var/run/docker.sock"],
                timeout="bad-timeout",
                strict_access=False,
            ),
            version="0.3.0-dev",
        ),
    )
    bad_timeout_adapter = docker_adapter_module.DockerAdapter()
    assert bad_timeout_adapter.get_status()["timeout_config"]["timeout"] == 30


def test_security_checks_and_tls_path_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["tcp://127.0.0.1:2375"],
                timeout=30,
                cert_path=None,
                key_path=None,
                ca_cert=True,
                strict_access=False,
            ),
            version="0.3.0-dev",
        ),
    )
    tcp_adapter = docker_adapter_module.DockerAdapter()
    assert tcp_adapter.get_status()["secure_connection"] is False

    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["https://docker.example.local"],
                timeout=30,
                cert_path="/missing/cert.pem",
                key_path="/missing/key.pem",
                ca_cert="/missing/ca.pem",
                verify_hostname=True,
                strict_access=False,
            ),
            version="0.3.0-dev",
        ),
    )
    tls_adapter = docker_adapter_module.DockerAdapter()
    assert tls_adapter._docker_url.startswith("https://")


def test_create_tls_config_hostname_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["https://docker.example.local"],
                timeout=30,
                cert_path=None,
                key_path=None,
                ca_cert=False,
                verify_hostname=True,
                strict_access=False,
            ),
            version="0.3.0-dev",
        ),
    )
    adapter = docker_adapter_module.DockerAdapter()
    tls_config = adapter._create_tls_config()
    assert tls_config is not None

    monkeypatch.setattr(
        docker_adapter_module,
        "signature",
        lambda fn: SimpleNamespace(parameters={}),
    )
    monkeypatch.setattr(
        docker_adapter_module.docker.tls,
        "TLSConfig",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    tls_without_hostname = adapter._create_tls_config()
    assert tls_without_hostname is not None


def test_internal_adapter_paths_for_client_recreation_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    adapter = docker_adapter_module.DockerAdapter()

    class _VersionStringClient(_FakeDockerClient):
        def version(self) -> str:  # type: ignore[override]
            return "not-a-dict"

    assert adapter._test_connection(_VersionStringClient()) == {}

    unavailable = adapter._build_unavailable_client("degraded")
    with pytest.raises(DockerConnectionError):
        unavailable.ping()

    monkeypatch.setattr(
        adapter,
        "_create_tls_config",
        lambda: (_ for _ in ()).throw(RuntimeError("tls crash")),
    )
    with pytest.raises(DockerConnectionError):
        adapter._create_client()

    adapter._client = cast(
        object,
        SimpleNamespace(ping=lambda: (_ for _ in ()).throw(RuntimeError("ping fail"))),
    )
    adapter._last_health_check = None
    assert adapter._should_recreate_client() is True

    adapter._docker_info_cache = {"version": "cached"}
    adapter._docker_info_cached_at = datetime.now().timestamp()
    assert adapter._get_docker_info()["version"] == "cached"


def test_enter_paths_for_disabled_and_degraded_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(host=[], timeout=30, strict_access=False)
        ),
    )
    disabled_adapter = docker_adapter_module.DockerAdapter()
    unavailable_client = disabled_adapter.__enter__()
    with pytest.raises(DockerConnectionError):
        unavailable_client.ping()
    disabled_adapter.__exit__(None, None, None)

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    degraded_adapter = docker_adapter_module.DockerAdapter()
    monkeypatch.setattr(
        degraded_adapter,
        "_should_recreate_client",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    degraded_client = degraded_adapter.__enter__()
    with pytest.raises(DockerConnectionError):
        degraded_client.ping()
    degraded_adapter.__exit__(None, None, None)


def test_enter_slow_path_reuse_and_old_client_close_suppression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    adapter = docker_adapter_module.DockerAdapter()
    existing_client = _FakeDockerClient()
    adapter._client = existing_client

    call_sequence = iter([True, False])
    monkeypatch.setattr(adapter, "_should_recreate_client", lambda: next(call_sequence))
    reused = adapter.__enter__()
    assert reused is existing_client
    adapter.__exit__(None, None, None)

    class _FailingCloseClient(_FakeDockerClient):
        def close(self) -> None:
            raise RuntimeError("close fail")

    adapter._client = _FailingCloseClient()
    create_sequence = iter([True, True])
    monkeypatch.setattr(
        adapter, "_should_recreate_client", lambda: next(create_sequence)
    )
    monkeypatch.setattr(adapter, "_create_client", lambda: _FakeDockerClient())
    recreated = adapter.__enter__()
    assert isinstance(recreated, _FakeDockerClient)
    adapter.__exit__(None, None, None)


def test_health_check_docker_connection_error_and_del_cleanup_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    adapter = docker_adapter_module.DockerAdapter()

    monkeypatch.setattr(
        docker_adapter_module.DockerAdapter,
        "__enter__",
        lambda self: (_ for _ in ()).throw(DockerConnectionError("down")),
    )
    assert adapter.health_check() is False

    monkeypatch.setattr(
        adapter, "close", lambda: (_ for _ in ()).throw(RuntimeError("close crash"))
    )
    monkeypatch.setattr(
        adapter, "_log", SimpleNamespace(warning=lambda *args, **kwargs: None)
    )
    adapter.__del__()


def test_remaining_adapter_branches_for_strict_tls_and_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    # Non-strict mode with missing docker config should degrade (line 153 return).
    monkeypatch.setattr(docker_adapter_module, "settings", SimpleNamespace())
    degraded = docker_adapter_module.DockerAdapter()
    assert degraded.get_status()["degraded_mode"] is True

    # Strict mode with invalid timeout type should fail fast (line 171 raise path).
    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["unix:///var/run/docker.sock"],
                timeout="invalid",
                strict_access=True,
            ),
        ),
    )
    with pytest.raises(ValueError):
        docker_adapter_module.DockerAdapter()

    # Cover TLS assert_hostname wiring branch (line 315).
    monkeypatch.setattr(
        docker_adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["https://docker.example.local"],
                timeout=30,
                cert_path=None,
                key_path=None,
                ca_cert=True,
                verify_hostname=True,
                strict_access=False,
            ),
            version="0.3.0-dev",
        ),
    )
    captured_tls_kwargs: dict[str, object] = {}

    def _capture_tls_config(**kwargs: object) -> SimpleNamespace:
        captured_tls_kwargs.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        docker_adapter_module,
        "signature",
        lambda fn: SimpleNamespace(parameters={"assert_hostname": object()}),
    )
    monkeypatch.setattr(
        docker_adapter_module.docker.tls, "TLSConfig", _capture_tls_config
    )
    tls_adapter = docker_adapter_module.DockerAdapter()
    assert tls_adapter._create_tls_config() is not None
    assert captured_tls_kwargs.get("assert_hostname") is True

    # Cover healthy ping branch in _should_recreate_client (lines 473-474).
    healthy = _FakeDockerClient(ping_ok=True)
    tls_adapter._client = healthy
    tls_adapter._last_health_check = None
    assert tls_adapter._should_recreate_client() is False
    assert tls_adapter._last_health_check is not None


def test_enter_slow_path_raises_when_client_missing_after_double_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    adapter = docker_adapter_module.DockerAdapter()
    adapter._strict_docker_access = True
    call_sequence = iter([True, False])
    monkeypatch.setattr(adapter, "_should_recreate_client", lambda: next(call_sequence))

    with pytest.raises(DockerConnectionError):
        adapter.__enter__()


def _patch_container_manager_access(
    monkeypatch: pytest.MonkeyPatch,
    container_manager_module: object,
    *,
    allowed_admins_ids: list[int],
    is_authenticated: bool,
    created_at: float,
    max_session_age: int = 3600,
) -> None:
    monkeypatch.setattr(
        container_manager_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(
                allowed_admins_ids=allowed_admins_ids,
                max_session_age=max_session_age,
            ),
            docker=SimpleNamespace(start_timeout=5, stop_timeout=5, restart_timeout=5),
        ),
    )
    monkeypatch.setattr(
        container_manager_module,
        "session_manager",
        SimpleNamespace(
            is_authenticated=lambda _uid: is_authenticated,
            get_session_info=lambda _uid: {"created_at": created_at},
        ),
    )


def test_container_manager_access_validation_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.container_manager as container_manager_module

    manager = container_manager_module.ContainerManager()

    with pytest.raises(ValueError):
        manager.managing_container(0, "cid", "start")

    # Unauthorized call sets rate-limit state; second call must fail by rate-limit.
    _patch_container_manager_access(
        monkeypatch,
        container_manager_module,
        allowed_admins_ids=[],
        is_authenticated=False,
        created_at=time.time(),
    )
    with pytest.raises(PermissionError):
        manager.managing_container(1001, "cid", "start")
    with pytest.raises(PermissionError, match="Rate limit exceeded"):
        manager.managing_container(1001, "cid", "start")

    # Session authentication branch.
    _patch_container_manager_access(
        monkeypatch,
        container_manager_module,
        allowed_admins_ids=[1002],
        is_authenticated=False,
        created_at=time.time(),
    )
    with pytest.raises(PermissionError, match="session invalid"):
        manager.managing_container(1002, "cid", "start")

    # Session age expiration branch.
    _patch_container_manager_access(
        monkeypatch,
        container_manager_module,
        allowed_admins_ids=[1003],
        is_authenticated=True,
        created_at=0.0,
        max_session_age=1,
    )
    monkeypatch.setattr(container_manager_module.time, "time", lambda: 100.0)
    with pytest.raises(PermissionError, match="Session expired"):
        manager.managing_container(1003, "cid", "start")


def test_container_manager_internal_timeout_and_history_cleanup() -> None:
    import pytmbot.adapters.docker.container_manager as container_manager_module

    manager = container_manager_module.ContainerManager()
    with pytest.raises(ValueError):
        manager._normalize_container_id("   ")

    for idx in range(120):
        manager._record_operation("start", f"id-{idx}")
    assert len(manager._operation_history) <= 100

    with pytest.raises(TimeoutError):
        manager._run_with_timeout(
            "slow-op",
            lambda: time.sleep(0.05),
            timeout_seconds=0.001,
        )


def test_container_manager_lifecycle_and_status_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.container_manager as container_manager_module

    manager = container_manager_module.ContainerManager()
    _patch_container_manager_access(
        monkeypatch,
        container_manager_module,
        allowed_admins_ids=[2001],
        is_authenticated=True,
        created_at=time.time(),
    )

    mismatch_container = _ManagedContainer(status="exited")

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield SimpleNamespace()

    monkeypatch.setattr(
        container_manager_module, "docker_client_context", _client_context
    )
    monkeypatch.setattr(
        container_manager_module,
        "get_container_safely",
        lambda _cid, docker_client=None: mismatch_container,
    )

    with pytest.raises(RuntimeError, match="Start operation failed"):
        manager._execute_lifecycle_operation(
            user_id=2001,
            container_id="cid-1",
            operation="start",
            context_action="test_start",
            start_event="start.event",
            success_event="start.ok",
            fail_event="start.fail",
            expected_statuses={"running"},
            expected_status_description="running",
            execute_operation=lambda container: None,
        )

    monkeypatch.setattr(
        container_manager_module,
        "get_container_safely",
        lambda _cid, docker_client=None: (_ for _ in ()).throw(
            RuntimeError("status boom")
        ),
    )
    with pytest.raises(RuntimeError):
        container_manager_module.ContainerManager.get_container_status("cid-2")


def test_container_manager_rename_and_dispatch_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.container_manager as container_manager_module

    manager = container_manager_module.ContainerManager()
    _patch_container_manager_access(
        monkeypatch,
        container_manager_module,
        allowed_admins_ids=[3001, 3002, 3003, 3004, 3005, 3006, 3007],
        is_authenticated=True,
        created_at=time.time(),
    )

    @contextmanager
    def _client_context() -> Iterator[object]:
        yield SimpleNamespace()

    monkeypatch.setattr(
        container_manager_module, "docker_client_context", _client_context
    )
    base_container = _ManagedContainer(status="running", name="same")
    monkeypatch.setattr(
        container_manager_module,
        "get_container_safely",
        lambda _cid, docker_client=None: base_container,
    )
    manager_any: Any = manager
    rename_container = manager_any._ContainerManager__rename_container

    # Validation branches.
    with pytest.raises(ValueError):
        rename_container(3001, "cid", "")
    with pytest.raises(ValueError):
        rename_container(3002, "cid", "x" * 65)
    with pytest.raises(ValueError):
        rename_container(3003, "cid", "   ")

    monkeypatch.setattr(
        container_manager_module, "is_new_name_valid", lambda _name: False
    )
    with pytest.raises(ValueError, match="Invalid container name format"):
        rename_container(3004, "cid", "bad/name")

    monkeypatch.setattr(
        container_manager_module, "is_new_name_valid", lambda _name: True
    )
    assert rename_container(3005, "cid", "same") is None

    class _NoRenameContainer(_ManagedContainer):
        def rename(self, new_name: str) -> None:
            del new_name
            return

    monkeypatch.setattr(
        container_manager_module,
        "get_container_safely",
        lambda _cid, docker_client=None: _NoRenameContainer(
            status="running", name="/old"
        ),
    )
    with pytest.raises(RuntimeError, match="Rename operation failed"):
        rename_container(3006, "cid", "new")

    class _ExplodingRenameContainer(_ManagedContainer):
        def rename(self, new_name: str) -> None:
            del new_name
            raise RuntimeError("rename explode")

    monkeypatch.setattr(
        container_manager_module,
        "get_container_safely",
        lambda _cid, docker_client=None: _ExplodingRenameContainer(
            status="running", name="/old"
        ),
    )
    with pytest.raises(RuntimeError, match="rename explode"):
        rename_container(3007, "cid", "new-2")

    with pytest.raises(ValueError):
        manager.managing_container(3001, "cid", " ")

    with monkeypatch.context() as local_patch:
        local_patch.setattr(
            container_manager_module.ContainerAction,
            "from_str",
            lambda _action: cast(ContainerAction, object()),
        )
        with pytest.raises(ValueError, match="Invalid action"):
            manager.managing_container(3001, "cid", "start")

    monkeypatch.setattr(
        manager,
        "_ContainerManager__start_container",
        lambda _user_id, _container_id: (_ for _ in ()).throw(
            RuntimeError("start fail")
        ),
    )
    with pytest.raises(RuntimeError, match="start fail"):
        manager.managing_container(3001, "cid", "start")


def test_docker_adapter_test_connection_retries_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker._adapter as docker_adapter_module

    class _FlakyPingClient(_FakeDockerClient):
        def __init__(self) -> None:
            super().__init__()
            self.ping_calls = 0

        def ping(self) -> None:
            self.ping_calls += 1
            if self.ping_calls < 3:
                raise RuntimeError("transient ping failure")

    monkeypatch.setattr(docker_adapter_module, "settings", _docker_settings_stub())
    adapter = docker_adapter_module.DockerAdapter()
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        docker_adapter_module.time, "sleep", lambda seconds: sleep_calls.append(seconds)
    )

    client = _FlakyPingClient()
    version = adapter._test_connection(client)

    assert version is not None
    assert version.get("Version") == "29.2.0"
    assert client.ping_calls == 3
    assert sleep_calls == [0.5, 1.0]
