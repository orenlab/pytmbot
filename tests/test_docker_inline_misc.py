from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.docker_handlers.inline.back as back_module
import pytmbot.handlers.docker_handlers.inline.image_updates as image_updates_module
import pytmbot.handlers.docker_handlers.inline.images_page as images_page_module
import pytmbot.handlers.docker_handlers.inline.manage_action as manage_action_module
from pytmbot.adapters.docker.updates import UpdaterStatus


@dataclass
class _User:
    id: int = 11


@dataclass
class _Chat:
    id: int = 22


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    message_id: int = 33


@dataclass
class _Call:
    id: str = "cb"
    data: str | None = None
    from_user: _User | None = field(default_factory=_User)
    message: _Message | None = field(default_factory=_Message)


@dataclass
class _Bot:
    callback_answers: list[dict[str, object]] = field(default_factory=list)
    edited_messages: list[dict[str, object]] = field(default_factory=list)

    def answer_callback_query(self, callback_query_id: str, **kwargs: object) -> bool:
        payload: dict[str, object] = {
            "callback_query_id": callback_query_id,
            **kwargs,
        }
        self.callback_answers.append(payload)
        return True

    def edit_message_text(self, **kwargs: object) -> str:
        self.edited_messages.append(kwargs)
        return "edited"


def _raw_handler(handler: object) -> Callable[..., object]:
    wrapped = handler
    for _ in range(3):
        wrapped = getattr(wrapped, "__wrapped__", wrapped)
    return cast(Callable[..., object], wrapped)


def test_back_callback_parsing() -> None:
    assert back_module._parse_back_callback_data("back_to_containers") == (1, None)
    assert back_module._parse_back_callback_data("__containers_page__:2:44") == (2, 44)

    with pytest.raises(ValueError):
        back_module._parse_back_callback_data("invalid")


def test_handle_back_to_containers_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(back_module.handle_back_to_containers)
    bot = _Bot()
    shown: list[str] = []

    monkeypatch.setattr(back_module, "show_handler_info", lambda call, text, bot: shown.append(text))

    handler(cast(CallbackQuery, _Call(from_user=None)), cast(TeleBot, bot))
    assert shown[-1] == "Cannot identify callback user."

    handler(cast(CallbackQuery, _Call(message=None)), cast(TeleBot, bot))
    assert shown[-1] == "Cannot refresh containers list in this context."

    handler(cast(CallbackQuery, _Call(data=None)), cast(TeleBot, bot))
    assert shown[-1] == "Invalid containers pagination request."

    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid containers pagination request."

    monkeypatch.setattr(
        back_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id, **kwargs: (False, "denied"),
    )
    handler(cast(CallbackQuery, _Call(data="__containers_page__:1:11")), cast(TeleBot, bot))
    assert shown[-1] == "Containers: denied"

    monkeypatch.setattr(
        back_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id, **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        back_module,
        "get_list_of_containers_again",
        lambda page, user_id: ("containers", "kbd"),
    )
    handler(cast(CallbackQuery, _Call(data="__containers_page__:3:11")), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == "containers"


def test_handle_images_page_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(images_page_module.handle_images_page)
    bot = _Bot()
    shown: list[str] = []

    monkeypatch.setattr(images_page_module, "show_handler_info", lambda call, text, bot: shown.append(text))

    handler(cast(CallbackQuery, _Call(from_user=None)), cast(TeleBot, bot))
    assert shown[-1] == "Cannot identify callback user."

    handler(cast(CallbackQuery, _Call(message=None)), cast(TeleBot, bot))
    assert shown[-1] == "Cannot update images list in this context."

    handler(cast(CallbackQuery, _Call(data=None)), cast(TeleBot, bot))
    assert shown[-1] == "Invalid images pagination request."

    monkeypatch.setattr(images_page_module, "parse_page_callback_data", lambda data, prefix: None)
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid images pagination request."

    monkeypatch.setattr(images_page_module, "parse_page_callback_data", lambda data, prefix: (2, 11))
    monkeypatch.setattr(
        images_page_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id, **kwargs: (False, "forbidden"),
    )
    handler(cast(CallbackQuery, _Call(data="__images_page__:2:11")), cast(TeleBot, bot))
    assert shown[-1] == "Images: forbidden"

    monkeypatch.setattr(
        images_page_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id, **kwargs: (True, ""),
    )
    monkeypatch.setattr(images_page_module, "render_images_page", lambda page, user_id: ("images-page", "kbd"))
    handler(cast(CallbackQuery, _Call(data="__images_page__:2:11")), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == "images-page"


def test_prepare_context_for_render() -> None:
    payload: dict[str, dict[str, list[dict[str, str]]]] = {
        "repo-a": {
            "updates": [
                {
                    "current_tag": "1.0.0",
                    "created_at_local": "2026-02-17",
                    "newer_tag": "1.0.1",
                    "created_at_remote": "2026-02-18",
                }
            ]
        },
        "repo-b": {"updates": []},
    }

    context = image_updates_module.prepare_context_for_render(payload)
    updates = cast(dict[str, dict[str, object]], context["updates"])
    no_updates = cast(list[str], context["no_updates"])

    assert "repo-a" in updates
    assert no_updates == ["repo-b"]


def test_handle_image_updates_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(image_updates_module.handle_image_updates)
    bot = _Bot()

    monkeypatch.setattr(
        image_updates_module,
        "parse_callback_target_user",
        lambda data, prefix: (_ for _ in ()).throw(ValueError("bad")),
    )
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert "Invalid image updates request format" in str(bot.callback_answers[-1]["text"])

    monkeypatch.setattr(image_updates_module, "parse_callback_target_user", lambda data, prefix: 11)
    monkeypatch.setattr(
        image_updates_module,
        "authorize_callback_request",
        lambda call, target_user_id, require_owner_match: (False, "deny"),
    )
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert bot.callback_answers[-1]["text"] == "deny"

    monkeypatch.setattr(
        image_updates_module,
        "authorize_callback_request",
        lambda call, target_user_id, require_owner_match: (True, ""),
    )
    handler(
        cast(CallbackQuery, _Call(data="__check_updates__:11", message=None)),
        cast(TeleBot, bot),
    )
    assert "Cannot render image updates" in str(bot.callback_answers[-1]["text"])

    class _UpdaterRateLimited:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> dict[str, object]:
            return {
                "status": UpdaterStatus.RATE_LIMITED.name,
                "message": "rate",
                "data": {"retry_after": 10},
            }

    monkeypatch.setattr(image_updates_module, "DockerImageUpdater", _UpdaterRateLimited)
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert "Rate limit exceeded" in str(bot.callback_answers[-1]["text"])

    class _UpdaterError:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> dict[str, object]:
            return {
                "status": UpdaterStatus.ERROR.name,
                "message": "oops",
                "data": {},
            }

    monkeypatch.setattr(image_updates_module, "DockerImageUpdater", _UpdaterError)
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert "Error checking updates" in str(bot.callback_answers[-1]["text"])

    class _UpdaterNoUpdates:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> dict[str, object]:
            return {
                "status": UpdaterStatus.SUCCESS.name,
                "message": "ok",
                "data": {"repo-a": {"updates": []}},
            }

    monkeypatch.setattr(image_updates_module, "DockerImageUpdater", _UpdaterNoUpdates)
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert "No updates found" in str(bot.callback_answers[-1]["text"])

    class _UpdaterSuccess:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> dict[str, object]:
            return {
                "status": UpdaterStatus.SUCCESS.name,
                "message": "ok",
                "data": {
                    "repo-a": {
                        "updates": [
                            {
                                "current_tag": "1.0.0",
                                "created_at_local": "2026-02-17",
                                "newer_tag": "1.0.1",
                                "created_at_remote": "2026-02-18",
                            }
                        ]
                    }
                },
            }

    monkeypatch.setattr(image_updates_module, "DockerImageUpdater", _UpdaterSuccess)
    monkeypatch.setattr(image_updates_module.Compiler, "quick_render", lambda **kwargs: "updates-rendered")
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == "updates-rendered"


def test_manage_action_fabric_and_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert manage_action_module.managing_action_fabric(cast(CallbackQuery, _Call(data="__start__:c:1"))) is True
    assert manage_action_module.managing_action_fabric(cast(CallbackQuery, _Call(data="other"))) is False

    handler = _raw_handler(manage_action_module.handle_manage_container_action)
    bot = _Bot()

    monkeypatch.setattr(
        manage_action_module,
        "get_authorized_container_callback_context",
        lambda **kwargs: None,
    )
    handler(cast(CallbackQuery, _Call(data="__start__:c:1")), cast(TeleBot, bot))

    calls: list[str] = []

    @dataclass
    class _Context:
        callback_data: str
        container_name: str
        user_id: int

    monkeypatch.setattr(
        manage_action_module,
        "get_authorized_container_callback_context",
        lambda **kwargs: _Context("__start__:api:11", "api", 11),
    )
    monkeypatch.setattr(manage_action_module, "split_string_into_octets", lambda callback_data, octet_index=1: "__start__")
    monkeypatch.setattr(
        manage_action_module,
        "__start_container",
        lambda call, container_name, bot: calls.append(f"start:{container_name}"),
    )

    handler(cast(CallbackQuery, _Call(data="__start__:api:11")), cast(TeleBot, bot))
    assert calls == ["start:api"]


def test_manage_action_private_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _Bot()
    shown: list[str] = []

    monkeypatch.setattr(manage_action_module, "show_handler_info", lambda call, text, bot: shown.append(text))

    # start
    manage_action_module.__start_container(cast(CallbackQuery, _Call(from_user=None)), "api", cast(TeleBot, bot))
    assert shown[-1] == "Starting api: Missing user information"

    monkeypatch.setattr(manage_action_module.container_manager, "managing_container", lambda user_id, container_name, action: None)
    manage_action_module.__start_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Starting api: Success"

    monkeypatch.setattr(manage_action_module.container_manager, "managing_container", lambda user_id, container_name, action: "err")
    manage_action_module.__start_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Starting api: Error occurred. See logs"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    manage_action_module.__start_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Starting api: Unexpected error occurred"

    # stop
    manage_action_module.__stop_container(cast(CallbackQuery, _Call(from_user=None)), "api", cast(TeleBot, bot))
    assert shown[-1] == "Stopping api: Missing user information"

    monkeypatch.setattr(manage_action_module.container_manager, "managing_container", lambda user_id, container_name, action: None)
    manage_action_module.__stop_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Stopping api: Success"

    monkeypatch.setattr(manage_action_module.container_manager, "managing_container", lambda user_id, container_name, action: "err")
    manage_action_module.__stop_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Stopping api: Error occurred. See logs"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    manage_action_module.__stop_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Stopping api: Unexpected error occurred"

    # restart
    manage_action_module.__restart_container(cast(CallbackQuery, _Call(from_user=None)), "api", cast(TeleBot, bot))
    assert shown[-1] == "Restarting api: Missing user information"

    manage_action_module.__restart_container(cast(CallbackQuery, _Call(message=None)), "api", cast(TeleBot, bot))
    assert shown[-1] == "Restarting api: Missing callback message"

    monkeypatch.setattr(manage_action_module.container_manager, "managing_container", lambda user_id, container_name, action: None)
    monkeypatch.setattr(manage_action_module, "button_data", lambda text, callback_data: {"text": text, "callback_data": callback_data})
    monkeypatch.setattr(
        manage_action_module,
        "keyboards",
        cast(object, type("_Kbd", (), {"build_inline_keyboard": staticmethod(lambda buttons: buttons)})()),
    )
    manage_action_module.__restart_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert "Restarting api: Success" in str(bot.edited_messages[-1]["text"])

    monkeypatch.setattr(manage_action_module.container_manager, "managing_container", lambda user_id, container_name, action: "err")
    manage_action_module.__restart_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Restarting api: Error occurred. See logs"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    manage_action_module.__restart_container(cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot))
    assert shown[-1] == "Restarting api: Unexpected error occurred"
