from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType, TracebackType
from typing import Literal, cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.docker_handlers.inline.container_info as container_info_module
import pytmbot.handlers.docker_handlers.inline.container_runtime_info as runtime_info_module
import pytmbot.handlers.docker_handlers.inline.manage as manage_module
from pytmbot.handlers.handlers_util.docker import validate_container_name
from pytmbot.parsers.compiler import Compiler
from tests._inline_edit_helpers import patch_not_modified_edit_error

type _CallbackHandler = Callable[[CallbackQuery, TeleBot], None]
type _RawHandlerInput = (
    Callable[..., _CallbackHandler | None]
    | Callable[..., None]
    | Callable[[Callable[..., None]], Callable[..., None]]
)
type _Value = str | int | float | bool | None | dict[str, _Value] | list[_Value]
type _ValueDict = dict[str, _Value]


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
    data: str | None = "payload"
    from_user: _User | None = field(default_factory=_User)
    message: _Message | None = field(default_factory=_Message)


@dataclass
class _Bot:
    callback_answers: list[_ValueDict] = field(default_factory=list)
    edited_messages: list[_ValueDict] = field(default_factory=list)

    def answer_callback_query(self, callback_query_id: str, **kwargs: _Value) -> bool:
        payload: _ValueDict = {
            "callback_query_id": callback_query_id,
            **kwargs,
        }
        self.callback_answers.append(payload)
        return True

    def edit_message_text(self, **kwargs: _Value) -> str:
        self.edited_messages.append(cast(_ValueDict, dict(kwargs)))
        return "edited"


def _raw_handler(handler: _RawHandlerInput) -> _CallbackHandler:
    wrapped = handler
    for _ in range(3):
        wrapped = getattr(wrapped, "__wrapped__", wrapped)
    return cast(_CallbackHandler, wrapped)


def _prepare_handler_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: ModuleType,
    handler_obj: _RawHandlerInput,
) -> tuple[_CallbackHandler, _Bot, list[str]]:
    handler = _raw_handler(handler_obj)
    bot = _Bot()
    shown: list[str] = []
    monkeypatch.setattr(
        module,
        "show_handler_info",
        lambda call, text, bot=None: shown.append(text),
    )
    return handler, bot, shown


@dataclass
class _ManageAuthContext:
    container_name: str = "api"
    user_id: int = 11


class _DockerContext:
    def __enter__(self) -> str:
        return "adapter"

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc, tb
        return False


def _patch_manage_view_render_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manage_module, "docker_client_context", lambda: _DockerContext()
    )
    monkeypatch.setattr(
        manage_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        manage_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )
    monkeypatch.setattr(
        manage_module,
        "em",
        type("_Em", (), {"get_emoji": staticmethod(lambda key: key)})(),
    )
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda *args, **kwargs: "manage-ui",
    )


def _patch_manage_authorization_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        manage_module,
        "get_authorized_container_callback_context",
        lambda **kwargs: _ManageAuthContext(),
    )


def _patch_manage_container_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: str,
) -> None:
    monkeypatch.setattr(
        manage_module,
        "get_container_state",
        lambda container_name, docker_client: state,
    )


def _assert_invalid_container_name_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: ModuleType,
    handler: _CallbackHandler,
    bot: _Bot,
    shown: list[str],
    callback_data: str,
    invalid_text: str,
) -> None:
    monkeypatch.setattr(module, "validate_container_name", lambda name: False)
    handler(cast(CallbackQuery, _Call(data=callback_data)), cast(TeleBot, bot))
    assert shown[-1] == invalid_text
    monkeypatch.setattr(module, "validate_container_name", lambda name: True)


def test_validate_container_name() -> None:
    assert validate_container_name("api-1") is True
    assert validate_container_name("") is False
    assert validate_container_name("../etc") is False
    assert validate_container_name("bad|name") is False


def test_handle_container_full_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, bot, shown = _prepare_handler_context(
        monkeypatch,
        module=container_info_module,
        handler_obj=container_info_module.handle_containers_full_info,
    )

    handler(cast(CallbackQuery, _Call(data=None)), cast(TeleBot, bot))
    assert shown[-1] == "Invalid request format"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: None,
    )
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid request format"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: ("api", 11, 2),
    )
    monkeypatch.setattr(
        container_info_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (False, "denied"),
    )
    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    assert shown[-1] == "Container info: denied"

    monkeypatch.setattr(
        container_info_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (True, ""),
    )
    _assert_invalid_container_name_path(
        monkeypatch,
        module=container_info_module,
        handler=handler,
        bot=bot,
        shown=shown,
        callback_data="ok",
        invalid_text="Invalid container name format",
    )
    monkeypatch.setattr(
        container_info_module, "get_comprehensive_container_details", lambda name: {}
    )
    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    assert shown[-1] == "api: Container not found"

    class _Access:
        allowed_admins_ids = [11]

    class _Settings:
        access_control = _Access()

    monkeypatch.setattr(container_info_module, "settings", _Settings())
    monkeypatch.setattr(
        container_info_module,
        "get_comprehensive_container_details",
        lambda name: {"name": "api", "state": "running"},
    )
    monkeypatch.setattr(
        container_info_module,
        "get_emojis",
        lambda: {
            "spiral_calendar": "📅",
            "bullseye": "🎯",
            "BACK_arrow": "⬅️",
            "thought_balloon": "💭",
            "package": "📦",
            "gear": "⚙️",
            "chart_increasing": "📈",
            "globe_with_meridians": "🌐",
            "herb": "🌿",
            "banjo": "🪕",
        },
    )
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: "container-full",
    )
    monkeypatch.setattr(
        container_info_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        container_info_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )

    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    callbacks = cast(list[dict[str, str]], bot.edited_messages[-1]["reply_markup"])
    callback_data = [item["callback_data"] for item in callbacks]
    assert bot.edited_messages[-1]["text"] == "container-full"
    assert any(
        value.startswith("__container_extra__:volumes:") for value in callback_data
    )
    assert any(
        value.startswith("__container_extra__:networks:") for value in callback_data
    )
    assert any(
        value.startswith("__container_extra__:runtime:") for value in callback_data
    )
    assert any(value.startswith("__get_logs__") for value in callback_data)
    assert any(value.startswith("__manage__") for value in callback_data)
    assert any(value.startswith("__containers_page__") for value in callback_data)

    handler(cast(CallbackQuery, _Call(data="ok", message=None)), cast(TeleBot, bot))
    assert shown[-1] == "Cannot render container details in this context"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: (_ for _ in ()).throw(ValueError("bad")),
    )
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid request data"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: ("api", 11, 1),
    )
    monkeypatch.setattr(
        container_info_module, "validate_container_name", lambda name: True
    )
    monkeypatch.setattr(
        container_info_module,
        "get_comprehensive_container_details",
        lambda name: {"name": "api"},
    )
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("render fail")),
    )
    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    assert shown[-1] == "An error occurred while processing request"


def test_parse_container_extra_callback_data() -> None:
    parsed = runtime_info_module.parse_container_extra_callback_data(
        "__container_extra__:volumes:api:11"
    )
    assert parsed.action == "volumes"
    assert parsed.container_name == "api"
    assert parsed.user_id == 11

    with pytest.raises(ValueError):
        runtime_info_module.parse_container_extra_callback_data(None)
    with pytest.raises(ValueError):
        runtime_info_module.parse_container_extra_callback_data(
            "__container_extra__:unknown:api:11"
        )
    with pytest.raises(ValueError):
        runtime_info_module.parse_container_extra_callback_data(
            "__container_extra__:volumes:api:not-int"
        )

    parsed_runtime = runtime_info_module.parse_container_extra_callback_data(
        "__container_extra__:runtime:api:11"
    )
    assert parsed_runtime.action == "runtime"


def test_handle_container_extra_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, bot, shown = _prepare_handler_context(
        monkeypatch,
        module=runtime_info_module,
        handler_obj=runtime_info_module.handle_container_extra_info,
    )

    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid container details request"

    monkeypatch.setattr(
        runtime_info_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id: (False, "denied"),
    )
    handler(
        cast(CallbackQuery, _Call(data="__container_extra__:volumes:api:11")),
        cast(TeleBot, bot),
    )
    assert shown[-1] == "Container details: denied"

    monkeypatch.setattr(
        runtime_info_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id: (True, ""),
    )
    _assert_invalid_container_name_path(
        monkeypatch,
        module=runtime_info_module,
        handler=handler,
        bot=bot,
        shown=shown,
        callback_data="__container_extra__:volumes:api:11",
        invalid_text="Invalid container name format",
    )
    monkeypatch.setattr(
        runtime_info_module, "get_container_full_details", lambda name: None
    )
    handler(
        cast(CallbackQuery, _Call(data="__container_extra__:volumes:api:11")),
        cast(TeleBot, bot),
    )
    assert shown[-1] == "api: Container not found"

    @dataclass
    class _Container:
        attrs: dict[str, _Value]

    container_attrs: dict[str, _Value] = {
        "Mounts": [
            {
                "Source": "/src",
                "Destination": "/dst",
                "Mode": "rw",
                "Type": "bind",
                "RW": True,
            }
        ],
        "HostConfig": {"NetworkMode": "bridge"},
        "NetworkSettings": {
            "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
            "Networks": {
                "bridge": {
                    "IPAddress": "172.17.0.2",
                    "Gateway": "172.17.0.1",
                    "MacAddress": "aa:bb:cc:dd:ee:ff",
                    "Aliases": ["api"],
                }
            },
        },
    }

    monkeypatch.setattr(
        runtime_info_module,
        "get_container_full_details",
        lambda name: _Container(attrs=container_attrs),
    )
    monkeypatch.setattr(
        runtime_info_module,
        "get_emojis",
        lambda: {
            "thought_balloon": "💭",
            "package": "📦",
            "banjo": "🪕",
            "luggage": "🧳",
            "globe_with_meridians": "🌐",
            "chart_increasing": "📈",
            "BACK_arrow": "⬅️",
        },
    )
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda template_name, **kwargs: template_name,
    )
    monkeypatch.setattr(
        runtime_info_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        runtime_info_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )

    handler(
        cast(
            CallbackQuery,
            _Call(data="__container_extra__:volumes:api:11", message=None),
        ),
        cast(TeleBot, bot),
    )
    assert shown[-1] == "Cannot render container details in this context"

    handler(
        cast(CallbackQuery, _Call(data="__container_extra__:volumes:api:11")),
        cast(TeleBot, bot),
    )
    assert bot.edited_messages[-1]["text"] == "d_container_volumes_info.jinja2"
    volumes_callbacks = cast(
        list[dict[str, str]],
        bot.edited_messages[-1]["reply_markup"],
    )
    assert volumes_callbacks[0]["callback_data"] == "__get_full__:api:11"

    handler(
        cast(CallbackQuery, _Call(data="__container_extra__:networks:api:11")),
        cast(TeleBot, bot),
    )
    assert bot.edited_messages[-1]["text"] == "d_container_networks_info.jinja2"

    handler(
        cast(CallbackQuery, _Call(data="__container_extra__:runtime:api:11")),
        cast(TeleBot, bot),
    )
    assert bot.edited_messages[-1]["text"] == "d_container_runtime_info.jinja2"


def test_runtime_template_line_breaks_are_stable() -> None:
    rendered = Compiler.quick_render(
        template_name="d_container_runtime_info.jinja2",
        thought_balloon="💭",
        package_emoji="📦",
        stethoscope_emoji="🩺",
        chart_emoji="📈",
        shield_emoji="🛡️",
        gear_emoji="⚙️",
        banjo="🪕",
        container_name="pytmbot",
        health_badge="🟢 healthy",
        health_failing_streak=0,
        health_last_checked_at="2026-02-19 12:48:58 UTC",
        health_last_log="ok",
        created_at="2026-02-19 12:48:53 UTC",
        started_at="2026-02-19 12:48:53 UTC",
        finished_at="N/A",
        pid="123",
        exit_code="0",
        stop_signal="SIGTERM",
        stop_timeout="default",
        oom_killed="no",
        dead="no",
        state_error="none",
        privileged="no",
        read_only_rootfs="no",
        oom_kill_disable="no",
        no_new_privileges="yes",
        init_process="no",
        security_opts=["no-new-privileges:true"],
        security_opts_count=1,
        hidden_security_opts_count=0,
        cap_add=[],
        cap_add_count=0,
        hidden_cap_add_count=0,
        cap_drop=[],
        cap_drop_count=0,
        hidden_cap_drop_count=0,
    )

    assert "🟢 healthy\n<code>Failing streak:</code>" in rendered
    assert "<code>PID:</code> 123\n<code>Exit code:</code> 0" in rendered
    assert "<code>Stop signal:</code> SIGTERM\n<code>Stop timeout:</code> default" in (
        rendered
    )


def test_handle_manage_container_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, bot, shown = _prepare_handler_context(
        monkeypatch,
        module=manage_module,
        handler_obj=manage_module.handle_manage_container,
    )

    monkeypatch.setattr(
        manage_module,
        "get_authorized_container_callback_context",
        lambda **kwargs: None,
    )
    handler(cast(CallbackQuery, _Call(data="__manage__:api:11")), cast(TeleBot, bot))

    _patch_manage_authorization_context(monkeypatch)
    _patch_manage_view_render_dependencies(monkeypatch)
    _patch_manage_container_state(monkeypatch, state="running")
    handler(cast(CallbackQuery, _Call(data="__manage__:api:11")), cast(TeleBot, bot))
    running_callbacks = cast(
        list[dict[str, str]], bot.edited_messages[-1]["reply_markup"]
    )
    running_values = [item["callback_data"] for item in running_callbacks]
    assert any(value.startswith("__stop__") for value in running_values)
    assert any(value.startswith("__restart__") for value in running_values)

    _patch_manage_container_state(monkeypatch, state="exited")
    handler(cast(CallbackQuery, _Call(data="__manage__:api:11")), cast(TeleBot, bot))
    stopped_callbacks = cast(
        list[dict[str, str]], bot.edited_messages[-1]["reply_markup"]
    )
    stopped_values = [item["callback_data"] for item in stopped_callbacks]
    assert any(value.startswith("__start__") for value in stopped_values)

    handler(
        cast(CallbackQuery, _Call(data="__manage__:api:11", message=None)),
        cast(TeleBot, bot),
    )
    assert shown[-1] == "Managing api: Missing callback message"


def test_handle_container_full_info_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _raw_handler(container_info_module.handle_containers_full_info)
    bot = _Bot()

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: ("api", 11, 1),
    )
    monkeypatch.setattr(
        container_info_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        container_info_module, "validate_container_name", lambda name: True
    )
    monkeypatch.setattr(
        container_info_module,
        "get_comprehensive_container_details",
        lambda name: {"name": "api"},
    )

    class _Access:
        allowed_admins_ids = [11]

    class _Settings:
        access_control = _Access()

    monkeypatch.setattr(container_info_module, "settings", _Settings())
    monkeypatch.setattr(
        container_info_module,
        "get_emojis",
        lambda: {
            "spiral_calendar": "📅",
            "bullseye": "🎯",
            "BACK_arrow": "⬅️",
            "thought_balloon": "💭",
            "package": "📦",
            "gear": "⚙️",
            "chart_increasing": "📈",
            "globe_with_meridians": "🌐",
            "herb": "🌿",
            "banjo": "🪕",
        },
    )
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: "container-full",
    )
    monkeypatch.setattr(
        container_info_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        container_info_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )

    patch_not_modified_edit_error(monkeypatch, bot)

    handler(cast(CallbackQuery, _Call(data="__get_full__:api:11")), cast(TeleBot, bot))
    assert (
        bot.callback_answers[-1]["text"] == "Container details are already up to date."
    )


def test_handle_container_extra_info_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _raw_handler(runtime_info_module.handle_container_extra_info)
    bot = _Bot()
    monkeypatch.setattr(
        runtime_info_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id: (True, ""),
    )
    monkeypatch.setattr(
        runtime_info_module, "validate_container_name", lambda name: True
    )
    monkeypatch.setattr(
        runtime_info_module,
        "get_container_full_details",
        lambda name: {"name": "api", "state": "running"},
    )
    monkeypatch.setattr(
        runtime_info_module,
        "get_emojis",
        lambda: {"thought_balloon": "💭", "package": "📦", "banjo": "🪕"},
    )
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: "runtime-info",
    )
    monkeypatch.setattr(
        runtime_info_module,
        "_build_back_keyboard",
        lambda **kwargs: "kbd",
    )

    patch_not_modified_edit_error(monkeypatch, bot)

    handler(
        cast(CallbackQuery, _Call(data="__container_extra__:runtime:api:11")),
        cast(TeleBot, bot),
    )
    assert (
        bot.callback_answers[-1]["text"] == "Container details are already up to date."
    )


def test_handle_manage_container_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _raw_handler(manage_module.handle_manage_container)
    bot = _Bot()

    _patch_manage_authorization_context(monkeypatch)
    _patch_manage_view_render_dependencies(monkeypatch)
    _patch_manage_container_state(monkeypatch, state="running")
    patch_not_modified_edit_error(monkeypatch, bot)

    handler(cast(CallbackQuery, _Call(data="__manage__:api:11")), cast(TeleBot, bot))
    assert (
        bot.callback_answers[-1]["text"]
        == "Container management view is already up to date."
    )
