from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from types import ModuleType, SimpleNamespace, TracebackType
from typing import Never, cast

import pytest
from docker.errors import APIError, DockerException

from pytmbot.exceptions import (
    ContainerLogsUnavailableError,
    ContainerNotFoundError,
    DockerConnectionError,
)
from pytmbot.models.docker_models import ContainerAction

type _Value = str | int | float | bool | None | dict[str, _Value] | list[_Value]


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
        self.attrs: dict[str, _Value] = {
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
        self._set_runtime_status("running")

    def stop(self, *, timeout: int) -> None:
        del timeout
        self._set_runtime_status("stopped")

    def restart(self, *, timeout: int) -> None:
        del timeout
        self._set_runtime_status("running")

    def _set_runtime_status(self, status: str) -> None:
        self.status = status
        self.attrs["State"] = {
            **cast(dict[str, _Value], self.attrs["State"]),
            "Status": status,
        }

    def rename(self, new_name: str) -> None:
        self.name = new_name
        self.attrs["Name"] = f"/{new_name}"

    def reload(self) -> None:
        return

    def logs(self, **_kwargs: _Value) -> bytes:
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
        version="0.3.3",
    )


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


def test_fetch_full_container_details_returns_none_for_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.adapters.docker.containers_info as containers_info_module
    from pytmbot.exceptions import ErrorContext

    error = ContainerNotFoundError(
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
    def _client_context() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace()

    monkeypatch.setattr(
        containers_info_module, "docker_client_context", _client_context
    )
    assert containers_info_module.fetch_full_container_details("missing") is None


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
    def _empty_context() -> Iterator[SimpleNamespace]:
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
    def _multi_context() -> Iterator[SimpleNamespace]:
        yield multi_adapter

    monkeypatch.setattr(containers_info_module, "docker_client_context", _multi_context)

    not_found = ContainerNotFoundError(
        ErrorContext(
            message="missing",
            error_code="DOCKER_001",
            metadata={},
        )
    )

    def _aggregate(
        container_ref: SimpleNamespace,
        docker_client: SimpleNamespace | None = None,
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
        def __enter__(self) -> Never:
            raise RuntimeError("list failure")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
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
    def _logs_context() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace()

    monkeypatch.setattr(containers_info_module, "docker_client_context", _logs_context)
    content = containers_info_module.fetch_container_logs("cid", tail_lines=5)
    assert content.startswith("[LOG TRUNCATED")
    assert len(content) > 10_000

    not_found_for_logs = ContainerNotFoundError(
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
    with pytest.raises(ContainerNotFoundError):
        containers_info_module.fetch_container_logs("missing", tail_lines=5)

    def _unsupported_logs(**_kwargs: _Value) -> bytes:
        raise APIError("configured logging driver does not support reading")

    monkeypatch.setattr(
        containers_info_module,
        "get_container_safely",
        lambda _cid, docker_client=None: SimpleNamespace(logs=_unsupported_logs),
    )
    with pytest.raises(ContainerLogsUnavailableError):
        containers_info_module.fetch_container_logs("cid", tail_lines=5)

    def _api_logs_failure(**_kwargs: _Value) -> bytes:
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
        def __enter__(self) -> Never:
            raise RuntimeError("docker unavailable")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
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
    def _context() -> Iterator[SimpleNamespace]:
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
        version="0.3.3",
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
        version="0.3.3",
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
        version="0.3.3",
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
        version="0.3.3",
    )
    monkeypatch.setattr(docker_adapter_module, "settings", https_settings)
    adapter = docker_adapter_module.DockerAdapter()
    assert adapter._create_tls_config() is not None

    monkeypatch.setattr(
        docker_adapter_module,
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
        docker_adapter_module,
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
            version="0.3.3",
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
        docker_adapter_module,
        "TLSConfig",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    tls_without_hostname = adapter._create_tls_config()
    assert tls_without_hostname is not None


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
    container_manager_module: ModuleType,
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
    monkeypatch.setattr(
        "pytmbot.adapters.docker.container_manager.time.time", lambda: 100.0
    )
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
    def _client_context() -> Iterator[SimpleNamespace]:
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
    method_name = "_rename_container"
    rename_container = cast(
        Callable[[int, str, str], None],
        getattr(manager, method_name),
    )

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
            ContainerAction,
            "from_str",
            lambda _action: cast(ContainerAction, "unknown"),
        )
        with pytest.raises(ValueError, match="Invalid action"):
            manager.managing_container(3001, "cid", "start")

    monkeypatch.setattr(
        manager,
        "_start_container",
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
        "pytmbot.adapters.docker._adapter.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    client = _FlakyPingClient()
    version = adapter._test_connection(client)

    assert version is not None
    assert version.get("Version") == "29.2.0"
    assert client.ping_calls == 3
    assert sleep_calls == [0.5, 1.0]
