from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.docker_handlers.inline.back as back_module
import pytmbot.handlers.docker_handlers.inline.image_callback as image_callback_module
import pytmbot.handlers.docker_handlers.inline.image_extra as image_extra_module
import pytmbot.handlers.docker_handlers.inline.image_info as image_info_module
import pytmbot.handlers.docker_handlers.inline.image_updates as image_updates_module
import pytmbot.handlers.docker_handlers.inline.images_page as images_page_module
import pytmbot.handlers.docker_handlers.inline.manage_action as manage_action_module
from pytmbot.adapters.docker.updates import UpdaterStatus
from pytmbot.parsers.compiler import Compiler
from tests._callback_path_helpers import assert_standard_callback_auth_paths
from tests._inline_edit_helpers import (
    assert_reply_markup_has_callbacks,
    patch_authorized_inline_render,
    patch_not_modified_edit_error,
    patch_rate_limited_edit_error,
)
from tests._telebot_objects import (
    record_callback_answer,
    record_edited_message,
    unwrap_handler,
)

type _JsonLike = (
    str | int | float | bool | None | dict[str, _JsonLike] | list[_JsonLike]
)
type _JsonDict = dict[str, _JsonLike]
type _CallbackHandler = Callable[[CallbackQuery, TeleBot], None]
type _DecoratedHandler = (
    Callable[..., None] | Callable[[Callable[..., None]], Callable[..., None]]
)
type _RawHandlerInput = Callable[..., _CallbackHandler | None] | _DecoratedHandler
type _ParsedImageCallback = tuple[int, int, int] | tuple[str, int, int, int]
type _RenderResult = tuple[str, str]


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
    callback_answers: list[_JsonDict] = field(default_factory=list)
    edited_messages: list[_JsonDict] = field(default_factory=list)

    def answer_callback_query(
        self, callback_query_id: str, **kwargs: _JsonLike
    ) -> bool:
        record_callback_answer(self.callback_answers, callback_query_id, **kwargs)
        return True

    def edit_message_text(self, **kwargs: _JsonLike) -> str:
        record_edited_message(self.edited_messages, **kwargs)
        return "edited"


def _raw_handler(handler: _RawHandlerInput) -> _CallbackHandler:
    return cast(_CallbackHandler, unwrap_handler(handler, depth=3))


def _assert_common_callback_context_errors(
    *,
    handler: _CallbackHandler,
    bot: _Bot,
    shown: list[str],
    missing_message_error: str,
) -> None:
    handler(cast(CallbackQuery, _Call(from_user=None)), cast(TeleBot, bot))
    assert shown[-1] == "Couldn't verify who pressed this button."

    handler(cast(CallbackQuery, _Call(message=None)), cast(TeleBot, bot))
    assert shown[-1] == missing_message_error


def _collect_shown_messages(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: ModuleType,
) -> list[str]:
    shown: list[str] = []
    target = module if hasattr(module, "show_handler_info") else image_callback_module
    monkeypatch.setattr(
        target,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    return shown


def _patch_authorization(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: ModuleType,
    auth_kwargs: list[_JsonDict],
    is_allowed: bool,
    reason: str,
) -> None:
    def _authorize(
        call: CallbackQuery,
        called_user_id: int,
        **kwargs: _JsonLike,
    ) -> tuple[bool, str]:
        del call, called_user_id
        auth_kwargs.append(kwargs)
        return is_allowed, reason

    target = (
        module
        if hasattr(module, "authorize_docker_callback_request")
        else image_callback_module
    )
    monkeypatch.setattr(target, "authorize_docker_callback_request", _authorize)


def _assert_image_details_callback_paths(
    *,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    handler: _CallbackHandler,
    bot: _Bot,
    parse_attr: str,
    parse_valid: Callable[[str], _ParsedImageCallback],
    valid_callback_data: str,
    render_attr: str,
    render_none: Callable[..., _RenderResult | None],
    render_success: Callable[..., _RenderResult],
    success_text: str,
) -> None:
    shown = _collect_shown_messages(monkeypatch, module=module)
    auth_kwargs: list[_JsonDict] = []

    _assert_common_callback_context_errors(
        handler=handler,
        bot=bot,
        shown=shown,
        missing_message_error="This image details message can no longer be updated.",
    )

    handler(cast(CallbackQuery, _Call(data=None)), cast(TeleBot, bot))
    assert shown[-1] == "This image details button is no longer valid."

    monkeypatch.setattr(module, parse_attr, lambda data: None)
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "This image details button is no longer valid."

    monkeypatch.setattr(module, parse_attr, parse_valid)

    _patch_authorization(
        monkeypatch,
        module=module,
        auth_kwargs=auth_kwargs,
        is_allowed=False,
        reason="denied",
    )
    handler(cast(CallbackQuery, _Call(data=valid_callback_data)), cast(TeleBot, bot))
    assert shown[-1] == "Images: denied"
    assert auth_kwargs[-1]["require_session"] is False

    _patch_authorization(
        monkeypatch,
        module=module,
        auth_kwargs=auth_kwargs,
        is_allowed=True,
        reason="",
    )
    monkeypatch.setattr(module, render_attr, render_none)
    handler(cast(CallbackQuery, _Call(data=valid_callback_data)), cast(TeleBot, bot))
    assert shown[-1] == (
        "Image details are no longer available. Refresh the images list first."
    )

    monkeypatch.setattr(module, render_attr, render_success)
    handler(cast(CallbackQuery, _Call(data=valid_callback_data)), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == success_text


def test_back_callback_parsing() -> None:
    assert back_module._parse_back_callback_data("back_to_containers") == (1, None)
    assert back_module._parse_back_callback_data("__containers_page__:2:44") == (2, 44)

    with pytest.raises(ValueError):
        back_module._parse_back_callback_data("invalid")


def test_handle_back_to_containers_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(back_module.handle_back_to_containers)
    bot = _Bot()
    shown: list[str] = []

    monkeypatch.setattr(
        back_module, "show_handler_info", lambda call, text, bot: shown.append(text)
    )

    _assert_common_callback_context_errors(
        handler=handler,
        bot=bot,
        shown=shown,
        missing_message_error="This containers list message can no longer be updated.",
    )

    handler(cast(CallbackQuery, _Call(data=None)), cast(TeleBot, bot))
    assert shown[-1] == "This pagination button is no longer valid."

    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "This pagination button is no longer valid."

    monkeypatch.setattr(
        back_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id, **kwargs: (False, "denied"),
    )
    handler(
        cast(CallbackQuery, _Call(data="__containers_page__:1:11")), cast(TeleBot, bot)
    )
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
    handler(
        cast(CallbackQuery, _Call(data="__containers_page__:3:11")), cast(TeleBot, bot)
    )
    assert bot.edited_messages[-1]["text"] == "containers"


def test_handle_images_page_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(images_page_module.handle_images_page)
    bot = _Bot()
    shown = _collect_shown_messages(monkeypatch, module=images_page_module)
    auth_kwargs: list[_JsonDict] = []

    _assert_common_callback_context_errors(
        handler=handler,
        bot=bot,
        shown=shown,
        missing_message_error="This images list message can no longer be updated.",
    )

    handler(cast(CallbackQuery, _Call(data=None)), cast(TeleBot, bot))
    assert shown[-1] == "This pagination button is no longer valid."

    monkeypatch.setattr(
        images_page_module, "parse_page_callback_data", lambda data, prefix: None
    )
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "This pagination button is no longer valid."

    monkeypatch.setattr(
        images_page_module, "parse_page_callback_data", lambda data, prefix: (2, 11)
    )

    _patch_authorization(
        monkeypatch,
        module=images_page_module,
        auth_kwargs=auth_kwargs,
        is_allowed=False,
        reason="forbidden",
    )
    handler(cast(CallbackQuery, _Call(data="__images_page__:2:11")), cast(TeleBot, bot))
    assert shown[-1] == "Images: forbidden"
    assert auth_kwargs[-1]["require_session"] is False

    _patch_authorization(
        monkeypatch,
        module=images_page_module,
        auth_kwargs=auth_kwargs,
        is_allowed=True,
        reason="",
    )
    monkeypatch.setattr(
        images_page_module,
        "render_images_page",
        lambda page, user_id: ("images-page", "kbd"),
    )
    handler(cast(CallbackQuery, _Call(data="__images_page__:2:11")), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == "images-page"
    assert auth_kwargs[-1]["require_session"] is False


def test_handle_image_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(image_info_module.handle_image_info)
    bot = _Bot()
    _assert_image_details_callback_paths(
        monkeypatch=monkeypatch,
        module=image_info_module,
        handler=handler,
        bot=bot,
        parse_attr="parse_image_info_callback_data",
        parse_valid=lambda _data: (3, 11, 2),
        valid_callback_data="__image_info__:3:11:2",
        render_attr="render_image_details",
        render_none=lambda image_index, page, user_id: None,
        render_success=lambda image_index, page, user_id: ("image-details", "kbd"),
        success_text="image-details",
    )


def test_handle_image_extra_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(image_extra_module.handle_image_extra_info)
    bot = _Bot()
    _assert_image_details_callback_paths(
        monkeypatch=monkeypatch,
        module=image_extra_module,
        handler=handler,
        bot=bot,
        parse_attr="parse_image_extra_callback_data",
        parse_valid=lambda _data: ("history", 3, 11, 2),
        valid_callback_data="__image_extra__:history:3:11:2",
        render_attr="render_image_extra_info",
        render_none=lambda action, image_index, page, user_id: None,
        render_success=lambda action, image_index, page, user_id: (
            "image-extra",
            "kbd",
        ),
        success_text="image-extra",
    )


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

    context = image_updates_module.prepare_context_for_render(
        cast(dict[str, image_updates_module.RawRepositoryUpdateInfo], payload)
    )
    updates = context["updates"]
    no_updates = context["no_updates"]

    assert "repo-a" in updates
    assert no_updates == ["repo-b"]


def test_handle_image_updates_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _raw_handler(image_updates_module.handle_image_updates)
    bot = _Bot()

    assert_standard_callback_auth_paths(
        monkeypatch=monkeypatch,
        module=image_updates_module,
        handler=handler,
        bot=bot,
        call_builder=lambda **kwargs: cast(CallbackQuery, _Call(**kwargs)),
        invalid_data="bad",
        valid_data="__check_updates__:11",
        target_user_id=11,
        invalid_text_contains="This image updates button is no longer valid",
        denied_text="deny",
        missing_message_text_contains="This image updates message can no longer be refreshed",
    )

    class _UpdaterRateLimited:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> _JsonDict:
            return {
                "status": UpdaterStatus.RATE_LIMITED.name,
                "message": "rate",
                "data": {"retry_after": 10},
            }

    monkeypatch.setattr(image_updates_module, "DockerImageUpdater", _UpdaterRateLimited)
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert "Registry rate limit exceeded" in str(bot.callback_answers[-1]["text"])

    class _UpdaterError:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> _JsonDict:
            return {
                "status": UpdaterStatus.ERROR.name,
                "message": "oops",
                "data": {},
            }

    monkeypatch.setattr(image_updates_module, "DockerImageUpdater", _UpdaterError)
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert "Couldn't check image updates" in str(bot.callback_answers[-1]["text"])

    class _UpdaterNoUpdates:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> _JsonDict:
            return {
                "status": UpdaterStatus.SUCCESS.name,
                "message": "ok",
                "data": {"repo-a": {"updates": []}},
            }

    monkeypatch.setattr(image_updates_module, "DockerImageUpdater", _UpdaterNoUpdates)
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert "No image updates were found" in str(bot.callback_answers[-1]["text"])

    class _UpdaterSuccess:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> _JsonDict:
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
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: "updates-rendered",
    )
    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == "updates-rendered"
    assert_reply_markup_has_callbacks(
        bot.edited_messages[-1].get("reply_markup"),
        expected_callbacks=["__check_updates__:11", "__images_page__:1:11"],
    )


def test_manage_action_fabric_and_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        manage_action_module.managing_action_fabric(
            cast(CallbackQuery, _Call(data="__start__:c:1"))
        )
        is True
    )
    assert (
        manage_action_module.managing_action_fabric(
            cast(CallbackQuery, _Call(data="other"))
        )
        is False
    )

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
    monkeypatch.setattr(
        manage_action_module,
        "split_string_into_octets",
        lambda callback_data, octet_index=1: "__start__",
    )
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

    monkeypatch.setattr(
        manage_action_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )

    # start
    manage_action_module.__start_container(
        cast(CallbackQuery, _Call(from_user=None)), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Starting api: Missing user information"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: None,
    )
    manage_action_module.__start_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Starting api: Success"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: "err",
    )
    manage_action_module.__start_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Starting api: Error occurred. See logs"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    manage_action_module.__start_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Starting api: Unexpected error occurred"

    # stop
    manage_action_module.__stop_container(
        cast(CallbackQuery, _Call(from_user=None)), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Stopping api: Missing user information"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: None,
    )
    manage_action_module.__stop_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Stopping api: Success"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: "err",
    )
    manage_action_module.__stop_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Stopping api: Error occurred. See logs"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    manage_action_module.__stop_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Stopping api: Unexpected error occurred"

    # restart
    manage_action_module.__restart_container(
        cast(CallbackQuery, _Call(from_user=None)), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Restarting api: Missing user information"

    manage_action_module.__restart_container(
        cast(CallbackQuery, _Call(message=None)), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Restarting api: Missing callback message"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: None,
    )
    monkeypatch.setattr(
        manage_action_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        manage_action_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )
    manage_action_module.__restart_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert "Restarting api: Success" in str(bot.edited_messages[-1]["text"])

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: "err",
    )
    manage_action_module.__restart_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Restarting api: Error occurred. See logs"

    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    manage_action_module.__restart_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert shown[-1] == "Restarting api: Unexpected error occurred"


def test_handle_back_to_containers_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _raw_handler(back_module.handle_back_to_containers)
    bot = _Bot()
    monkeypatch.setattr(
        back_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        back_module,
        "get_list_of_containers_again",
        lambda page, user_id: ("containers", "kbd"),
    )

    patch_not_modified_edit_error(monkeypatch, bot)

    handler(
        cast(CallbackQuery, _Call(data="__containers_page__:1:11")), cast(TeleBot, bot)
    )
    assert bot.callback_answers[-1]["text"] == "Containers list is already current."


def test_handle_images_page_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _raw_handler(images_page_module.handle_images_page)
    bot = _Bot()
    monkeypatch.setattr(
        images_page_module,
        "parse_page_callback_data",
        lambda data, prefix: (2, 11),
    )
    monkeypatch.setattr(
        images_page_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        images_page_module,
        "render_images_page",
        lambda page, user_id: ("images-page", "kbd"),
    )

    patch_not_modified_edit_error(monkeypatch, bot)

    handler(cast(CallbackQuery, _Call(data="__images_page__:2:11")), cast(TeleBot, bot))
    assert bot.callback_answers[-1]["text"] == "Images list is already current."


@pytest.mark.parametrize(
    ("module", "handler_obj", "callback_data", "parse_callback_name", "render_name"),
    [
        (
            image_info_module,
            image_info_module.handle_image_info,
            "__get_image_info__:0:11:1",
            "parse_image_info_callback_data",
            "render_image_details",
        ),
        (
            image_extra_module,
            image_extra_module.handle_image_extra_info,
            "__image_extra__:history:0:11:1",
            "parse_image_extra_callback_data",
            "render_image_extra_info",
        ),
    ],
)
def test_handle_image_details_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    handler_obj: _CallbackHandler,
    callback_data: str,
    parse_callback_name: str,
    render_name: str,
) -> None:
    handler = _raw_handler(handler_obj)
    bot = _Bot()

    monkeypatch.setattr(
        module,
        parse_callback_name,
        lambda data: (
            (0, 11, 1)
            if parse_callback_name == "parse_image_info_callback_data"
            else ("history", 0, 11, 1)
        ),
    )
    monkeypatch.setattr(
        image_callback_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(module, render_name, lambda **kwargs: ("image", "kbd"))

    patch_not_modified_edit_error(monkeypatch, bot)

    handler(cast(CallbackQuery, _Call(data=callback_data)), cast(TeleBot, bot))
    assert bot.callback_answers[-1]["text"] == "Image details are already current."


def test_handle_image_info_handles_telegram_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _raw_handler(image_info_module.handle_image_info)
    bot = _Bot()

    patch_authorized_inline_render(
        monkeypatch,
        parse_module=image_info_module,
        parse_name="parse_image_info_callback_data",
        parse_result=(0, 11, 1),
        authorize_module=image_callback_module,
        render_module=image_info_module,
        render_name="render_image_details",
        render_result=("image", "kbd"),
    )

    patch_rate_limited_edit_error(monkeypatch, bot, retry_after=11)

    handler(
        cast(CallbackQuery, _Call(data="__get_image_info__:0:11:1")), cast(TeleBot, bot)
    )
    assert (
        bot.callback_answers[-1]["text"]
        == "Telegram API is rate limited. Try again in 11s."
    )


def test_handle_image_updates_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _raw_handler(image_updates_module.handle_image_updates)
    bot = _Bot()

    monkeypatch.setattr(
        image_updates_module,
        "parse_callback_target_user",
        lambda data, prefix: 11,
    )
    monkeypatch.setattr(
        image_updates_module,
        "authorize_callback_request",
        lambda call, target_user_id, require_owner_match: (True, ""),
    )

    class _UpdaterSuccess:
        def initialize(self) -> None:
            return None

        def to_dict(self) -> _JsonDict:
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
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: "updates-rendered",
    )

    patch_not_modified_edit_error(monkeypatch, bot)

    handler(cast(CallbackQuery, _Call(data="__check_updates__:11")), cast(TeleBot, bot))
    assert bot.callback_answers[-1]["text"] == "Image updates are already current."


def test_restart_container_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    monkeypatch.setattr(
        manage_action_module.container_manager,
        "managing_container",
        lambda user_id, container_name, action: None,
    )
    monkeypatch.setattr(
        manage_action_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        manage_action_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )

    patch_not_modified_edit_error(monkeypatch, bot)

    manage_action_module.__restart_container(
        cast(CallbackQuery, _Call()), "api", cast(TeleBot, bot)
    )
    assert (
        bot.callback_answers[-1]["text"] == "Restart result for api is already shown."
    )
