"""Docker read-only views: honest errors, short-ID buttons, no double escaping."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

import pytmbot.handlers.docker_handlers.containers as containers_module
import pytmbot.handlers.docker_handlers.docker as docker_menu_module
import pytmbot.handlers.docker_handlers.images as images_module
import pytmbot.handlers.docker_handlers.inline.back as back_module
import pytmbot.handlers.docker_handlers.inline.container_info as info_module
import pytmbot.handlers.docker_handlers.inline.container_runtime_info as extra_module
import pytmbot.handlers.docker_handlers.inline.image_callback as image_callback_module
import pytmbot.handlers.docker_handlers.inline.image_info as image_info_module
import pytmbot.handlers.docker_handlers.inline.images_page as images_page_module
import pytmbot.handlers.docker_handlers.inline.logs as logs_module
from pytmbot.exceptions import (
    ContainerNotFoundError,
    DockerConnectionError,
    DockerOperationException,
    ImageOperationError,
    InvalidContainerReferenceError,
)
from pytmbot.handlers.docker_handlers.user_messages import (
    CONTAINER_NOT_FOUND_TEXT,
    DOCKER_REQUEST_FAILED_TEXT,
    DOCKER_UNAVAILABLE_TEXT,
    INVALID_CONTAINER_REF_TEXT,
)
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.rich_html import rich_html_to_plain_text
from tests._telebot_objects import PayloadDict, telegram_object_from_payload

_ADMIN = 123456789
_SHORT_ID = "1a2b3c4d5e6f"
_FULL_ID = _SHORT_ID + "0" * 52
type _Handler = Callable[[CallbackQuery, TeleBot], object]


def _make_call(data: str) -> CallbackQuery:
    payload: PayloadDict = {
        "id": "cbq-1",
        "from": {"id": _ADMIN, "is_bot": False, "first_name": "Admin"},
        "chat_instance": "ci",
        "data": data,
        "message": {
            "message_id": 7,
            "date": 0,
            "chat": {"id": _ADMIN, "type": "private"},
            "from": {"id": 1111, "is_bot": True, "first_name": "bot"},
            "text": "x",
        },
    }
    return telegram_object_from_payload(
        payload,
        parser=cast(Callable[[PayloadDict], CallbackQuery], CallbackQuery.de_json),
        expected_type=CallbackQuery,
    )


@dataclass
class _Bot:
    token: str = "1111:TEST"
    alerts: list[str] = field(default_factory=list)
    edits: list[dict[str, object]] = field(default_factory=list)

    def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, **kwargs: object
    ) -> bool:
        del callback_query_id, kwargs
        self.alerts.append(str(text))
        return True

    def edit_message_text(self, **kwargs: object) -> bool:
        self.edits.append(dict(kwargs))
        return True


def _unwrap(handler: object, depth: int) -> _Handler:
    for _ in range(depth):
        handler = getattr(handler, "__wrapped__", handler)
    return cast(_Handler, handler)


def _callbacks(edit: dict[str, object]) -> list[str]:
    markup = edit["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    return [str(button.callback_data) for row in markup.keyboard for button in row]


def _raise(error: Exception) -> Callable[..., object]:
    def raiser(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise error

    return raiser


# --- extra views (volumes / networks / runtime) -------------------------------


def test_extra_views_escape_html_exactly_once() -> None:
    attrs: dict[str, object] = {
        "State": {
            "Health": {
                "Status": "unhealthy",
                "Log": [{"End": "2026-10-19T00:00:00Z", "Output": "a & b <timeout>"}],
            }
        },
        "Mounts": [{"Type": "bind", "Source": "/srv/R&D data", "Destination": "/d"}],
    }
    runtime_html = Compiler.quick_render(
        "d_container_runtime_info.jinja2",
        container_name="web",
        **extra_module._extract_runtime_context(attrs),
    )
    volumes_html = Compiler.quick_render(
        "d_container_volumes_info.jinja2",
        container_name="web",
        **extra_module._extract_volume_context(attrs),
    )
    assert "a &amp; b &lt;timeout&gt;" in runtime_html
    assert "/srv/R&amp;D data" in volumes_html
    for html in (runtime_html, volumes_html):
        assert "&amp;amp;" not in html
        assert "&amp;lt;" not in html
    assert "/srv/R&D data" in rich_html_to_plain_text(volumes_html)


@pytest.fixture
def allow_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    allow = lambda *args, **kwargs: (True, "")  # noqa: E731
    for module in (extra_module, info_module, logs_module, image_callback_module):
        monkeypatch.setattr(module, "authorize_docker_callback_request", allow)
    monkeypatch.setattr(images_page_module, "authorize_docker_callback_request", allow)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DockerConnectionError("down"), DOCKER_UNAVAILABLE_TEXT),
        (InvalidContainerReferenceError("bad"), INVALID_CONTAINER_REF_TEXT),
        (DockerOperationException("api error"), DOCKER_REQUEST_FAILED_TEXT),
    ],
)
def test_extra_views_report_docker_outage_and_invalid_refs(
    monkeypatch: pytest.MonkeyPatch,
    allow_callbacks: None,
    error: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr(extra_module, "fetch_full_container_details", _raise(error))
    bot = _Bot()
    handler = _unwrap(extra_module.handle_container_extra_info, 3)
    handler(
        _make_call(f"__container_extra__:runtime:{_SHORT_ID}:{_ADMIN}"),
        cast(TeleBot, bot),
    )
    assert bot.alerts == [expected]
    assert bot.edits == []


def test_extra_view_uses_docker_name_and_short_id(
    monkeypatch: pytest.MonkeyPatch, allow_callbacks: None
) -> None:
    container = SimpleNamespace(attrs={"Id": _FULL_ID, "Name": "/MyApp"})
    looked_up: list[str] = []

    def fetch(ref: str) -> SimpleNamespace:
        looked_up.append(ref)
        return container

    monkeypatch.setattr(extra_module, "fetch_full_container_details", fetch)
    bot = _Bot()
    handler = _unwrap(extra_module.handle_container_extra_info, 3)
    # An older button may still carry an exact-case name; it is not lowercased.
    handler(
        _make_call(f"__container_extra__:networks:MyApp:{_ADMIN}"), cast(TeleBot, bot)
    )
    assert looked_up == ["MyApp"]
    assert "MyApp" in str(getattr(bot.edits[0]["rich_message"], "html", ""))
    assert _callbacks(bot.edits[0]) == [f"__get_full__:{_SHORT_ID}:{_ADMIN}"]


# --- container details --------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (DockerConnectionError("down"), DOCKER_UNAVAILABLE_TEXT),
        (InvalidContainerReferenceError("bad"), INVALID_CONTAINER_REF_TEXT),
        (DockerOperationException("api error"), DOCKER_REQUEST_FAILED_TEXT),
        (None, CONTAINER_NOT_FOUND_TEXT),
    ],
)
def test_details_report_outage_invalid_ref_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
    allow_callbacks: None,
    result: Exception | None,
    expected: str,
) -> None:
    lookup = _raise(result) if isinstance(result, Exception) else lambda ref: None
    monkeypatch.setattr(info_module, "get_comprehensive_container_details", lookup)
    bot = _Bot()
    handler = _unwrap(info_module.handle_containers_full_info, 2)
    handler(_make_call(f"__get_full__:{_SHORT_ID}:{_ADMIN}:1"), cast(TeleBot, bot))
    assert bot.alerts == [expected]


def test_details_buttons_carry_short_id_for_long_names(
    monkeypatch: pytest.MonkeyPatch, allow_callbacks: None
) -> None:
    long_name = "immich_machine_learning_cuda_worker_01"
    monkeypatch.setattr(
        info_module,
        "get_comprehensive_container_details",
        lambda ref: {"name": long_name, "id": _SHORT_ID},
    )
    monkeypatch.setattr(Compiler, "quick_render", lambda **kwargs: "<p><b>x</b></p>")
    bot = _Bot()
    handler = _unwrap(info_module.handle_containers_full_info, 2)
    handler(_make_call(f"__get_full__:{_SHORT_ID}:{_ADMIN}:3"), cast(TeleBot, bot))

    callbacks = _callbacks(bot.edits[0])
    assert callbacks == [
        f"__container_extra__:volumes:{_SHORT_ID}:{_ADMIN}",
        f"__container_extra__:networks:{_SHORT_ID}:{_ADMIN}",
        f"__container_extra__:runtime:{_SHORT_ID}:{_ADMIN}",
        f"__get_logs__:open:{_SHORT_ID}:{_ADMIN}",
        f"__manage__:{_SHORT_ID}:{_ADMIN}",
        f"__containers_page__:3:{_ADMIN}",
    ]
    assert all(len(value.encode()) <= 64 for value in callbacks)


# --- logs -----------------------------------------------------------------------


def _open_logs(monkeypatch: pytest.MonkeyPatch, bot: _Bot) -> None:
    handler = _unwrap(logs_module.handle_get_logs, 2)
    handler(_make_call(f"__get_logs__:open:{_SHORT_ID}:{_ADMIN}"), cast(TeleBot, bot))


@pytest.mark.parametrize(
    ("container", "logs_result", "expected"),
    [
        (None, "", CONTAINER_NOT_FOUND_TEXT),
        (DockerConnectionError("down"), "", DOCKER_UNAVAILABLE_TEXT),
        ("found", None, CONTAINER_NOT_FOUND_TEXT),
        ("found", ContainerNotFoundError("gone"), CONTAINER_NOT_FOUND_TEXT),
        ("found", DockerConnectionError("down"), DOCKER_UNAVAILABLE_TEXT),
        ("found", DockerOperationException("api"), DOCKER_REQUEST_FAILED_TEXT),
        (DockerOperationException("api"), "", DOCKER_REQUEST_FAILED_TEXT),
    ],
)
def test_logs_report_not_found_and_docker_outage(
    monkeypatch: pytest.MonkeyPatch,
    allow_callbacks: None,
    container: str | Exception | None,
    logs_result: str | Exception | None,
    expected: str,
) -> None:
    def fetch(ref: str) -> SimpleNamespace | None:
        if isinstance(container, Exception):
            raise container
        return None if container is None else SimpleNamespace(id=_FULL_ID, name="web")

    def logs(ref: str, call: CallbackQuery, token: str) -> str | None:
        del ref, call, token
        if isinstance(logs_result, Exception):
            raise logs_result
        return logs_result

    monkeypatch.setattr(logs_module, "fetch_full_container_details", fetch)
    monkeypatch.setattr(logs_module, "get_sanitized_logs", logs)
    bot = _Bot()
    _open_logs(monkeypatch, bot)
    assert bot.alerts == [expected]
    assert bot.edits == []


def test_logs_open_shows_empty_logs_and_binds_navigation(
    monkeypatch: pytest.MonkeyPatch, allow_callbacks: None
) -> None:
    monkeypatch.setattr(
        logs_module,
        "fetch_full_container_details",
        lambda ref: SimpleNamespace(id=_FULL_ID, name="web"),
    )
    monkeypatch.setattr(logs_module, "get_sanitized_logs", lambda *args: "")
    bot = _Bot()
    _open_logs(monkeypatch, bot)

    html = str(getattr(bot.edits[0]["rich_message"], "html", ""))
    assert logs_module.LOGS_EMPTY_MESSAGE in html
    assert "docker logs web" in html
    callbacks = _callbacks(bot.edits[0])
    assert f"__get_full__:{_SHORT_ID}:{_ADMIN}" in callbacks
    assert f"__containers_page__:1:{_ADMIN}" in callbacks
    assert "back_to_containers" not in callbacks


# --- images -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DockerConnectionError("down"), DOCKER_UNAVAILABLE_TEXT),
        (ImageOperationError("boom"), image_callback_module.IMAGE_DETAILS_FAILED_TEXT),
    ],
)
def test_image_views_report_docker_errors(
    monkeypatch: pytest.MonkeyPatch,
    allow_callbacks: None,
    error: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr(image_info_module, "render_image_details", _raise(error))
    bot = _Bot()
    handler = _unwrap(image_info_module.handle_image_info, 2)
    handler(_make_call(f"__image_info__:0123456789ab:{_ADMIN}:1"), cast(TeleBot, bot))
    assert bot.alerts == [expected]


def test_old_position_based_image_button_is_rejected(allow_callbacks: None) -> None:
    bot = _Bot()
    handler = _unwrap(image_info_module.handle_image_info, 2)
    handler(_make_call(f"__image_info__:3:{_ADMIN}:1"), cast(TeleBot, bot))
    assert bot.alerts == [image_callback_module.INVALID_IMAGE_BUTTON_TEXT]


def test_images_page_reports_docker_outage(
    monkeypatch: pytest.MonkeyPatch, allow_callbacks: None
) -> None:
    monkeypatch.setattr(
        images_page_module, "render_images_page", _raise(DockerConnectionError("x"))
    )
    bot = _Bot()
    handler = _unwrap(images_page_module.handle_images_page, 2)
    handler(_make_call(f"__images_page__:2:{_ADMIN}"), cast(TeleBot, bot))
    assert bot.alerts == [DOCKER_UNAVAILABLE_TEXT]


def test_image_lookup_by_id_refreshes_stale_cache_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    new_image: dict[str, object] = {"id": "sha256:0123456789abcdef", "name": "app:2"}

    def load(*, force_refresh: bool = False) -> list[dict[str, object]]:
        calls.append(force_refresh)
        return [new_image] if force_refresh else [{"id": "sha256:ffffffffffff"}]

    monkeypatch.setattr(images_module, "_load_images_data", load)
    assert images_module._get_image_raw_data(image_ref="0123456789ab") == new_image
    assert calls == [False, True]
    assert images_module._get_image_raw_data(image_ref="aaaaaaaaaaaa") is None
    assert images_module.image_short_ref("sha256:0123456789abcdef") == "0123456789ab"
    assert images_module.image_short_ref("sha256:abc") is None


# --- lists and Docker menu ------------------------------------------------------


@dataclass
class _MessageBot:
    sent: list[dict[str, object]] = field(default_factory=list)

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self.sent.append({"chat_action": action, "chat_id": chat_id})
        return True

    def send_message(self, **kwargs: object) -> SimpleNamespace:
        self.sent.append(dict(kwargs))
        return SimpleNamespace(message_id=1)


def _menu_message() -> Message:
    payload: PayloadDict = {
        "message_id": 1,
        "date": 0,
        "text": "Containers",
        "chat": {"id": _ADMIN, "type": "private"},
        "from": {"id": _ADMIN, "is_bot": False, "first_name": "Admin"},
    }
    return telegram_object_from_payload(
        payload,
        parser=cast(Callable[[PayloadDict], Message], Message.de_json),
        expected_type=Message,
    )


@pytest.mark.parametrize(
    ("module", "handler_name", "fetch_name"),
    [
        (containers_module, "handle_containers", "retrieve_containers_stats"),
        (images_module, "handle_images", "fetch_image_details"),
        (docker_menu_module, "handle_docker", "fetch_docker_counters"),
    ],
)
def test_lists_and_menu_report_docker_outage(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    handler_name: str,
    fetch_name: str,
) -> None:
    monkeypatch.setattr(module, fetch_name, _raise(DockerConnectionError("down")))
    monkeypatch.setattr(images_module, "_images_cache", None)
    bot = _MessageBot()
    handler = cast(
        Callable[[Message, TeleBot], object],
        _unwrap(getattr(module, handler_name), 1),
    )
    handler(_menu_message(), cast(TeleBot, bot))
    assert bot.sent[-1]["text"] == DOCKER_UNAVAILABLE_TEXT


def test_containers_pagination_reports_docker_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        containers_module,
        "retrieve_containers_stats",
        _raise(DockerConnectionError("down")),
    )
    bot = _Bot()
    handler = _unwrap(back_module.handle_back_to_containers, 1)
    handler(_make_call(f"__containers_page__:2:{_ADMIN}"), cast(TeleBot, bot))
    assert bot.alerts == [DOCKER_UNAVAILABLE_TEXT]
    assert bot.edits == []
