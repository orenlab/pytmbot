"""Container references: validation, exact targeting and outage reporting."""

from __future__ import annotations

import time
from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest
from docker.errors import APIError, NotFound
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout
from telebot import TeleBot
from telebot.types import CallbackQuery, User

import pytmbot.adapters.docker.container_manager as container_manager_module
import pytmbot.adapters.docker.containers_info as containers_info_module
import pytmbot.adapters.docker.utils as docker_utils_module
import pytmbot.handlers.handlers_util.docker as handlers_docker
from pytmbot.exceptions import (
    ContainerNotFoundError,
    DockerConnectionError,
    DockerOperationException,
    InvalidContainerReferenceError,
)
from tests._docker_sdk_fakes import (
    FakeDockerApi,
    api_calls,
    install_client,
    make_client,
    make_container_attrs,
)

UPPER_ID = "aa" + "1" * 62  # container the admin looks at, named "DB"
OTHER_ID = "db7f" + "2" * 60  # unrelated container whose ID starts with "db"
PLEX_ID = "ee" + "3" * 62

_MODULES: list[ModuleType] = [
    containers_info_module,
    docker_utils_module,
    container_manager_module,
]


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> FakeDockerApi:
    api = FakeDockerApi(
        [
            make_container_attrs(UPPER_ID, "DB"),
            make_container_attrs(OTHER_ID, "metrics-collector"),
            make_container_attrs(PLEX_ID, "Plex", status="exited"),
        ]
    )
    install_client(monkeypatch, _MODULES, make_client(api))
    docker_utils_module.invalidate_container_state_cache()
    return api


def _allow_admin(monkeypatch: pytest.MonkeyPatch, user_id: int) -> None:
    monkeypatch.setattr(
        container_manager_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_admins_ids=[user_id]),
            docker=SimpleNamespace(),
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


@pytest.mark.parametrize(
    "reference",
    ["DB", "metrics-collector", "a", "web_1.prod", UPPER_ID, UPPER_ID[:12], "x" * 255],
)
def test_validate_container_reference_accepts_names_and_ids(reference: str) -> None:
    assert docker_utils_module.validate_container_reference(reference) == reference
    assert handlers_docker.validate_container_name(reference) is True


@pytest.mark.parametrize(
    "reference",
    ["", "   ", "../etc", "a..b", "a/b", "-rm", ".hidden", "a b", "x" * 256, "a:b"],
)
def test_validate_container_reference_rejects_invalid(reference: str) -> None:
    with pytest.raises(InvalidContainerReferenceError):
        docker_utils_module.validate_container_reference(reference)
    assert handlers_docker.validate_container_name(reference) is False


def test_validate_container_reference_rejects_non_strings() -> None:
    with pytest.raises(InvalidContainerReferenceError):
        docker_utils_module.validate_container_reference(None)
    with pytest.raises(InvalidContainerReferenceError):
        docker_utils_module.validate_container_reference(42)


def test_details_resolve_exact_name_without_lowercasing(
    fake_api: FakeDockerApi,
) -> None:
    container = handlers_docker.get_container_full_details("DB")
    assert getattr(container, "id", None) == UPPER_ID
    assert api_calls(fake_api, "inspect_container") == ["DB"]

    by_short_id = containers_info_module.fetch_full_container_details(UPPER_ID[:12])
    assert by_short_id is not None and by_short_id.id == UPPER_ID


def test_lowercased_name_never_resolves_to_other_container(
    fake_api: FakeDockerApi,
) -> None:
    # dockerd resolves "db" by unique ID prefix to "metrics-collector".
    assert containers_info_module.fetch_full_container_details("db") is None
    assert handlers_docker.get_comprehensive_container_details("db") is None
    with pytest.raises(ContainerNotFoundError):
        docker_utils_module.get_container_safely("db")


def test_stop_with_stale_reference_does_not_touch_other_container(
    fake_api: FakeDockerApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_admin(monkeypatch, 4201)
    manager = container_manager_module.ContainerManager()

    with pytest.raises(ContainerNotFoundError):
        manager.managing_container(4201, "db", action="stop")
    assert api_calls(fake_api, "stop") == []
    assert fake_api._state(OTHER_ID)["Status"] == "running"

    manager.managing_container(4201, "DB", action="stop")
    assert api_calls(fake_api, "stop") == [(UPPER_ID, 10)]


def test_manage_action_rejects_invalid_reference_before_docker(
    fake_api: FakeDockerApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_admin(monkeypatch, 4202)
    manager = container_manager_module.ContainerManager()
    with pytest.raises(InvalidContainerReferenceError):
        manager.managing_container(4202, "../db", action="stop")
    assert fake_api.calls == []


def test_container_state_keeps_reference_case(fake_api: FakeDockerApi) -> None:
    assert docker_utils_module.get_container_state("Plex") == "exited"
    assert docker_utils_module.get_container_state("plex") is None


def _callback_query(data: str, user_id: int = 101) -> CallbackQuery:
    user_ctor = cast(Callable[..., User], User)
    callback_ctor = cast(Callable[..., CallbackQuery], CallbackQuery)
    return callback_ctor(
        id=1,
        from_user=user_ctor(id=user_id, is_bot=False, first_name="T"),
        data=data,
        chat_instance="chat-1",
        json_string="{}",
    )


def test_callback_context_preserves_reference_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_docker,
        "authorize_docker_callback_request",
        lambda *_args, **_kwargs: (True, ""),
    )
    context = handlers_docker.get_authorized_container_callback_context(
        _callback_query("__manage__:Plex:101"),
        cast(TeleBot, SimpleNamespace()),
        operation_label="Managing",
        missing_user_event="missing",
        denied_event="denied",
    )
    assert context is not None
    assert context.container_name == "Plex"


@pytest.mark.parametrize(
    "transport_error",
    [RequestsConnectionError("socket refused"), ReadTimeout("read timed out")],
)
def test_outage_is_reported_as_connection_error_not_not_found(
    fake_api: FakeDockerApi, transport_error: Exception
) -> None:
    fake_api.fail_on["inspect_container"] = transport_error

    with pytest.raises(DockerConnectionError):
        docker_utils_module.get_container_safely("DB")
    with pytest.raises(DockerConnectionError):
        containers_info_module.fetch_full_container_details("DB")
    with pytest.raises(DockerConnectionError):
        handlers_docker.get_comprehensive_container_details("DB")
    with pytest.raises(DockerConnectionError):
        docker_utils_module.get_container_state("DB")
    with pytest.raises(DockerConnectionError):
        containers_info_module.fetch_container_logs("DB")


def test_outage_during_logs_read_is_connection_error(fake_api: FakeDockerApi) -> None:
    fake_api.fail_on["logs"] = RequestsConnectionError("daemon went away")
    with pytest.raises(DockerConnectionError):
        containers_info_module.fetch_container_logs("DB")


def test_logs_by_exact_reference_and_none_when_missing(
    fake_api: FakeDockerApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = containers_info_module.fetch_container_logs(UPPER_ID[:12])
    assert logs == f"logs of {UPPER_ID[:12]}\n"
    assert containers_info_module.fetch_container_logs("missing") is None

    monkeypatch.setattr(handlers_docker, "sanitize_logs", lambda logs, *_: logs)
    call = _callback_query("__get_logs__:missing:101")
    assert handlers_docker.get_sanitized_logs("missing", call, "TOKEN") is None


def test_logs_api_error_becomes_operation_error(fake_api: FakeDockerApi) -> None:
    fake_api.fail_on["logs"] = APIError(
        "409 Client Error: can not get logs from container which is dead or "
        "marked for removal"
    )
    with pytest.raises(DockerOperationException):
        containers_info_module.fetch_container_logs("DB")


def test_logs_for_container_removed_after_lookup_is_none(
    fake_api: FakeDockerApi,
) -> None:
    fake_api.fail_on["logs"] = NotFound("No such container")
    assert containers_info_module.fetch_container_logs("DB") is None
