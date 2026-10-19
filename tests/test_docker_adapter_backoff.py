"""Docker outages: negative cache, short probes and closing failed clients."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from docker.errors import DockerException
from requests.exceptions import ReadTimeout

import pytmbot.adapters.docker._adapter as adapter_module
from pytmbot.adapters.docker._adapter import (
    DockerAdapter,
    _ConnectionBackoff,
    _UnavailableDockerApi,
    _UnavailableDockerClient,
    reset_connection_backoff,
)
from pytmbot.exceptions import DockerConnectionError


@pytest.fixture(autouse=True)
def _docker_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(
        adapter_module,
        "settings",
        SimpleNamespace(
            docker=SimpleNamespace(
                host=["unix:///var/run/docker.sock"],
                timeout=20,
                strict_access=False,
            ),
            version="0.5.1",
        ),
    )
    monkeypatch.setattr(
        "pytmbot.adapters.docker._adapter.time.sleep", lambda _seconds: None
    )
    reset_connection_backoff()
    yield
    reset_connection_backoff()


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


class _ProbeClient:
    """DockerClient stand-in recording construction kwargs and closes."""

    instances: list[_ProbeClient] = []
    ping_error: Exception | None = None

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.ping_calls = 0
        self.api = SimpleNamespace(_version="1.47", timeout=kwargs.get("timeout"))
        _ProbeClient.instances.append(self)

    def ping(self) -> bool:
        self.ping_calls += 1
        if _ProbeClient.ping_error is not None:
            raise _ProbeClient.ping_error
        return True

    def version(self) -> dict[str, str]:
        return {"Version": "28.0.0"}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def probe_client(monkeypatch: pytest.MonkeyPatch) -> type[_ProbeClient]:
    _ProbeClient.instances = []
    _ProbeClient.ping_error = None
    monkeypatch.setattr(adapter_module, "DockerClient", _ProbeClient)
    return _ProbeClient


def test_backoff_delays_grow_exponentially_and_are_capped() -> None:
    backoff = _ConnectionBackoff(
        base_seconds=2.0, max_seconds=60.0, probe_window_seconds=30.0
    )
    assert [backoff.delay_for(failures) for failures in range(1, 8)] == [
        2.0,
        4.0,
        8.0,
        16.0,
        32.0,
        60.0,
        60.0,
    ]


def test_backoff_window_claim_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(
        "pytmbot.adapters.docker._adapter.time.monotonic", clock.monotonic
    )
    backoff = _ConnectionBackoff(
        base_seconds=2.0, max_seconds=60.0, probe_window_seconds=30.0
    )
    key = "unix:///var/run/docker.sock"

    assert backoff.try_acquire(key) is None  # healthy: everyone may connect
    assert backoff.record_failure(key, "refused") == 2.0
    assert "refused" in str(backoff.try_acquire(key))  # inside the window

    clock.now += 2.0
    assert backoff.try_acquire(key) is None  # first caller claims the probe
    assert backoff.try_acquire(key) is not None  # others keep failing fast
    clock.now += 30.0
    assert backoff.try_acquire(key) is None  # a lost probe cannot block forever

    assert backoff.record_failure(key, "refused") == 4.0
    backoff.record_success(key)
    assert backoff.try_acquire(key) is None


def test_hung_daemon_is_probed_once_then_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructions: list[dict[str, object]] = []

    def _hung_client(**kwargs: object) -> object:
        constructions.append(kwargs)
        raise DockerException("Error while fetching server API version: timed out")

    monkeypatch.setattr(adapter_module, "DockerClient", _hung_client)
    adapter = DockerAdapter()
    for _ in range(4):
        with adapter as client:
            assert isinstance(client, _UnavailableDockerClient)

    assert len(constructions) == 1
    assert constructions[0]["timeout"] == DockerAdapter._CONNECTION_TEST_TIMEOUT


def test_backoff_is_shared_by_thread_local_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructions: list[object] = []

    def _refused(**_kwargs: object) -> object:
        constructions.append(1)
        raise DockerException("connection refused")

    monkeypatch.setattr(adapter_module, "DockerClient", _refused)
    with DockerAdapter():
        pass
    with DockerAdapter() as second_thread_client:
        assert isinstance(second_thread_client, _UnavailableDockerClient)
    assert len(constructions) == 1


def test_strict_mode_raises_connection_error_inside_backoff_window(
    probe_client: type[_ProbeClient],
) -> None:
    probe_client.ping_error = DockerException("ping failed")
    adapter = DockerAdapter()
    adapter._strict_docker_access = True

    with pytest.raises(DockerConnectionError):
        adapter.__enter__()
    with pytest.raises(DockerConnectionError, match="retry in"):
        adapter.__enter__()
    assert len(probe_client.instances) == 1


def test_client_failing_connection_test_is_closed(
    probe_client: type[_ProbeClient],
) -> None:
    probe_client.ping_error = DockerException("ping failed")
    adapter = DockerAdapter()
    with adapter as client:
        assert isinstance(client, _UnavailableDockerClient)

    assert len(probe_client.instances) == 1
    assert probe_client.instances[0].closed is True
    assert (
        probe_client.instances[0].ping_calls == DockerAdapter._CONNECTION_TEST_RETRIES
    )


def test_probe_timeouts_are_not_retried(probe_client: type[_ProbeClient]) -> None:
    probe_client.ping_error = ReadTimeout("read timed out")
    with DockerAdapter():
        pass
    assert probe_client.instances[0].ping_calls == 1
    assert probe_client.instances[0].closed is True


def test_successful_probe_switches_to_regular_timeout_and_clears_backoff(
    probe_client: type[_ProbeClient],
) -> None:
    adapter_module._CONNECTION_BACKOFF.record_failure(
        "unix:///var/run/docker.sock", "old outage"
    )
    adapter_module._CONNECTION_BACKOFF._entries[
        "unix:///var/run/docker.sock"
    ].retry_at = 0.0

    adapter = DockerAdapter()
    with adapter as client:
        assert client is probe_client.instances[0]

    created = probe_client.instances[0]
    assert created.kwargs["timeout"] == DockerAdapter._CONNECTION_TEST_TIMEOUT
    assert created.api.timeout == 20  # configured per-request timeout
    assert adapter_module._CONNECTION_BACKOFF.try_acquire(adapter._docker_url) is None

    with adapter as reused:
        assert reused is created
    assert len(probe_client.instances) == 1


def test_default_request_timeout_is_short_for_interactive_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter_module,
        "settings",
        SimpleNamespace(docker=SimpleNamespace(host=["unix:///x.sock"])),
    )
    assert DockerAdapter()._timeout_config == {"timeout": 10}


def test_unavailable_api_raises_connection_error_and_stays_copyable() -> None:
    api = _UnavailableDockerApi("socket missing")
    with pytest.raises(DockerConnectionError, match="socket missing"):
        api.images(quiet=True)
    with pytest.raises(AttributeError):
        api.__fake_dunder__  # noqa: B018
    assert copy.copy(api)._version == "unavailable"


def test_health_check_uses_sparse_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    list_calls: list[dict[str, object]] = []

    def _list(**list_kwargs: object) -> list[object]:
        list_calls.append(list_kwargs)
        return []

    class _HealthyClient(_ProbeClient):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            self.containers = SimpleNamespace(list=_list)

        def info(self) -> dict[str, str]:
            return {"ServerVersion": "28.0.0"}

    monkeypatch.setattr("pytmbot.adapters.docker._adapter.DockerClient", _HealthyClient)
    assert DockerAdapter().health_check() is True
    assert list_calls == [{"limit": 1, "sparse": True}]


def test_request_timeout_drops_client_and_fails_fast_next_time(
    probe_client: type[_ProbeClient],
) -> None:
    adapter = DockerAdapter()
    with adapter as client:
        assert isinstance(client, _ProbeClient)

    # A request on the cached client hangs until the HTTP timeout.
    with pytest.raises(ReadTimeout), adapter:
        raise ReadTimeout("Read timed out")

    healthy_client = probe_client.instances[-1]
    assert healthy_client.closed is True
    pings_before = healthy_client.ping_calls
    with adapter as client:
        # Inside the backoff window: no new probe and no ping on the dead client.
        assert isinstance(client, _UnavailableDockerClient)
    assert len(probe_client.instances) == 1
    assert healthy_client.ping_calls == pings_before
