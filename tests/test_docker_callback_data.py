from __future__ import annotations

import pytest

from pytmbot.handlers.docker_handlers.callback_data import (
    CONFIRM_RESTART_CALLBACK_PREFIX,
    CONFIRM_STOP_CALLBACK_PREFIX,
    MANAGE_CALLBACK_PREFIX,
    START_CALLBACK_PREFIX,
    STOP_CALLBACK_PREFIX,
    TELEGRAM_CALLBACK_DATA_MAX_BYTES,
    CallbackDataTooLongError,
    ContainerCallback,
    build_callback_data,
    build_container_callback,
    container_short_id,
    is_valid_container_ref,
    parse_callback_user_id,
    parse_container_callback,
    post_auth_return_callback,
    post_auth_return_label,
)
from pytmbot.handlers.handlers_util.callback_auth import parse_bound_user_id

_FULL_ID = "1a2b3c4d5e6f" + "0" * 52


def test_build_callback_data_enforces_telegram_limit_without_truncating() -> None:
    exact = build_callback_data("x" * (TELEGRAM_CALLBACK_DATA_MAX_BYTES - 2), 1)
    assert len(exact.encode()) == TELEGRAM_CALLBACK_DATA_MAX_BYTES

    with pytest.raises(CallbackDataTooLongError):
        build_callback_data("__get_logs__", "open", "nextcloud-aio-mastercontainer" * 2)
    # Multi-byte characters count as bytes, not characters.
    with pytest.raises(CallbackDataTooLongError):
        build_callback_data("é" * 33)
    with pytest.raises(ValueError):
        build_callback_data("__manage__", "", 1)
    with pytest.raises(ValueError):
        build_callback_data("__manage__", "a:b", 1)


def test_container_callbacks_carry_short_id_and_never_lowercase() -> None:
    short_id = container_short_id(_FULL_ID)
    assert short_id == "1a2b3c4d5e6f"
    assert container_short_id("NOT-HEX-ID") is None
    assert container_short_id("abc") is None
    assert container_short_id(None) is None

    payload = build_container_callback(STOP_CALLBACK_PREFIX, "1a2b3c4d5e6f", 7)
    assert payload == "__stop__:1a2b3c4d5e6f:7"
    # Names from older buttons keep their exact case.
    assert parse_container_callback(
        "__manage__:DB:7", prefixes={MANAGE_CALLBACK_PREFIX}
    ) == ContainerCallback(prefix=MANAGE_CALLBACK_PREFIX, container_ref="DB", user_id=7)


@pytest.mark.parametrize(
    "callback_data",
    [
        None,
        "",
        "__manage__",
        "__manage__:db",
        "__other__:db:7",
        "__manage__::7",
        "__manage__:../etc:7",
        "__manage__:-db:7",
        "__manage__:db:0",
        "__manage__:db:-7",
        "__manage__:db:７",
        "__manage__:db:7:extra",
    ],
)
def test_parse_container_callback_rejects_invalid_payloads(
    callback_data: str | None,
) -> None:
    assert (
        parse_container_callback(callback_data, prefixes={MANAGE_CALLBACK_PREFIX})
        is None
    )


def test_container_ref_and_user_id_validation() -> None:
    assert is_valid_container_ref("1a2b3c4d5e6f")
    assert is_valid_container_ref("Nextcloud_AIO.master-1")
    assert not is_valid_container_ref("")
    assert not is_valid_container_ref("a" * 65)
    assert not is_valid_container_ref("bad|name")
    assert parse_callback_user_id("123") == 123
    assert parse_callback_user_id("0") is None
    assert parse_callback_user_id("12a") is None
    with pytest.raises(ValueError):
        build_container_callback(MANAGE_CALLBACK_PREFIX, "bad/ref", 1)


@pytest.mark.parametrize(
    "prefix",
    [
        START_CALLBACK_PREFIX,
        STOP_CALLBACK_PREFIX,
        "__restart__",
        CONFIRM_STOP_CALLBACK_PREFIX,
        CONFIRM_RESTART_CALLBACK_PREFIX,
    ],
)
def test_post_auth_return_target_for_actions_is_manage_screen(prefix: str) -> None:
    target = post_auth_return_callback(f"{prefix}:1a2b3c4d5e6f:7")
    assert target == "__manage__:1a2b3c4d5e6f:7"
    assert target is not None
    assert post_auth_return_label(target) == "container actions"


def test_post_auth_return_target_keeps_read_only_screens() -> None:
    logs = "__get_logs__:open:1a2b3c4d5e6f:7"
    assert post_auth_return_callback(logs) == logs
    assert post_auth_return_label(logs) == "container logs"
    assert post_auth_return_label("__container_extra__:runtime:x:7") == (
        "container details"
    )
    assert post_auth_return_label("__unknown__:x") is None
    assert post_auth_return_callback("__stop__") is None
    # The manage prefix is one byte longer than "__start__".
    assert post_auth_return_callback("__start__:" + "a" * 50 + ":1234") is None


def test_parse_bound_user_id() -> None:
    assert parse_bound_user_id("__manage__:1a2b3c4d5e6f:42") == 42
    assert parse_bound_user_id("__get_logs__:nav:0123456789ab:3:42") == 42
    assert parse_bound_user_id("back_to_containers") is None
    assert parse_bound_user_id("__x__:name") is None
    assert parse_bound_user_id("__x__:0") is None
    assert parse_bound_user_id("__x__:４２") is None
    assert parse_bound_user_id(None) is None
