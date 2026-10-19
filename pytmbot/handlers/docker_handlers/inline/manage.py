#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.adapters.docker.containers_info import fetch_full_container_details
from pytmbot.exceptions import (
    DockerConnectionError,
    DockerOperationException,
    InvalidContainerReferenceError,
)
from pytmbot.globals import ButtonDataType, get_emoji_converter, get_keyboards
from pytmbot.handlers.docker_handlers.callback_data import (
    MANAGE_CALLBACK_PREFIX,
    RESTART_CALLBACK_PREFIX,
    START_CALLBACK_PREFIX,
    STOP_CALLBACK_PREFIX,
    build_container_callback,
    container_short_id,
    is_valid_container_ref,
    parse_container_callback,
)
from pytmbot.handlers.docker_handlers.pagination import (
    build_container_full_info_callback_data,
)
from pytmbot.handlers.docker_handlers.user_messages import (
    CONTAINER_NOT_FOUND_TEXT,
    DOCKER_REQUEST_FAILED_TEXT,
    DOCKER_UNAVAILABLE_TEXT,
    INVALID_CONTAINER_REF_TEXT,
)
from pytmbot.handlers.handlers_util.docker import (
    get_manage_container_callback_context as get_authorized_container_callback_context,
)
from pytmbot.handlers.handlers_util.docker import (
    show_handler_info,
)
from pytmbot.handlers.handlers_util.rich_messages import build_rich_html_message
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.keyboards.keyboards import ButtonData
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.models.docker_models import ContainersState
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()

# Actions offered per Docker state (matching the adapter's state rules).
# Dead containers cannot be started again, only removed on the host.
_ACTIONS_BY_STATE: Final[dict[str, tuple[str, ...]]] = {
    ContainersState.running: (STOP_CALLBACK_PREFIX, RESTART_CALLBACK_PREFIX),
    ContainersState.paused: (STOP_CALLBACK_PREFIX, RESTART_CALLBACK_PREFIX),
    ContainersState.restarting: (STOP_CALLBACK_PREFIX,),
    "created": (START_CALLBACK_PREFIX,),
    ContainersState.exited: (START_CALLBACK_PREFIX,),
}
_STATE_HINTS: Final[dict[str, str]] = {
    ContainersState.dead: "This container is dead and can't be started. Remove it "
    "on the host (docker rm).",
    "removing": "This container is being removed.",
}
_UNKNOWN_STATE_HINT: Final[str] = "No actions are available in this state."


@dataclass(frozen=True, slots=True)
class ManagedContainer:
    """Container identity and state as Docker reports them."""

    ref: str
    name: str
    state: str


def describe_container(container: object, fallback_ref: str) -> ManagedContainer:
    """Build a ManagedContainer from a docker-py container object."""
    name = str(getattr(container, "name", "") or "").lstrip("/") or fallback_ref
    state = str(getattr(container, "status", "") or "unknown").lower()
    ref = container_short_id(getattr(container, "id", None)) or fallback_ref
    return ManagedContainer(ref=ref, name=name, state=state)


def resolve_managed_container(
    call: CallbackQuery, bot: TeleBot, container_ref: str
) -> ManagedContainer | None:
    """Look the container up exactly; answer the callback when that fails."""
    error_text: str | None = None
    container: object | None = None
    if not is_valid_container_ref(container_ref):
        error_text = INVALID_CONTAINER_REF_TEXT
    else:
        try:
            container = fetch_full_container_details(container_ref)
        except DockerConnectionError:
            error_text = DOCKER_UNAVAILABLE_TEXT
        except InvalidContainerReferenceError:
            error_text = INVALID_CONTAINER_REF_TEXT
        except DockerOperationException:
            error_text = DOCKER_REQUEST_FAILED_TEXT
        if error_text is None and container is None:
            error_text = CONTAINER_NOT_FOUND_TEXT

    if error_text is not None or container is None:
        logger.info("bot.handler.docker.manage.container.unavailable.info")
        show_handler_info(
            call=call, text=error_text or CONTAINER_NOT_FOUND_TEXT, bot=bot
        )
        return None
    return describe_container(container, container_ref)


def _action_button(
    prefix: str, container: ManagedContainer, user_id: int
) -> ButtonData:
    labels = {
        START_CALLBACK_PREFIX: (f"{em.get_emoji('glowing_star')} Start", "success"),
        STOP_CALLBACK_PREFIX: (f"{em.get_emoji('no_entry')} Stop", "danger"),
        RESTART_CALLBACK_PREFIX: (
            f"{em.get_emoji('recycling_symbol')} Restart",
            "primary",
        ),
    }
    text, style = labels[prefix]
    return button_data(
        text=text,
        callback_data=build_container_callback(prefix, container.ref, user_id),
        style=style,
    )


def build_manage_keyboard(
    container: ManagedContainer, user_id: int
) -> InlineKeyboardMarkup:
    """Action buttons for the container's state plus a way back to details."""
    keyboard_buttons = [
        _action_button(prefix, container, user_id)
        for prefix in _ACTIONS_BY_STATE.get(container.state, ())
    ]
    keyboard_buttons.append(
        button_data(
            text=f"{em.get_emoji('BACK_arrow')} {container.name}",
            callback_data=build_container_full_info_callback_data(
                container_ref=container.ref, user_id=user_id
            ),
        )
    )
    return keyboards.build_inline_keyboard(keyboard_buttons)


def render_manage_text(
    container: ManagedContainer, *, notice: str | None = None
) -> str:
    """Render the Manage screen body, optionally with an action result notice."""
    hint = None
    if container.state not in _ACTIONS_BY_STATE:
        hint = _STATE_HINTS.get(container.state, _UNKNOWN_STATE_HINT)
    emojis: dict[str, str] = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "briefcase": em.get_emoji("briefcase"),
        "anxious_face_with_sweat": em.get_emoji("anxious_face_with_sweat"),
    }
    return Compiler.quick_render(
        "d_managing_containers.jinja2",
        emojis=emojis,
        state=container.state,
        container_name=container.name,
        container_id=container.ref,
        notice=notice,
        hint=hint,
    )


# func=lambda call: call.data.startswith('__manage__')
@logger.catch()
@logger.session_decorator
@two_factor_auth_required
def handle_manage_container(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handles the callback for managing a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    auth_context = get_authorized_container_callback_context(
        call=call,
        bot=bot,
        missing_user_event="bot.handler.docker.manage.missing.user.warn",
        denied_event="bot.handler.docker.manage.denied.function.deny",
    )
    if auth_context is None:
        return

    if call.message is None:
        show_handler_info(
            call=call,
            text="This container management message can no longer be updated.",
            bot=bot,
        )
        return

    parsed = parse_container_callback(call.data, prefixes={MANAGE_CALLBACK_PREFIX})
    if parsed is None:
        show_handler_info(call=call, text=INVALID_CONTAINER_REF_TEXT, bot=bot)
        return

    container = resolve_managed_container(call, bot, parsed.container_ref)
    if container is None:
        return
    logger.info("bot.handler.docker.manage.container.state.info", state=container.state)

    edit_callback_message_text(
        call=call,
        bot=bot,
        rich_message=build_rich_html_message(render_manage_text(container)),
        reply_markup=build_manage_keyboard(container, auth_context.user_id),
        not_modified_text="Container management view is already current.",
    )
