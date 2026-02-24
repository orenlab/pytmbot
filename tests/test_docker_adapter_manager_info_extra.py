from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pytest
from docker.errors import DockerException

from pytmbot.exceptions import DockerConnectionError


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
