"""Command arguments on container and image cards are shown to admins only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.adapters.docker.images_info as images_info_module
import pytmbot.handlers.docker_handlers.images as images_module
import pytmbot.handlers.docker_handlers.inline.container_info as info_module
import pytmbot.handlers.docker_handlers.inline.image_callback as image_callback_module
import pytmbot.handlers.docker_handlers.inline.image_info as image_info_module
import pytmbot.handlers.handlers_util.docker as handlers_docker
from pytmbot.adapters.docker.utils import SECRET_MASK
from tests._telebot_objects import PayloadDict, telegram_object_from_payload

# Both are allowed users in ``pytmbot.yaml.sample``; only the first is an admin.
_ADMIN = 123456789
_USER = 987654321
_SHORT_ID = "1a2b3c4d5e6f"
_IMAGE_REF = "4" * 12
_ADMINS_ONLY_NOTE = "Arguments are visible to admins only."
_MASKED_NOTE = "Values that look like secrets are masked."
type _Handler = Callable[[CallbackQuery, TeleBot], object]


def _make_call(data: str, user_id: int) -> CallbackQuery:
    payload: PayloadDict = {
        "id": "cbq-1",
        "from": {"id": user_id, "is_bot": False, "first_name": "User"},
        "chat_instance": "ci",
        "data": data,
        "message": {
            "message_id": 7,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
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

    def html(self) -> str:
        assert self.edits, self.alerts
        return str(getattr(self.edits[-1]["rich_message"], "html", ""))


def _unwrap(handler: object) -> _Handler:
    # Strip ``logger.catch`` and ``logger.session_decorator``.
    for _ in range(2):
        handler = getattr(handler, "__wrapped__", handler)
    return cast(_Handler, handler)


def _allow_any_callback(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    """Accept every callback, as a relaxed owner check would."""
    monkeypatch.setattr(
        module, "authorize_docker_callback_request", lambda **kwargs: (True, "")
    )


# --- container card -------------------------------------------------------------


@pytest.fixture
def mysql_container(monkeypatch: pytest.MonkeyPatch) -> None:
    container = SimpleNamespace(
        status="exited",
        attrs={
            "Id": _SHORT_ID + "0" * 52,
            "Name": "/db",
            "State": {"Status": "exited"},
            "Config": {
                "Image": "mysql:8",
                "Entrypoint": ["docker-entrypoint.sh"],
                "Cmd": ["mysqld", "-ps3cret"],
            },
        },
    )
    monkeypatch.setattr(
        handlers_docker, "get_container_full_details", lambda ref: container
    )


def _open_container_card(callback_user: int, viewer: int) -> str:
    bot = _Bot()
    handler = _unwrap(info_module.handle_containers_full_info)
    handler(
        _make_call(f"__get_full__:{_SHORT_ID}:{callback_user}:1", viewer),
        cast(TeleBot, bot),
    )
    return bot.html()


@pytest.mark.usefixtures("mysql_container")
def test_container_card_shows_only_executables_to_non_admins() -> None:
    html = _open_container_card(_USER, _USER)

    assert "<td>Entrypoint</td><td>docker-entrypoint.sh</td>" in html
    assert "<td>Command</td><td>mysqld</td>" in html
    assert _ADMINS_ONLY_NOTE in html
    assert SECRET_MASK not in html
    assert "s3cret" not in html
    assert "Sensitive data is hidden" not in html


@pytest.mark.usefixtures("mysql_container")
def test_container_card_shows_masked_arguments_to_admins() -> None:
    html = _open_container_card(_ADMIN, _ADMIN)

    assert f"<td>Command</td><td>mysqld -p{SECRET_MASK}</td>" in html
    assert _MASKED_NOTE in html
    assert "s3cret" not in html


@pytest.mark.usefixtures("mysql_container")
def test_container_card_trusts_the_viewer_not_the_callback_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_any_callback(monkeypatch, info_module)

    html = _open_container_card(_ADMIN, _USER)

    assert "<td>Command</td><td>mysqld</td>" in html
    assert _ADMINS_ONLY_NOTE in html


# --- image card -----------------------------------------------------------------


@pytest.fixture
def mysql_image(monkeypatch: pytest.MonkeyPatch) -> None:
    image = SimpleNamespace(
        short_id=f"sha256:{_IMAGE_REF}",
        tags=["mysql:8"],
        attrs={
            "RepoTags": ["mysql:8"],
            "Config": {
                "Entrypoint": ["docker-entrypoint.sh"],
                "Cmd": ["mysqld", "-ps3cret"],
                "Shell": ["/bin/sh", "-c"],
                "Healthcheck": {"Test": ["CMD-SHELL", "mysqladmin ping -ps3cret"]},
            },
        },
    )
    details = images_info_module.process_image_attrs(image)
    monkeypatch.setattr(images_module, "_images_cache", None)
    monkeypatch.setattr(images_module, "fetch_image_details", lambda: [details])


def _open_image_card(callback_user: int, viewer: int) -> str:
    bot = _Bot()
    handler = _unwrap(image_info_module.handle_image_info)
    handler(
        _make_call(f"__image_info__:{_IMAGE_REF}:{callback_user}:1", viewer),
        cast(TeleBot, bot),
    )
    return bot.html()


@pytest.mark.usefixtures("mysql_image")
def test_image_card_shows_only_executables_to_non_admins() -> None:
    html = _open_image_card(_USER, _USER)

    assert "<td>Entrypoint</td><td>docker-entrypoint.sh</td>" in html
    assert "<td>Command</td><td>mysqld</td>" in html
    assert "<td>Shell</td><td>/bin/sh</td>" in html
    assert "<td>Healthcheck</td><td>test=CMD-SHELL mysqladmin</td>" in html
    assert _ADMINS_ONLY_NOTE in html
    assert SECRET_MASK not in html
    assert "s3cret" not in html


@pytest.mark.usefixtures("mysql_image")
def test_image_card_shows_masked_arguments_to_admins() -> None:
    html = _open_image_card(_ADMIN, _ADMIN)

    assert f"<td>Command</td><td>mysqld -p{SECRET_MASK}</td>" in html
    assert f"test=CMD-SHELL mysqladmin ping -p{SECRET_MASK}" in html
    assert _MASKED_NOTE in html
    assert "s3cret" not in html


@pytest.mark.usefixtures("mysql_image")
def test_image_card_trusts_the_viewer_not_the_callback_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_any_callback(monkeypatch, image_callback_module)

    html = _open_image_card(_ADMIN, _USER)

    assert "<td>Command</td><td>mysqld</td>" in html
    assert _ADMINS_ONLY_NOTE in html
