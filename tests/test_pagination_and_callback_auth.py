from __future__ import annotations

from dataclasses import dataclass

import pytest
from telebot.types import CallbackQuery, User

import pytmbot.handlers.handlers_util.callback_auth as callback_auth
from pytmbot.handlers.docker_handlers.pagination import (
    CONTAINER_FULL_INFO_CALLBACK_PREFIX,
    build_container_full_info_callback_data,
    build_page_callback_data,
    paginate_items,
    parse_container_full_info_callback_data,
    parse_page_callback_data,
)
from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)


def test_paginate_items_normalizes_page_and_size() -> None:
    window = paginate_items(list(range(10)), page=99, page_size=0)
    assert window.page == 10
    assert window.total_pages == 10
    assert window.page_size == 1
    assert window.items == [9]

    first_page = paginate_items(["a", "b", "c"], page=-5, page_size=2)
    assert first_page.page == 1
    assert first_page.total_pages == 2
    assert first_page.items == ["a", "b"]


def test_parse_and_build_page_callback_data() -> None:
    payload = build_page_callback_data(prefix="containers_page", page=-3, user_id=42)
    assert payload == "containers_page:1:42"
    assert parse_page_callback_data(payload, prefix="containers_page") == (1, 42)
    assert parse_page_callback_data("wrong:1:42", prefix="containers_page") is None
    assert parse_page_callback_data("containers_page:0:42", prefix="containers_page") is None
    assert parse_page_callback_data("containers_page:x:42", prefix="containers_page") is None


def test_parse_and_build_container_full_info_callback_data() -> None:
    payload = build_container_full_info_callback_data(
        container_ref="  PyTMBot  ",
        user_id=101,
        page=0,
    )
    assert payload == f"{CONTAINER_FULL_INFO_CALLBACK_PREFIX}:pytmbot:101:1"
    assert parse_container_full_info_callback_data(payload) == ("pytmbot", 101, 1)

    payload_without_page = build_container_full_info_callback_data(
        container_ref="redis",
        user_id=101,
    )
    assert parse_container_full_info_callback_data(payload_without_page) == ("redis", 101, None)
    assert parse_container_full_info_callback_data("broken") is None
    assert parse_container_full_info_callback_data(
        f"{CONTAINER_FULL_INFO_CALLBACK_PREFIX}::101"
    ) is None
    assert parse_container_full_info_callback_data(
        f"{CONTAINER_FULL_INFO_CALLBACK_PREFIX}:redis:bad"
    ) is None
    assert parse_container_full_info_callback_data(
        f"{CONTAINER_FULL_INFO_CALLBACK_PREFIX}:redis:101:0"
    ) is None


def test_parse_callback_target_user() -> None:
    assert parse_callback_target_user("prefix", "prefix") is None
    assert parse_callback_target_user("prefix:42", "prefix") == 42

    with pytest.raises(ValueError):
        parse_callback_target_user(None, "prefix")
    with pytest.raises(ValueError):
        parse_callback_target_user("other:42", "prefix")
    with pytest.raises(ValueError):
        parse_callback_target_user("prefix:", "prefix")
    with pytest.raises(ValueError):
        parse_callback_target_user("prefix:not-an-int", "prefix")


@dataclass
class _FakeAccessControl:
    allowed_user_ids: set[int]
    allowed_admins_ids: set[int]


@dataclass
class _FakeSettings:
    access_control: _FakeAccessControl


class _FakeSessionManager:
    def __init__(self, authenticated_users: set[int]) -> None:
        self.authenticated_users = authenticated_users

    def is_authenticated(self, user_id: int) -> bool:
        return user_id in self.authenticated_users


def _make_callback_query(user_id: int) -> CallbackQuery:
    user = User(
        id=user_id,
        is_bot=False,
        first_name="Test",
        username="test_user",
    )
    return CallbackQuery(
        id="cbq-1",
        from_user=user,
        data="payload",
        chat_instance="chat-1",
        json_string="{}",
    )


def test_authorize_callback_request_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        callback_auth,
        "settings",
        _FakeSettings(
            access_control=_FakeAccessControl(
                allowed_user_ids={1, 2},
                allowed_admins_ids={2},
            )
        ),
    )
    monkeypatch.setattr(
        callback_auth,
        "session_manager",
        _FakeSessionManager(authenticated_users={2}),
    )

    ok, msg = authorize_callback_request(_make_callback_query(99))
    assert ok is False
    assert msg == "Access denied"

    ok, msg = authorize_callback_request(
        _make_callback_query(1),
        require_admin=True,
    )
    assert ok is False
    assert msg == "Access denied"

    ok, msg = authorize_callback_request(
        _make_callback_query(1),
        target_user_id=2,
        require_owner_match=True,
    )
    assert ok is False
    assert msg == "Access denied"

    ok, msg = authorize_callback_request(
        _make_callback_query(1),
        require_session=True,
    )
    assert ok is False
    assert msg == "Not authenticated user"

    ok, msg = authorize_callback_request(
        _make_callback_query(2),
        target_user_id=2,
        require_owner_match=True,
        require_admin=True,
        require_session=True,
    )
    assert ok is True
    assert msg == ""
