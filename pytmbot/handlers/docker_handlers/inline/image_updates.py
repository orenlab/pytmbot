#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import contextvars
import math
from collections.abc import Callable, Mapping
from functools import partial
from queue import SimpleQueue
from threading import Lock, Thread
from typing import Final, TypedDict

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.adapters.docker.updates import (
    CHECK_DEADLINE,
    UpdaterResponse,
    UpdaterStatus,
    get_image_updater,
)
from pytmbot.globals import ButtonDataType, get_emoji_converter, get_keyboards
from pytmbot.handlers.docker_handlers.images import IMAGES_PAGE_CALLBACK_PREFIX
from pytmbot.handlers.docker_handlers.pagination import build_page_callback_data
from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)
from pytmbot.handlers.handlers_util.rich_messages import (
    build_rich_html_message,
    screen_updated_at,
)
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.telegram_utils import callback_query_id

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()

CHECK_STARTED_TEXT: Final[str] = "Checking for updates…"
CHECK_RUNNING_TEXT: Final[str] = "A check is already running"
NOT_MODIFIED_TEXT: Final[str] = "Image updates are already current."

_DEADLINE_SECONDS: Final[int] = int(CHECK_DEADLINE)
NOTICE_NO_IMAGES: Final[str] = "No tagged local images to check."
NOTICE_DOCKER_ERROR: Final[str] = (
    "Couldn't read local images from Docker. "
    "Check that pyTMBot can reach the Docker socket."
)
NOTICE_TIMEOUT: Final[str] = (
    f"The check took longer than {_DEADLINE_SECONDS} s and was stopped. "
    "Try again later."
)
NOTICE_PARTIAL_TIMEOUT: Final[str] = (
    f"The check stopped after {_DEADLINE_SECONDS} s. "
    "Images it did not finish are listed under Couldn't check."
)
NOTICE_ERROR: Final[str] = "Couldn't check image updates. See the bot logs for details."
NOTICE_RATE_LIMITED: Final[str] = "Docker Hub rate limit reached. Try again in {wait}."
NOTICE_RATE_LIMITED_UNKNOWN: Final[str] = (
    "Docker Hub rate limit reached. Try again later."
)


def _build_image_updates_keyboard(target_user_id: int | None) -> InlineKeyboardMarkup:
    check_updates_callback = "__check_updates__"
    keyboard_buttons = []

    if target_user_id is not None:
        check_updates_callback = f"__check_updates__:{target_user_id}"
        keyboard_buttons.append(
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Images",
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
    error: str


class RenderImageUpdate(TypedDict):
    newer_tag: str
    created_at_remote: str


class RenderUpdateGroup(TypedDict):
    current_tag: str
    created_at_local: str
    updates: list[RenderImageUpdate]


class RenderRepositoryUpdateInfo(TypedDict):
    groups: list[RenderUpdateGroup]


class RenderFailure(TypedDict):
    name: str
    reason: str


class RenderContext(TypedDict):
    updates: dict[str, RenderRepositoryUpdateInfo]
    no_updates: list[str]
    failed: list[RenderFailure]


class _SingleFlightWorker:
    """Dedicated daemon thread that runs at most one job at a time."""

    def __init__(self, thread_name: str) -> None:
        self._thread_name = thread_name
        self._lock = Lock()
        self._busy = False
        self._jobs: SimpleQueue[tuple[contextvars.Context, Callable[[], None]]] = (
            SimpleQueue()
        )
        self._thread: Thread | None = None

    def try_start(self, job: Callable[[], None]) -> bool:
        """Hand ``job`` to the worker unless a job is still running; never blocks."""
        with self._lock:
            thread_alive = self._thread is not None and self._thread.is_alive()
            if self._busy and thread_alive:
                return False
            # A worker that died mid-job must not leave the check blocked forever.
            self._busy = False
            self._ensure_thread()
            self._busy = True
        self._jobs.put((contextvars.copy_context(), job))
        return True

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        thread = Thread(target=self._serve, name=self._thread_name, daemon=True)
        thread.start()
        self._thread = thread

    def _serve(self) -> None:
        while True:
            context, job = self._jobs.get()
            try:
                context.run(job)
            except Exception:
                logger.exception("bot.handler.docker.image.updates.job.fail")
            finally:
                with self._lock:
                    self._busy = False


# One check at a time per process; registry lookups never run on Telegram workers.
_check_worker = _SingleFlightWorker("docker_updates_check")


def _authorize_image_updates_callback(
    call: CallbackQuery, bot: TeleBot
) -> tuple[bool, int | None]:
    """Validate and authorize image-updates callback with legacy testable seams."""

    def reject_callback(
        text: str, target_user_id: int | None
    ) -> tuple[bool, int | None]:
        bot.answer_callback_query(callback_query_id(call), text=text, show_alert=True)
        return False, target_user_id

    try:
        target_user_id = parse_callback_target_user(
            call.data or "", "__check_updates__"
        )
    except ValueError:
        return reject_callback("This image updates button is no longer valid.", None)

    is_allowed, deny_reason = authorize_callback_request(
        call,
        target_user_id=target_user_id,
        require_owner_match=target_user_id is not None,
    )
    if not is_allowed:
        return reject_callback(deny_reason, target_user_id)

    if call.message is None:
        return reject_callback(
            "This image updates message can no longer be refreshed.",
            target_user_id,
        )

    return True, target_user_id


def _parse_raw_update(update: object) -> RawImageUpdate | None:
    if not isinstance(update, Mapping):
        return None

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
        return None

    return {
        "current_tag": current_tag,
        "created_at_local": created_at_local,
        "newer_tag": newer_tag,
        "created_at_remote": created_at_remote,
    }


def _parse_repository_entry(
    repo_info: Mapping[object, object],
) -> RawRepositoryUpdateInfo | None:
    error = repo_info.get("error")
    if isinstance(error, str) and error:
        return {"updates": [], "error": error}

    updates_obj = repo_info.get("updates")
    if not isinstance(updates_obj, list):
        return None
    parsed_updates = [_parse_raw_update(update) for update in updates_obj]
    return {"updates": [update for update in parsed_updates if update is not None]}


def _extract_repository_updates(
    data: object,
) -> dict[str, RawRepositoryUpdateInfo]:
    if not isinstance(data, Mapping):
        return {}

    parsed: dict[str, RawRepositoryUpdateInfo] = {}
    for repo, repo_info in data.items():
        if not isinstance(repo, str) or not isinstance(repo_info, Mapping):
            continue
        entry = _parse_repository_entry(repo_info)
        if entry is not None:
            parsed[repo] = entry
    return parsed


def _group_updates(raw_updates: list[RawImageUpdate]) -> list[RenderUpdateGroup]:
    """Group updates under the local tag they belong to, without duplicates."""
    groups: dict[str, RenderUpdateGroup] = {}
    seen: set[tuple[str, str]] = set()
    for update in raw_updates:
        key = (update["current_tag"], update["newer_tag"])
        if key in seen:
            continue
        seen.add(key)
        group = groups.setdefault(
            update["current_tag"],
            {
                "current_tag": update["current_tag"],
                "created_at_local": update["created_at_local"],
                "updates": [],
            },
        )
        group["updates"].append(
            {
                "newer_tag": update["newer_tag"],
                "created_at_remote": update["created_at_remote"],
            }
        )
    return list(groups.values())


def prepare_context_for_render(
    data: dict[str, RawRepositoryUpdateInfo],
) -> RenderContext:
    """
    Prepares the context for template rendering.

    Args:
        data: Update information keyed by image reference

    Returns:
        Images with updates, images that are up to date, and images that could
        not be checked together with the reason.
    """
    updates: dict[str, RenderRepositoryUpdateInfo] = {}
    no_updates: list[str] = []
    failed: list[RenderFailure] = []

    for repo in sorted(data):
        info = data[repo]
        error = info.get("error")
        if error:
            failed.append({"name": repo, "reason": error})
            continue

        groups = _group_updates(info.get("updates", []))
        if groups:
            updates[repo] = {"groups": groups}
        else:
            no_updates.append(repo)

    return {"updates": updates, "no_updates": no_updates, "failed": failed}


def _format_wait(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} s"
    minutes = math.ceil(seconds / 60)
    if minutes < 120:
        return f"{minutes} min"
    return f"{math.ceil(minutes / 60)} h"


def _report_notice(response: UpdaterResponse) -> str:
    """Explain a stopped or failed check above the per-image sections."""
    metadata = response.metadata
    if response.status == UpdaterStatus.VALIDATION_ERROR:
        return NOTICE_NO_IMAGES
    if response.status == UpdaterStatus.DOCKER_ERROR:
        return NOTICE_DOCKER_ERROR
    if metadata.get("deadline_exceeded"):
        return NOTICE_PARTIAL_TIMEOUT if response.data else NOTICE_TIMEOUT
    if not response.data:
        return NOTICE_ERROR
    if metadata.get("rate_limited_repos"):
        retry_after = metadata.get("retry_after")
        if isinstance(retry_after, int) and retry_after > 0:
            return NOTICE_RATE_LIMITED.format(wait=_format_wait(retry_after))
        return NOTICE_RATE_LIMITED_UNKNOWN
    return ""


def render_update_report(response: UpdaterResponse) -> str:
    """Render the rich HTML report for a finished update check."""
    context = prepare_context_for_render(_extract_repository_updates(response.data))
    return Compiler.quick_render(
        template_name="d_updates.jinja2",
        **context,
        notice=_report_notice(response),
        checked_at=screen_updated_at(),
    )


def _publish_report(
    call: CallbackQuery, bot: TeleBot, html: str, target_user_id: int | None
) -> None:
    try:
        edit_callback_message_text(
            call=call,
            bot=bot,
            rich_message=build_rich_html_message(html),
            reply_markup=_build_image_updates_keyboard(target_user_id),
            not_modified_text=NOT_MODIFIED_TEXT,
        )
    except ApiTelegramException as error:
        # The button was answered when the check started, so a failed edit
        # cannot be reported with another toast; keep it in the logs.
        logger.warning(
            "bot.handler.docker.image.updates.edit.fail.warn",
            error=str(getattr(error, "description", error)),
        )


def _run_update_check(
    call: CallbackQuery, bot: TeleBot, target_user_id: int | None
) -> None:
    """Background job: check Docker Hub, then replace the message with the report."""
    try:
        response = get_image_updater().check_updates(CHECK_DEADLINE)
    except Exception:
        # Still replace the message, so the user is not left waiting.
        logger.exception("bot.handler.docker.image.updates.check.fail")
        response = UpdaterResponse(status=UpdaterStatus.ERROR, message="failed")
    _publish_report(call, bot, render_update_report(response), target_user_id)


@logger.catch()
@logger.session_decorator
def handle_image_updates(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Start a Docker image update check and acknowledge the button at once.

    The check runs on a dedicated single-flight worker, so the Telegram worker
    thread never waits on Docker Hub. When the check finishes, the worker edits
    the original message with the report.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    is_allowed, target_user_id = _authorize_image_updates_callback(call, bot)
    if not is_allowed or call.message is None:
        return None

    started = _check_worker.try_start(
        partial(_run_update_check, call, bot, target_user_id)
    )
    bot.answer_callback_query(
        callback_query_id(call),
        text=CHECK_STARTED_TEXT if started else CHECK_RUNNING_TEXT,
        show_alert=False,
    )
    return None
