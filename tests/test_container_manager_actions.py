"""ContainerManager: state validation, in-flight lock, real errors, --rm stops."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from docker.api.client import APIClient
from docker.errors import APIError
from requests.exceptions import ConnectionError as RequestsConnectionError

import pytmbot.adapters.docker.container_manager as container_manager_module
import pytmbot.adapters.docker.utils as docker_utils_module
from pytmbot.exceptions import (
    ContainerActionInProgressError,
    ContainerStateConflictError,
    DockerConnectionError,
)
from pytmbot.settings import load_settings_from_yaml
from tests._docker_sdk_fakes import (
    FakeDockerApi,
    api_calls,
    install_client,
    make_client,
    make_container_attrs,
)

RUNNING_ID = "1a" + "0" * 62
EXITED_ID = "2b" + "0" * 62
CREATED_ID = "3c" + "0" * 62
PAUSED_ID = "4d" + "0" * 62
ADMIN_ID = 5150


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> FakeDockerApi:
    api = FakeDockerApi(
        [
            make_container_attrs(RUNNING_ID, "web"),
            make_container_attrs(EXITED_ID, "job", status="exited"),
            make_container_attrs(CREATED_ID, "init", status="created"),
            make_container_attrs(PAUSED_ID, "frozen", status="paused"),
        ]
    )
    install_client(
        monkeypatch,
        [container_manager_module, docker_utils_module],
        make_client(api),
    )
    monkeypatch.setattr(
        container_manager_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_admins_ids=[ADMIN_ID]),
            docker=SimpleNamespace(stop_timeout=7, restart_timeout=3),
        ),
    )
    monkeypatch.setattr(
        container_manager_module,
        "session_manager",
        SimpleNamespace(
            is_authenticated=lambda _uid: True,
            get_session_info=lambda _uid: {"created_at": time.time()},
        ),
    )
    monkeypatch.setattr(
        container_manager_module,
        "_rate_limiter",
        container_manager_module._UserRateLimiter(
            min_interval=0.0, stale_after=300.0, max_users=16
        ),
    )
    docker_utils_module.invalidate_container_state_cache()
    return api


@pytest.fixture
def manager() -> container_manager_module.ContainerManager:
    return container_manager_module.ContainerManager()


@pytest.mark.parametrize(
    ("reference", "action", "state"),
    [
        ("web", "start", "running"),
        ("frozen", "start", "paused"),
        ("job", "stop", "exited"),
        ("init", "stop", "created"),
    ],
)
def test_state_conflicts_are_rejected_before_acting(
    fake_api: FakeDockerApi,
    manager: container_manager_module.ContainerManager,
    reference: str,
    action: str,
    state: str,
) -> None:
    with pytest.raises(ContainerStateConflictError) as error_info:
        manager.managing_container(ADMIN_ID, reference, action=action)
    assert error_info.value.state == state
    assert api_calls(fake_api, action) == []


def test_lifecycle_actions_succeed_and_pass_timeouts(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    assert manager.managing_container(ADMIN_ID, "web", action="stop") is None
    assert manager.managing_container(ADMIN_ID, "job", action="start") is None
    # Restarting a stopped container is allowed: Docker starts it.
    assert manager.managing_container(ADMIN_ID, "web", action="restart") is None
    assert manager.managing_container(ADMIN_ID, "frozen", action="stop") is None

    assert api_calls(fake_api, "stop") == [(RUNNING_ID, 7), (PAUSED_ID, 7)]
    assert api_calls(fake_api, "start") == [EXITED_ID]
    assert api_calls(fake_api, "restart") == [(RUNNING_ID, 3)]


def test_stopping_auto_removed_container_is_success(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    fake_api.remove_on_stop = {RUNNING_ID}  # `docker run --rm`
    assert manager.managing_container(ADMIN_ID, RUNNING_ID[:12], action="stop") is None
    assert RUNNING_ID not in fake_api.containers_db


def test_stop_reporting_removing_status_is_success(
    fake_api: FakeDockerApi,
    manager: container_manager_module.ContainerManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stop = fake_api.stop

    def _stop_then_removing(container: str, timeout: int | None = None) -> None:
        original_stop(container, timeout)
        fake_api.set_status(container, "removing")

    monkeypatch.setattr(fake_api, "stop", _stop_then_removing)
    assert manager.managing_container(ADMIN_ID, "web", action="stop") is None


def test_unexpected_final_state_is_reported(
    fake_api: FakeDockerApi,
    manager: container_manager_module.ContainerManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fake_api, "start", lambda container, *a, **k: None)
    with pytest.raises(RuntimeError, match="current status: exited"):
        manager.managing_container(ADMIN_ID, "job", action="start")


def test_real_docker_errors_are_not_replaced(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    fake_api.fail_on["stop"] = APIError("409 Conflict: container is paused")
    with pytest.raises(APIError, match="container is paused"):
        manager.managing_container(ADMIN_ID, "web", action="stop")


def test_transport_failure_during_action_is_connection_error(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    fake_api.fail_on["restart"] = RequestsConnectionError("socket closed")
    with pytest.raises(DockerConnectionError):
        manager.managing_container(ADMIN_ID, "web", action="restart")


def test_concurrent_action_on_same_container_is_rejected(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    with container_manager_module._in_flight_actions.hold(RUNNING_ID, "restart"):
        with pytest.raises(ContainerActionInProgressError):
            # Same container through its name: the lock is keyed by full ID.
            manager.managing_container(ADMIN_ID, "web", action="stop")
        # Other containers are not blocked.
        assert manager.managing_container(ADMIN_ID, "job", action="start") is None
    assert api_calls(fake_api, "stop") == []

    # Released after the first action finished (also after failures).
    assert manager.managing_container(ADMIN_ID, "web", action="stop") is None


def test_in_flight_lock_is_released_after_failure(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    fake_api.fail_on["stop"] = APIError("boom")
    with pytest.raises(APIError):
        manager.managing_container(ADMIN_ID, "web", action="stop")
    del fake_api.fail_on["stop"]
    assert manager.managing_container(ADMIN_ID, "web", action="stop") is None


def test_rate_limit_is_shared_by_all_actions(
    fake_api: FakeDockerApi,
    manager: container_manager_module.ContainerManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        container_manager_module,
        "_rate_limiter",
        container_manager_module._UserRateLimiter(
            min_interval=60.0, stale_after=300.0, max_users=16
        ),
    )
    manager.managing_container(ADMIN_ID, "web", action="stop")
    with pytest.raises(PermissionError, match="Rate limit"):
        manager.managing_container(ADMIN_ID, "job", action="start")
    assert api_calls(fake_api, "start") == []


def test_state_cache_is_invalidated_after_action(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    assert docker_utils_module.get_container_state("web") == "running"
    manager.managing_container(ADMIN_ID, "web", action="stop")
    assert docker_utils_module.get_container_state("web") == "exited"


def test_rename_errors_keep_their_message(
    fake_api: FakeDockerApi, manager: container_manager_module.ContainerManager
) -> None:
    with pytest.raises(ValueError, match="too long"):
        manager.managing_container(
            ADMIN_ID, "web", action="rename", new_container_name="x" * 65
        )
    with pytest.raises(ValueError, match="Invalid action"):
        manager.managing_container(ADMIN_ID, "web", action="explode")


def test_rate_limiter_evicts_oldest_users(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = container_manager_module._UserRateLimiter(
        min_interval=1.0, stale_after=300.0, max_users=2
    )
    clock = iter([100.0, 101.0, 102.0, 103.0, 103.5])
    monkeypatch.setattr(
        "pytmbot.adapters.docker.container_manager.time.time", lambda: next(clock)
    )
    for user_id in (1, 2, 3, 4):
        assert limiter.register(user_id) is None
    assert limiter.register(4) == pytest.approx(0.5)


def test_configured_grace_periods_reach_docker(
    fake_api: FakeDockerApi,
    manager: container_manager_module.ContainerManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sample_path = Path(__file__).resolve().parents[1] / "pytmbot.yaml.sample"
    config = yaml.safe_load(sample_path.read_text(encoding="utf-8"))
    config["docker"].update(stop_timeout=120, restart_timeout=45)
    config_path = tmp_path / "pytmbot.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("PYTMBOT_CONFIG_PATH", str(config_path))
    load_settings_from_yaml.cache_clear()
    try:
        docker_settings = load_settings_from_yaml().docker
    finally:
        load_settings_from_yaml.cache_clear()
    monkeypatch.setattr(
        container_manager_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_admins_ids=[ADMIN_ID]),
            docker=docker_settings,
        ),
    )

    manager.managing_container(ADMIN_ID, "web", action="stop")
    manager.managing_container(ADMIN_ID, "web", action="restart")

    assert api_calls(fake_api, "stop") == [(RUNNING_ID, 120)]
    assert api_calls(fake_api, "restart") == [(RUNNING_ID, 45)]


@pytest.mark.parametrize("operation", ["stop", "restart"])
def test_docker_sdk_adds_grace_period_to_request_timeout(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    # The adapter sets api.timeout to docker.timeout; docker-py must extend the
    # stop/restart request by the grace period so a long grace is not cut short.
    api = APIClient(base_url="tcp://127.0.0.1:2375", version="1.43", timeout=10)
    posted: list[dict[str, object]] = []

    def _post(url: str, **kwargs: object) -> SimpleNamespace:
        del url
        posted.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(api, "_post", _post)
    monkeypatch.setattr(api, "_raise_for_status", lambda _response: None)

    getattr(api, operation)(RUNNING_ID, timeout=300)

    assert posted == [{"params": {"t": 300}, "timeout": 310}]
