#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import TypedDict

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.adapters.docker.updates import DockerImageUpdater, UpdaterStatus
from pytmbot.globals import ButtonDataType, get_keyboards
from pytmbot.handlers.docker_handlers.images import IMAGES_PAGE_CALLBACK_PREFIX
from pytmbot.handlers.docker_handlers.pagination import build_page_callback_data
from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
keyboards = get_keyboards()


def _build_image_updates_keyboard(target_user_id: int | None) -> InlineKeyboardMarkup:
    check_updates_callback = "__check_updates__"
    keyboard_buttons = []

    if target_user_id is not None:
        check_updates_callback = f"__check_updates__:{target_user_id}"
        keyboard_buttons.append(
            button_data(
                text="Back to images",
                callback_data=build_page_callback_data(
                    prefix=IMAGES_PAGE_CALLBACK_PREFIX,
                    page=1,
                    user_id=target_user_id,
                ),
            )
        )

    keyboard_buttons.append(
        button_data(text="Check updates", callback_data=check_updates_callback)
    )
    return keyboards.build_inline_keyboard(keyboard_buttons)


class RawImageUpdate(TypedDict):
    current_tag: str
    created_at_local: str
    newer_tag: str
    created_at_remote: str


class RawRepositoryUpdateInfo(TypedDict, total=False):
    updates: list[RawImageUpdate]


class RenderImageUpdate(TypedDict):
    newer_tag: str
    created_at_remote: str


class RenderRepositoryUpdateInfo(TypedDict):
    current_tag: str
    created_at_local: str
    updates: list[RenderImageUpdate]


class RenderContext(TypedDict):
    updates: dict[str, RenderRepositoryUpdateInfo]
    no_updates: list[str]


def _extract_repository_updates(
    data: object,
) -> dict[str, RawRepositoryUpdateInfo]:
    if not isinstance(data, dict):
        return {}

    parsed: dict[str, RawRepositoryUpdateInfo] = {}
    for repo, repo_info in data.items():
        if not isinstance(repo, str) or not isinstance(repo_info, dict):
            continue

        updates_obj = repo_info.get("updates")
        if not isinstance(updates_obj, list):
            continue

        parsed_updates: list[RawImageUpdate] = []
        for update in updates_obj:
            if not isinstance(update, dict):
                continue

            current_tag = update.get("current_tag")
            created_at_local = update.get("created_at_local")
            newer_tag = update.get("newer_tag")
            created_at_remote = update.get("created_at_remote")

            if not (
                isinstance(current_tag, str)
                and isinstance(created_at_local, str)
                and isinstance(newer_tag, str)
                and isinstance(created_at_remote, str)
            ):
                continue

            parsed_updates.append(
                {
                    "current_tag": current_tag,
                    "created_at_local": created_at_local,
                    "newer_tag": newer_tag,
                    "created_at_remote": created_at_remote,
                }
            )

        parsed[repo] = {"updates": parsed_updates}

    return parsed


@logger.catch()
@logger.session_decorator
def handle_image_updates(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handles the callback for Docker image updates.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        target_user_id = parse_callback_target_user(
            call.data or "", "__check_updates__"
        )
    except ValueError:
        bot.answer_callback_query(
            call.id,
            text="This image updates button is no longer valid.",
            show_alert=True,
        )
        return None

    is_allowed, deny_reason = authorize_callback_request(
        call,
        target_user_id=target_user_id,
        require_owner_match=target_user_id is not None,
    )
    if not is_allowed:
        bot.answer_callback_query(call.id, text=deny_reason, show_alert=True)
        return None

    if call.message is None:
        bot.answer_callback_query(
            call.id,
            text="This image updates message can no longer be refreshed.",
            show_alert=True,
        )
        return None

    updater = DockerImageUpdater()
    updater.initialize()

    response = updater.to_dict()

    status = response.get("status")
    if not isinstance(status, str):
        bot.answer_callback_query(
            call.id,
            text="Couldn't understand the updater response.",
            show_alert=True,
        )
        return None

    # Handle rate limit
    if status == UpdaterStatus.RATE_LIMITED.name:
        retry_after = "unknown"
        rate_limit_data = response.get("data")
        if isinstance(rate_limit_data, dict):
            retry_after_obj = rate_limit_data.get("retry_after")
            if isinstance(retry_after_obj, (int, float)):
                retry_after = str(int(retry_after_obj))
            elif isinstance(retry_after_obj, str):
                retry_after = retry_after_obj
        bot.answer_callback_query(
            call.id,
            text=(f"Registry rate limit exceeded. Try again in {retry_after} seconds."),
            show_alert=True,
        )
        return None

    # Handle errors
    if status == UpdaterStatus.ERROR.name:
        error_message = response.get("message")
        rendered_message = (
            error_message if isinstance(error_message, str) else "unknown error"
        )
        bot.answer_callback_query(
            call.id,
            text=f"Couldn't check image updates: {rendered_message}",
            show_alert=True,
        )
        return None

    updates_data = _extract_repository_updates(response.get("data"))

    # Handle success with no updates
    if not updates_data or all(
        not image_info["updates"] for image_info in updates_data.values()
    ):
        bot.answer_callback_query(
            call.id,
            text="No image updates were found.",
            show_alert=True,
        )
        return None

    # Process updates
    prepared_context = prepare_context_for_render(updates_data)

    formatted_context = Compiler.quick_render(
        template_name="d_updates.jinja2", **prepared_context
    )

    edit_callback_message_text(
        call=call,
        bot=bot,
        text=formatted_context,
        parse_mode="Markdown",
        reply_markup=_build_image_updates_keyboard(target_user_id),
        not_modified_text="Image updates are already current.",
    )
    return None


def prepare_context_for_render(
    data: dict[str, RawRepositoryUpdateInfo],
) -> RenderContext:
    """
    Prepares the context for template rendering.

    Args:
        data: Dictionary containing update information for repositories

    Returns:
        Dictionary with prepared context for rendering
    """
    updates: dict[str, RenderRepositoryUpdateInfo] = {}
    no_updates = []

    for repo, info in data.items():
        repo_updates = info.get("updates", [])
        if not repo_updates:
            no_updates.append(repo)
            continue

        updates[repo] = {
            "current_tag": repo_updates[0]["current_tag"],
            "created_at_local": repo_updates[0]["created_at_local"],
            "updates": [
                {
                    "newer_tag": update["newer_tag"],
                    "created_at_remote": update["created_at_remote"],
                }
                for update in repo_updates
            ],
        }

    return {"updates": updates, "no_updates": no_updates}
