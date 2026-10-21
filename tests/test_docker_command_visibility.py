"""Command arguments are shown only to an admin in a private chat with the bot."""

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
import pytmbot.handlers.docker_handlers.inline.image_extra as image_extra_module
import pytmbot.handlers.docker_handlers.inline.image_info as image_info_module
import pytmbot.handlers.handlers_util.docker as handlers_docker
from pytmbot.adapters.docker.utils import SECRET_MASK
from tests._telebot_objects import PayloadDict, telegram_object_from_payload

# Both are allowed users in ``pytmbot.yaml.sample``; only the first is an admin.
_ADMIN = 123456789
_USER = 987654321
_GROUP = "supergroup"
_SHORT_ID = "1a2b3c4d5e6f"
_IMAGE_REF = "4" * 12
_ADMINS_ONLY_NOTE = "Arguments are visible to admins only."
_PRIVATE_CHAT_NOTE = "Arguments are shown to admins in a private chat with the bot."
_MASKED_NOTE = "Values that look like secrets are masked."
type _Handler = Callable[[CallbackQuery, TeleBot], object]


def _make_call(data: str, user_id: int, chat_type: str = "private") -> CallbackQuery:
    chat_id = user_id if chat_type == "private" else -1001234567890
    payload: PayloadDict = {
        "id": "cbq-1",
        "from": {"id": user_id, "is_bot": False, "first_name": "User"},
        "chat_instance": "ci",
        "data": data,
        "message": {
            "message_id": 7,
            "date": 0,
            "chat": {"id": chat_id, "type": chat_type},
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


def _open(handler: object, data: str, viewer: int, chat_type: str) -> str:
    # Strip ``logger.catch`` and ``logger.session_decorator``.
    for _ in range(2):
        handler = getattr(handler, "__wrapped__", handler)
    bot = _Bot()
    cast(_Handler, handler)(_make_call(data, viewer, chat_type), cast(TeleBot, bot))
    return bot.html()


def _allow_any_callback(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    """Accept every callback, as a relaxed owner check would."""
    monkeypatch.setattr(
        module, "authorize_docker_callback_request", lambda **kwargs: (True, "")
    )


# --- container card -------------------------------------------------------------


def _install_container(
    monkeypatch: pytest.MonkeyPatch, entrypoint: list[str], cmd: list[str]
) -> None:
    container = SimpleNamespace(
        status="exited",
        attrs={
            "Id": _SHORT_ID + "0" * 52,
            "Name": "/db",
            "State": {"Status": "exited"},
            "Config": {"Image": "mysql:8", "Entrypoint": entrypoint, "Cmd": cmd},
        },
    )
    monkeypatch.setattr(
        handlers_docker, "get_container_full_details", lambda ref: container
    )


@pytest.fixture
def mysql_container(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_container(monkeypatch, ["docker-entrypoint.sh"], ["mysqld", "-ps3cret"])


def _open_container_card(
    callback_user: int, viewer: int, chat_type: str = "private"
) -> str:
    data = f"__get_full__:{_SHORT_ID}:{callback_user}:1"
    return _open(info_module.handle_containers_full_info, data, viewer, chat_type)


@pytest.mark.usefixtures("mysql_container")
def test_container_card_shows_only_executables_to_non_admins() -> None:
    html = _open_container_card(_USER, _USER)

    assert "<td>Entrypoint</td><td>docker-entrypoint.sh</td>" in html
    # With an Entrypoint, Cmd only holds its arguments.
    assert "<td>Command</td><td>hidden</td>" in html
    assert _ADMINS_ONLY_NOTE in html
    assert SECRET_MASK not in html
    assert "s3cret" not in html
    assert "Sensitive data is hidden" not in html


def test_container_card_without_entrypoint_shows_the_cmd_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_container(monkeypatch, [], ["mysqld", "-ps3cret"])

    html = _open_container_card(_USER, _USER)

    assert "<td>Command</td><td>mysqld</td>" in html
    assert "s3cret" not in html


def test_container_card_never_shows_cmd_arguments_as_the_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "ghp_AbCdEf0123456789"
    _install_container(monkeypatch, ["/app/server", "--license-file"], [token])

    html = _open_container_card(_USER, _USER)

    assert "<td>Entrypoint</td><td>/app/server</td>" in html
    assert "<td>Command</td><td>hidden</td>" in html
    assert token not in html


@pytest.mark.usefixtures("mysql_container")
def test_container_card_shows_masked_arguments_to_admins_in_private() -> None:
    html = _open_container_card(_ADMIN, _ADMIN)

    assert f"<td>Command</td><td>mysqld -p{SECRET_MASK}</td>" in html
    assert _MASKED_NOTE in html
    assert "s3cret" not in html


@pytest.mark.usefixtures("mysql_container")
@pytest.mark.parametrize("viewer", [_ADMIN, _USER])
def test_container_card_in_a_group_hides_arguments_from_everyone(viewer: int) -> None:
    html = _open_container_card(viewer, viewer, _GROUP)

    assert "<td>Command</td><td>hidden</td>" in html
    assert _PRIVATE_CHAT_NOTE in html
    assert SECRET_MASK not in html


@pytest.mark.usefixtures("mysql_container")
def test_container_card_trusts_the_viewer_not_the_callback_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_any_callback(monkeypatch, info_module)

    html = _open_container_card(_ADMIN, _USER)

    assert "<td>Command</td><td>hidden</td>" in html
    assert _ADMINS_ONLY_NOTE in html


# --- image card and history -----------------------------------------------------


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
    history = [
        images_info_module._format_history_layer(  # noqa: SLF001
            {"Id": "sha256:" + "1" * 64, "Created": 1_760_000_000, "Size": 10, **layer}
        )
        for layer in (
            {"CreatedBy": 'CMD ["app" "--api" "sk-abcdef"]', "Comment": ""},
            {"CreatedBy": "RUN /bin/sh -c ./install --edition pro # buildkit"},
            {"CreatedBy": "/bin/sh -c #(nop) COPY file:abc in /app "},
        )
    ]
    monkeypatch.setattr(images_module, "_images_cache", None)
    monkeypatch.setattr(images_module, "fetch_image_details", lambda: [details])
    monkeypatch.setattr(images_module, "get_image_history", lambda ref: history)


def _open_image_card(
    callback_user: int, viewer: int, chat_type: str = "private"
) -> str:
    data = f"__image_info__:{_IMAGE_REF}:{callback_user}:1"
    return _open(image_info_module.handle_image_info, data, viewer, chat_type)


def _open_image_history(viewer: int, chat_type: str = "private") -> str:
    data = f"__image_extra__:history:{_IMAGE_REF}:{viewer}:1"
    return _open(image_extra_module.handle_image_extra_info, data, viewer, chat_type)


@pytest.mark.usefixtures("mysql_image")
def test_image_card_shows_only_executables_to_non_admins() -> None:
    html = _open_image_card(_USER, _USER)

    assert "<td>Entrypoint</td><td>docker-entrypoint.sh</td>" in html
    assert "<td>Command</td><td>hidden</td>" in html
    assert "<td>Shell</td><td>/bin/sh</td>" in html
    assert "<td>Healthcheck</td><td>test=CMD-SHELL mysqladmin</td>" in html
    assert _ADMINS_ONLY_NOTE in html
    assert SECRET_MASK not in html
    assert "s3cret" not in html


@pytest.mark.usefixtures("mysql_image")
def test_image_card_shows_masked_arguments_to_admins_in_private() -> None:
    html = _open_image_card(_ADMIN, _ADMIN)

    assert f"<td>Command</td><td>mysqld -p{SECRET_MASK}</td>" in html
    assert f"test=CMD-SHELL mysqladmin ping -p{SECRET_MASK}" in html
    assert _MASKED_NOTE in html
    assert "s3cret" not in html


@pytest.mark.usefixtures("mysql_image")
def test_image_card_in_a_group_hides_arguments_from_admins() -> None:
    html = _open_image_card(_ADMIN, _ADMIN, _GROUP)

    assert "<td>Command</td><td>hidden</td>" in html
    assert _PRIVATE_CHAT_NOTE in html
    assert SECRET_MASK not in html


@pytest.mark.usefixtures("mysql_image")
def test_image_card_trusts_the_viewer_not_the_callback_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_any_callback(monkeypatch, image_callback_module)

    html = _open_image_card(_ADMIN, _USER)

    assert "<td>Command</td><td>hidden</td>" in html
    assert _ADMINS_ONLY_NOTE in html


@pytest.mark.usefixtures("mysql_image")
@pytest.mark.parametrize(
    ("viewer", "chat_type", "note"),
    [(_USER, "private", _ADMINS_ONLY_NOTE), (_ADMIN, _GROUP, _PRIVATE_CHAT_NOTE)],
)
def test_image_history_shows_only_instructions_without_arguments(
    viewer: int, chat_type: str, note: str
) -> None:
    html = _open_image_history(viewer, chat_type)

    for instruction in ("CMD", "RUN", "COPY"):
        assert f"<td>By</td><td>{instruction}</td>" in html
    assert "sk-abcdef" not in html
    assert "--edition" not in html
    assert note in html


@pytest.mark.usefixtures("mysql_image")
def test_image_history_shows_steps_to_admins_in_private() -> None:
    html = _open_image_history(_ADMIN)

    assert "sk-abcdef" in html
    assert "./install --edition pro" in html
    assert _MASKED_NOTE in html
