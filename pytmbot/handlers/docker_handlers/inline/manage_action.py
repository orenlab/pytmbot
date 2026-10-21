#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Container lifecycle actions from the Manage screen.

Stop and Restart first ask for confirmation; Start runs right away. A
confirmed action answers the callback at once, shows a progress view and runs
in a small background pool (telebot has only two worker threads), then edits
the Manage message with the result, the refreshed state and fresh buttons.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from html import escape
from typing import Final

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.adapters.docker.container_manager import ContainerManager
from pytmbot.adapters.docker.utils import get_container_state
from pytmbot.exceptions import (
    ContainerActionInProgressError,
    ContainerNotFoundError,
    ContainerStateConflictError,
    DockerConnectionError,
    DockerOperationException,
    InvalidContainerReferenceError,
)
from pytmbot.globals import (
    ButtonDataType,
    get_emoji_converter,
    get_keyboards,
    settings,
)
from pytmbot.handlers.docker_handlers.callback_data import (
    CONFIRM_RESTART_CALLBACK_PREFIX,
    CONFIRM_STOP_CALLBACK_PREFIX,
    CONTAINER_ACTION_CALLBACK_PREFIXES,
    MANAGE_CALLBACK_PREFIX,
    RESTART_CALLBACK_PREFIX,
    START_CALLBACK_PREFIX,
    STOP_CALLBACK_PREFIX,
    build_container_callback,
    parse_container_callback,
)
from pytmbot.handlers.docker_handlers.inline.manage import (
    ManagedContainer,
    build_manage_keyboard,
    render_manage_text,
    resolve_managed_container,
)
from pytmbot.handlers.docker_handlers.user_messages import (
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
from pytmbot.handlers.server_handlers.inline.common import (
    edit_after_answer,
    edit_callback_message_text,
)
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.utils import sanitize_exception
from pytmbot.utils.telegram_utils import callback_query_id

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()
container_manager = ContainerManager()

_ACTION_WORKERS: Final[int] = 4
_action_executor = ThreadPoolExecutor(
    max_workers=_ACTION_WORKERS, thread_name_prefix="docker-action"
)


@dataclass(frozen=True, slots=True)
class _ActionSpec:
    action: str
    title: str
    progress: str
    past: str
    confirm_prefix: str | None = None
    warning: str = ""
    # Configured seconds Docker waits for a graceful stop before killing.
    grace_seconds: Callable[[], int] | None = None


_START = _ActionSpec(action="start", title="Start", progress="Starting", past="started")
_STOP = _ActionSpec(
    action="stop",
    title="Stop",
    progress="Stopping",
    past="stopped",
    confirm_prefix=CONFIRM_STOP_CALLBACK_PREFIX,
    warning="Its services stay unavailable until the container is started again.",
    grace_seconds=lambda: settings.docker.stop_timeout,
)
_RESTART = _ActionSpec(
    action="restart",
    title="Restart",
    progress="Restarting",
    past="restarted",
    confirm_prefix=CONFIRM_RESTART_CALLBACK_PREFIX,
    warning="Its services are briefly unavailable while it restarts.",
    grace_seconds=lambda: settings.docker.restart_timeout,
)
# prefix -> (action, needs confirmation)
_REQUESTS: Final[dict[str, tuple[_ActionSpec, bool]]] = {
    START_CALLBACK_PREFIX: (_START, False),
    STOP_CALLBACK_PREFIX: (_STOP, True),
    RESTART_CALLBACK_PREFIX: (_RESTART, True),
    CONFIRM_STOP_CALLBACK_PREFIX: (_STOP, False),
    CONFIRM_RESTART_CALLBACK_PREFIX: (_RESTART, False),
}


def managing_action_fabric(call: CallbackQuery) -> bool:
    """
    Checks if a callback query is a container lifecycle action.

    Args:
        call (CallbackQuery): The callback query object.

    Returns:
        bool: True for start/stop/restart and their confirmations.
    """
    prefix = (call.data or "").split(":", 1)[0]
    return prefix in CONTAINER_ACTION_CALLBACK_PREFIXES


def _get_manage_action_context(
    call: CallbackQuery, bot: TeleBot
) -> tuple[str, str] | None:
    """Return the authorized action prefix and container reference."""
    context = get_authorized_container_callback_context(
        call=call,
        bot=bot,
        missing_user_event="bot.handler.docker.manage_action.missing.user.warn",
        denied_event="bot.handler.docker.manage_action.denied.manage.deny",
    )
    if context is None:
        return None
    parsed = parse_container_callback(context.callback_data, prefixes=_REQUESTS)
    if parsed is None:
        logger.warning("bot.handler.docker.manage_action.invalid.callback.warn")
        show_handler_info(call=call, text="This button is no longer valid.", bot=bot)
        return None
    return parsed.prefix, parsed.container_ref


# func=lambda call: managing_action_fabric(call)
@logger.session_decorator
@two_factor_auth_required
def handle_manage_container_action(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handles start/stop/restart presses and their confirmations.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    callback_context = _get_manage_action_context(call, bot)
    if callback_context is None:
        return
    prefix, container_ref = callback_context

    if call.message is None:
        show_handler_info(
            call=call,
            text="This container management message can no longer be updated.",
            bot=bot,
        )
        return

    container = resolve_managed_container(call, bot, container_ref)
    if container is None:
        return

    spec, needs_confirmation = _REQUESTS[prefix]
    if needs_confirmation:
        _ask_confirmation(call, bot, spec, container)
    else:
        _start_action(call, bot, spec, container)


def _ask_confirmation(
    call: CallbackQuery, bot: TeleBot, spec: _ActionSpec, container: ManagedContainer
) -> None:
    """Replace the Manage view with an explicit Confirm / Cancel question."""
    if spec.confirm_prefix is None:
        return
    user_id = call.from_user.id
    safe_name = escape(container.name)
    text = (
        f"<p><b>{em.get_emoji('warning')} {spec.title} {safe_name}?</b></p>"
        f"<p>{escape(spec.warning)}</p>"
        f"<p><i>Current state: {escape(container.state)}</i></p>"
    )
    keyboard = keyboards.build_inline_keyboard(
        [
            button_data(
                text=f"{em.get_emoji('check_mark_button')} Confirm {spec.action}",
                callback_data=build_container_callback(
                    spec.confirm_prefix, container.ref, user_id
                ),
                style="danger",
            ),
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Cancel",
                callback_data=build_container_callback(
                    MANAGE_CALLBACK_PREFIX, container.ref, user_id
                ),
            ),
        ]
    )
    edit_callback_message_text(
        call=call,
        bot=bot,
        rich_message=build_rich_html_message(text),
        reply_markup=keyboard,
        not_modified_text=f"Confirm or cancel: {spec.action} {container.name}.",
    )


def _start_action(
    call: CallbackQuery, bot: TeleBot, spec: _ActionSpec, container: ManagedContainer
) -> None:
    """Answer at once, show progress and run the action off the bot workers."""
    user_id = call.from_user.id
    try:
        bot.answer_callback_query(
            callback_query_id=callback_query_id(call),
            text=f"{spec.progress} {container.name}…",
            show_alert=False,
        )
    except ApiTelegramException as error:
        # An expired query must not cancel an action the user confirmed.
        logger.warning(
            "bot.handler.docker.manage_action.answer.fail",
            error=str(getattr(error, "description", error)),
        )
    _edit_after_answer(
        call,
        bot,
        f"<p><b>⏳ {spec.progress} {escape(container.name)}…</b></p>"
        f"<p><i>{_progress_hint(spec)}</i></p>",
        # Never a dead end: Refresh reopens Manage with the current state.
        reply_markup=_progress_keyboard(container, user_id),
    )
    _run_in_background(
        lambda: _run_action_and_report(call, bot, spec, container, user_id)
    )


def _progress_hint(spec: _ActionSpec) -> str:
    """Say how long the action may take, from the configured grace period."""
    if spec.grace_seconds is None:
        return "The result will appear here."
    return (
        f"Docker waits up to {spec.grace_seconds()} s for a graceful stop, "
        "then kills the container. The result will appear here."
    )


def _run_in_background(job: Callable[[], None]) -> None:
    """Run ``job`` in the action pool and log anything it failed to handle."""
    future = _action_executor.submit(job)
    future.add_done_callback(_log_background_failure)


def _log_background_failure(future: Future[None]) -> None:
    if future.cancelled():
        return
    error = future.exception()
    if isinstance(error, Exception):
        logger.error(
            "bot.handler.docker.manage_action.background.fail",
            error_type=type(error).__name__,
            error=sanitize_exception(error),
        )
    elif error is not None:
        logger.error(
            "bot.handler.docker.manage_action.background.fail",
            error_type=type(error).__name__,
        )


def _run_action_and_report(
    call: CallbackQuery,
    bot: TeleBot,
    spec: _ActionSpec,
    container: ManagedContainer,
    user_id: int,
) -> None:
    """Run the action, then show its result with the refreshed Manage view."""
    error_notice = _perform_action(spec, container, user_id)
    refreshed = _refresh_container(container)
    notice = error_notice or (
        f"✅ {container.name} {spec.past}. Current state: {refreshed.state}."
    )
    _edit_after_answer(
        call,
        bot,
        render_manage_text(refreshed, notice=notice),
        reply_markup=build_manage_keyboard(refreshed, user_id),
        retry=True,
    )


def _perform_action(
    spec: _ActionSpec, container: ManagedContainer, user_id: int
) -> str | None:
    """Run the Docker action; return a user-facing notice when it failed."""
    name = container.name
    try:
        container_manager.managing_container(user_id, container.ref, action=spec.action)
    except ContainerActionInProgressError:
        return f"An action on {name} is already in progress."
    except ContainerStateConflictError as error:
        return _state_conflict_notice(spec, name, error.state)
    except ContainerNotFoundError:
        return f"{name} was not found. It may have been removed or recreated."
    except InvalidContainerReferenceError:
        return INVALID_CONTAINER_REF_TEXT
    except DockerConnectionError:
        return DOCKER_UNAVAILABLE_TEXT
    except PermissionError as error:
        return f"Can't {spec.action} {name}: {error}"
    except DockerOperationException as error:
        logger.error(
            "bot.handler.docker.manage_action.action.fail",
            action=spec.action,
            error_type=type(error).__name__,
            error=error.sanitized_message(),
        )
        return f"Docker couldn't {spec.action} {name}. See the bot logs for details."
    except Exception as error:
        # Last line of a background job: report instead of leaving the
        # progress view on screen forever, and keep the details in the logs.
        logger.error(
            "bot.handler.docker.manage_action.action.fail",
            action=spec.action,
            error_type=type(error).__name__,
            error=sanitize_exception(error),
        )
        return f"Couldn't {spec.action} {name}: Docker reported an error. See the bot logs."
    logger.info("bot.handler.docker.manage_action.action.ok", action=spec.action)
    return None


# action -> (states meaning "already done", wording for that case)
_ALREADY_DONE: Final[dict[str, tuple[frozenset[str], str]]] = {
    "start": (frozenset({"", "running", "restarting"}), "already running"),
    "stop": (frozenset({"", "exited", "created", "dead"}), "already stopped"),
}


def _state_conflict_notice(spec: _ActionSpec, name: str, state: str) -> str:
    """Explain an action that does not fit the container's current state."""
    state_suffix = f" (state: {state})" if state else ""
    done_states, done_text = _ALREADY_DONE.get(spec.action, (frozenset(), ""))
    if state.lower() in done_states:
        return f"{name} is {done_text}{state_suffix}."
    return f"{name} can't be {spec.past} right now{state_suffix}."


def _refresh_container(container: ManagedContainer) -> ManagedContainer:
    """Re-read the state after an action (the adapter drops its state cache)."""
    try:
        state = get_container_state(container.ref)
    except (DockerConnectionError, DockerOperationException):
        # The action result is still reported; only the state is unknown.
        return replace(container, state="unknown")
    if state is None:
        return replace(container, state="not found")
    return replace(container, state=state.lower())


def _progress_keyboard(
    container: ManagedContainer, user_id: int
) -> InlineKeyboardMarkup:
    return keyboards.build_inline_keyboard(
        [
            button_data(
                text=f"{em.get_emoji('counterclockwise_arrows_button')} Refresh",
                callback_data=build_container_callback(
                    MANAGE_CALLBACK_PREFIX, container.ref, user_id
                ),
            )
        ]
    )


def _edit_after_answer(
    call: CallbackQuery,
    bot: TeleBot,
    html: str,
    *,
    reply_markup: InlineKeyboardMarkup | None,
    retry: bool = False,
) -> None:
    """
    Edit the Manage message after the callback has already been answered.

    Background results pass ``retry`` so a Telegram rate limit does not leave
    the message on the progress view; other failures are logged.
    """
    edit_after_answer(
        call,
        bot,
        rich_message=build_rich_html_message(html),
        reply_markup=reply_markup,
        retry=retry,
    )
