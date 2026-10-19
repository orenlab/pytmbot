#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import hashlib
import io
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.adapters.docker.containers_info import fetch_full_container_details
from pytmbot.exceptions import (
    ContainerLogsUnavailableError,
    ContainerNotFoundError,
    DockerConnectionError,
    DockerOperationException,
    InvalidContainerReferenceError,
)
from pytmbot.globals import ButtonDataType, get_emoji_converter, get_keyboards
from pytmbot.handlers.docker_handlers.callback_data import (
    LOGS_CALLBACK_PREFIX,
    build_callback_data,
    container_short_id,
    is_valid_container_ref,
    parse_callback_user_id,
)
from pytmbot.handlers.docker_handlers.containers import CONTAINERS_PAGE_CALLBACK_PREFIX
from pytmbot.handlers.docker_handlers.pagination import (
    build_container_full_info_callback_data,
    build_page_callback_data,
)
from pytmbot.handlers.docker_handlers.user_messages import (
    CONTAINER_NOT_FOUND_TEXT,
    DOCKER_REQUEST_FAILED_TEXT,
    DOCKER_UNAVAILABLE_TEXT,
    INVALID_CONTAINER_REF_TEXT,
)
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    get_sanitized_logs,
    show_handler_info,
)
from pytmbot.handlers.handlers_util.rich_messages import build_rich_html_message
from pytmbot.handlers.handlers_util.utils import send_docker_message
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.keyboards.keyboards import NAV_DOCKER
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.message_deletion import (
    DeletionResult,
    DeletionStatus,
    create_post_delete_navigation_callback,
    deletion_manager,
)
from pytmbot.utils.telegram_utils import callback_query_id

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()

MAX_TELEGRAM_MESSAGE_LENGTH: Final[int] = 4096
MAX_LOGS_PAGE_CHARS: Final[int] = 3200
LOGS_SESSION_TTL_SECONDS: Final[int] = 300
LOGS_SESSION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{12}")
LOGS_ACTION_OPEN: Final[str] = "open"
LOGS_ACTION_NAV: Final[str] = "nav"
LOGS_ACTION_REFRESH: Final[str] = "refresh"
LOGS_ACTION_FILE: Final[str] = "file"
LOGS_TRUNCATION_NOTICE: Final[str] = "[LOGS TRUNCATED FOR TELEGRAM LENGTH LIMIT]\n"
LOGS_EMPTY_MESSAGE: Final[str] = "No logs are available for this container."
LOGS_FILE_AUTO_DELETE_DELAY_SECONDS: Final[int] = 30
LOGS_FILE_DELETION_NOTICE: Final[str] = (
    "This file will be automatically deleted in 30 seconds."
)
LOGS_UNSUPPORTED_DRIVER_MESSAGE: Final[str] = (
    "This container does not provide readable logs "
    "(configured Docker logging driver does not support reading)."
)
LOGS_FILE_DELETED_NAVIGATION_TEXT: Final[str] = (
    "🧹 Logs file message was deleted for privacy.\n"
    "Use the button below to return to the main menu."
)


@dataclass(frozen=True, slots=True)
class ParsedLogsCallback:
    action: str
    user_id: int
    container_ref: str | None = None
    session_id: str | None = None
    page_index: int = 0


@dataclass(slots=True)
class LogsSession:
    session_id: str
    container_ref: str
    container_name: str
    user_id: int
    raw_logs: str
    chunks: list[str]
    created_at: float


class LogsSessionStore:
    """Thread-safe in-memory session cache for paginated logs."""

    def __init__(self, ttl_seconds: int = LOGS_SESSION_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, LogsSession] = {}
        self._lock = RLock()

    def _cleanup_expired_unlocked(self, now: float) -> None:
        expired_keys = [
            key
            for key, value in self._sessions.items()
            if now - value.created_at > self._ttl_seconds
        ]
        for key in expired_keys:
            self._sessions.pop(key, None)

    @staticmethod
    def _generate_session_id(container_ref: str, user_id: int) -> str:
        seed = f"{container_ref}:{user_id}:{time.time_ns()}"
        return hashlib.blake2s(seed.encode(), digest_size=6).hexdigest()

    def create(
        self,
        *,
        container_ref: str,
        container_name: str,
        user_id: int,
        raw_logs: str,
        chunks: list[str],
    ) -> LogsSession:
        now = time.time()
        with self._lock:
            self._cleanup_expired_unlocked(now)

            session_id = self._generate_session_id(container_ref, user_id)
            while session_id in self._sessions:
                session_id = self._generate_session_id(container_ref, user_id)

            session = LogsSession(
                session_id=session_id,
                container_ref=container_ref,
                container_name=container_name,
                user_id=user_id,
                raw_logs=raw_logs,
                chunks=chunks,
                created_at=now,
            )
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> LogsSession | None:
        now = time.time()
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            if now - session.created_at > self._ttl_seconds:
                self._sessions.pop(session_id, None)
                return None

            return session

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


_logs_sessions = LogsSessionStore()


def _logs_file_deletion_callback(result: DeletionResult) -> None:
    """Callback function executed after logs file deletion attempt."""
    if result.status == DeletionStatus.SUCCESS:
        logger.info("bot.handler.docker.logging.logs.file.info")
    elif result.status == DeletionStatus.FAILED:
        logger.warning("bot.handler.docker.logging.delete.logs.fail")


def _render_logs_template(
    logs: str, container_name: str, emojis: dict[str, str]
) -> str:
    """Render logs template with provided context."""
    return Compiler.quick_render(
        "d_logs.jinja2",
        emojis=emojis,
        logs=logs,
        container_name=container_name,
    )


def _parse_logs_user_id(raw_user_id: str) -> int:
    user_id = parse_callback_user_id(raw_user_id)
    if user_id is None:
        raise ValueError("Invalid logs callback user id")
    return user_id


def _parse_logs_container_ref(container_ref: str) -> str:
    if not is_valid_container_ref(container_ref):
        raise ValueError("Invalid logs container reference")
    return container_ref


def _parse_logs_session_id(session_id: str) -> str:
    if LOGS_SESSION_ID_PATTERN.fullmatch(session_id) is None:
        raise ValueError("Invalid logs session id")
    return session_id


def _parse_logs_callback_data(callback_data: str) -> ParsedLogsCallback:
    """
    Parse callback data for logs actions.

    Supported:
    - Legacy: __get_logs__:<container_ref>:<user_id>
    - New: __get_logs__:open:<container_ref>:<user_id>
    - New: __get_logs__:nav:<session_id>:<page_index>:<user_id>
    - New: __get_logs__:refresh:<session_id>:<user_id>
    - New: __get_logs__:file:<session_id>:<user_id>

    Raises:
        ValueError: For unknown formats or invalid segments.
    """
    parts = callback_data.split(":")
    if not parts or parts[0] != LOGS_CALLBACK_PREFIX:
        raise ValueError("Invalid logs callback prefix")

    actions = {LOGS_ACTION_OPEN, LOGS_ACTION_NAV, LOGS_ACTION_REFRESH, LOGS_ACTION_FILE}
    # Backward-compatible format.
    if len(parts) == 3 and parts[1] not in actions:
        return ParsedLogsCallback(
            action=LOGS_ACTION_OPEN,
            container_ref=_parse_logs_container_ref(parts[1]),
            user_id=_parse_logs_user_id(parts[2]),
        )

    if len(parts) == 4 and parts[1] == LOGS_ACTION_OPEN:
        return ParsedLogsCallback(
            action=LOGS_ACTION_OPEN,
            container_ref=_parse_logs_container_ref(parts[2]),
            user_id=_parse_logs_user_id(parts[3]),
        )

    if len(parts) == 5 and parts[1] == LOGS_ACTION_NAV:
        return ParsedLogsCallback(
            action=LOGS_ACTION_NAV,
            session_id=_parse_logs_session_id(parts[2]),
            page_index=int(parts[3]),
            user_id=_parse_logs_user_id(parts[4]),
        )

    if len(parts) == 4 and parts[1] in {LOGS_ACTION_REFRESH, LOGS_ACTION_FILE}:
        return ParsedLogsCallback(
            action=parts[1],
            session_id=_parse_logs_session_id(parts[2]),
            user_id=_parse_logs_user_id(parts[3]),
        )

    raise ValueError("Unsupported logs callback format")


def _build_logs_chunks(
    logs: str, max_chunk_chars: int = MAX_LOGS_PAGE_CHARS
) -> list[str]:
    """Split logs into pages where index 0 contains newest logs."""
    if not logs.strip():
        return [LOGS_EMPTY_MESSAGE]

    chunks: list[str] = []
    end = len(logs)

    while end > 0:
        start = max(0, end - max_chunk_chars)

        if start > 0:
            newline_index = logs.find("\n", start, end)
            if newline_index != -1 and newline_index + 1 < end:
                start = newline_index + 1

        chunk = logs[start:end].strip("\n")
        if chunk:
            chunks.append(chunk)
        end = start

    return chunks or [LOGS_EMPTY_MESSAGE]


def _is_logs_session_owner(call: CallbackQuery, session: LogsSession) -> bool:
    """Check that callback caller owns the logs session."""
    if call.from_user is None:
        return False
    return int(call.from_user.id) == session.user_id


def _validate_logs_session_access(
    call: CallbackQuery,
    bot: TeleBot,
    session: LogsSession,
    *,
    requested_action: str,
) -> bool:
    """
    Validate session ownership and active auth for logs session actions.

    This is a defense-in-depth guard for direct handler invocations and
    stale callback payloads.
    """
    if not _is_logs_session_owner(call, session):
        current_user_id = call.from_user.id if call.from_user else "unknown"
        logger.warning(
            "bot.handler.docker.logging.denied.logs.deny",
            requested_action=requested_action,
            current_user_id=current_user_id,
            session_user_id=session.user_id,
            session_id=session.session_id,
        )
        show_handler_info(
            call=call,
            text="This logs session belongs to another user.",
            bot=bot,
        )
        return False

    is_allowed, deny_reason = authorize_docker_callback_request(
        call=call,
        called_user_id=session.user_id,
        require_admin=True,
        require_owner_match=True,
        require_session=True,
    )
    if not is_allowed:
        current_user_id = call.from_user.id if call.from_user else "unknown"
        logger.warning(
            "bot.handler.docker.logging.denied.logs.deny",
            requested_action=requested_action,
            current_user_id=current_user_id,
            session_id=session.session_id,
            reason=deny_reason,
        )
        show_handler_info(
            call=call,
            text=f"Getting logs: {deny_reason}",
            bot=bot,
        )
        return False

    return True


def _clamp_page_index(page_index: int, total_pages: int) -> int:
    if total_pages <= 1:
        return 0
    return max(0, min(page_index, total_pages - 1))


def _render_logs_page(
    logs_chunk: str,
    container_name: str,
    emojis: dict[str, str],
    page_index: int,
    total_pages: int,
) -> tuple[str, bool]:
    """
    Render one logs page and guarantee Telegram hard message limit.

    Returns:
        tuple[str, bool]: (rendered_text, was_truncated)
    """
    header = f"[Page {page_index + 1}/{total_pages} | Newest first]"
    logs_payload = f"{header}\n{logs_chunk}"
    context = _render_logs_template(
        logs=logs_payload, container_name=container_name, emojis=emojis
    )
    if len(context) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return context, False

    left, right = 1, len(logs_chunk)
    best_context = ""

    while left <= right:
        mid = (left + right) // 2
        tail_logs = logs_chunk[-mid:]
        candidate_logs = f"{header}\n{LOGS_TRUNCATION_NOTICE}{tail_logs}"
        candidate_context = _render_logs_template(
            logs=candidate_logs, container_name=container_name, emojis=emojis
        )

        if len(candidate_context) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            best_context = candidate_context
            left = mid + 1
        else:
            right = mid - 1

    if best_context:
        return best_context, True

    fallback_logs = (
        f"{header}\n"
        "Logs are too large to display in Telegram.\n"
        "Use server console command below."
    )
    fallback_context = _render_logs_template(
        logs=fallback_logs, container_name=container_name, emojis=emojis
    )

    return fallback_context[:MAX_TELEGRAM_MESSAGE_LENGTH], True


def _build_logs_keyboard(
    session: LogsSession, current_page: int, total_pages: int
) -> InlineKeyboardMarkup:
    """Build logs keyboard with navigation and actions."""
    keyboard_buttons = []

    def nav(page_index: int) -> str:
        return build_callback_data(
            LOGS_CALLBACK_PREFIX,
            LOGS_ACTION_NAV,
            session.session_id,
            page_index,
            session.user_id,
        )

    def session_action(action: str) -> str:
        return build_callback_data(
            LOGS_CALLBACK_PREFIX, action, session.session_id, session.user_id
        )

    if current_page > 0:
        keyboard_buttons.append(
            button_data(text="Newer", callback_data=nav(current_page - 1))
        )

    if current_page < total_pages - 1:
        keyboard_buttons.append(
            button_data(text="Older", callback_data=nav(current_page + 1))
        )

    keyboard_buttons.extend(
        [
            button_data(
                text="Refresh", callback_data=session_action(LOGS_ACTION_REFRESH)
            ),
            button_data(text="As file", callback_data=session_action(LOGS_ACTION_FILE)),
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} {session.container_name}",
                callback_data=build_container_full_info_callback_data(
                    container_ref=session.container_ref, user_id=session.user_id
                ),
            ),
            button_data(
                text=f"{em.get_emoji('house')} All containers",
                callback_data=build_page_callback_data(
                    prefix=CONTAINERS_PAGE_CALLBACK_PREFIX,
                    page=1,
                    user_id=session.user_id,
                ),
            ),
        ]
    )

    return keyboards.build_inline_keyboard(keyboard_buttons)


def _edit_logs_message(
    call: CallbackQuery,
    bot: TeleBot,
    session: LogsSession,
    page_index: int,
    emojis: dict[str, str],
) -> bool:
    if call.message is None:
        logger.warning("bot.handler.docker.logging.cannot.render.warn")
        return show_handler_info(
            call=call,
            text="This logs message can no longer be updated.",
            bot=bot,
        )

    total_pages = len(session.chunks)
    safe_page_index = _clamp_page_index(page_index, total_pages)
    logs_chunk = session.chunks[safe_page_index]

    context, was_truncated = _render_logs_page(
        logs_chunk=logs_chunk,
        container_name=session.container_name,
        emojis=emojis,
        page_index=safe_page_index,
        total_pages=total_pages,
    )
    inline_keyboard = _build_logs_keyboard(
        session=session, current_page=safe_page_index, total_pages=total_pages
    )

    logger.debug(
        "bot.handler.docker.logging.compiled.logs.ok",
        page=f"{safe_page_index + 1}/{total_pages}",
        message_length=len(context),
        logs_truncated_for_telegram=was_truncated,
    )

    return edit_callback_message_text(
        call=call,
        bot=bot,
        rich_message=build_rich_html_message(context),
        reply_markup=inline_keyboard,
        not_modified_text="Logs view is already current.",
    )


def _resolve_logs_container(
    call: CallbackQuery, bot: TeleBot, container_ref: str
) -> tuple[str, str] | None:
    """Return (short id, name) of the container or explain why it is unavailable."""
    error_text: str | None = None
    container: object | None = None
    try:
        container = fetch_full_container_details(container_ref)
    except DockerConnectionError:
        error_text = DOCKER_UNAVAILABLE_TEXT
    except InvalidContainerReferenceError:
        error_text = INVALID_CONTAINER_REF_TEXT
    except DockerOperationException:
        error_text = DOCKER_REQUEST_FAILED_TEXT

    if container is None:
        show_handler_info(call, text=error_text or CONTAINER_NOT_FOUND_TEXT, bot=bot)
        return None
    short_id = container_short_id(getattr(container, "id", None)) or container_ref
    name = str(getattr(container, "name", "") or "").lstrip("/") or short_id
    return short_id, name


def _fetch_sanitized_logs(
    call: CallbackQuery,
    bot: TeleBot,
    container_ref: str,
    container_name: str,
) -> str | None:
    """Fetch sanitized logs, or tell the user why they cannot be shown."""
    try:
        logs = get_sanitized_logs(container_ref, call, bot.token)
        if logs is not None:
            return logs
        error_text = CONTAINER_NOT_FOUND_TEXT
    except ContainerLogsUnavailableError:
        logger.info(
            "bot.handler.docker.logging.logs.unavailable.info",
            container_name=container_name,
            reason="logging_driver_not_readable",
        )
        error_text = f"{container_name}: {LOGS_UNSUPPORTED_DRIVER_MESSAGE}"
    except ContainerNotFoundError:
        error_text = CONTAINER_NOT_FOUND_TEXT
    except DockerConnectionError:
        error_text = DOCKER_UNAVAILABLE_TEXT
    except InvalidContainerReferenceError:
        error_text = INVALID_CONTAINER_REF_TEXT
    except DockerOperationException:
        error_text = DOCKER_REQUEST_FAILED_TEXT

    show_handler_info(call, text=error_text, bot=bot)
    return None


def _open_logs_session(
    call: CallbackQuery,
    bot: TeleBot,
    container_ref: str,
    user_id: int,
    emojis: dict[str, str],
) -> bool:
    logger.info("bot.handler.docker.logging.user.getting.info")
    container = _resolve_logs_container(call, bot, container_ref)
    if container is None:
        return False
    short_id, container_name = container

    logs = _fetch_sanitized_logs(call, bot, short_id, container_name)
    if logs is None:
        return False

    session = _logs_sessions.create(
        container_ref=short_id,
        container_name=container_name,
        user_id=user_id,
        raw_logs=logs,
        chunks=_build_logs_chunks(logs),
    )
    return _edit_logs_message(
        call=call,
        bot=bot,
        session=session,
        page_index=0,
        emojis=emojis,
    )


def _get_session_or_show_error(
    call: CallbackQuery, session_id: str, bot: TeleBot
) -> LogsSession | None:
    session = _logs_sessions.get(session_id)
    if session is None:
        logger.warning("bot.handler.docker.logging.logs.session.warn")
        show_handler_info(
            call,
            text="This logs session has expired. Open logs again from container details.",
            bot=bot,
        )
    return session


def _send_logs_as_file(call: CallbackQuery, bot: TeleBot, session: LogsSession) -> bool:
    if not _validate_logs_session_access(
        call=call,
        bot=bot,
        session=session,
        requested_action=LOGS_ACTION_FILE,
    ):
        return False

    if call.message is None:
        logger.warning("bot.handler.docker.logging.cannot.send.warn")
        return show_handler_info(
            call,
            text="This logs file can no longer be sent from this message.",
            bot=bot,
        )

    if not session.raw_logs.strip():
        return show_handler_info(
            call,
            text=f"{session.container_name}: No logs are available right now.",
            bot=bot,
        )

    chat_id = call.message.chat.id
    requester_user_id = int(call.from_user.id)
    filename = f"{session.container_name}-logs.txt"
    with io.BytesIO(session.raw_logs.encode("utf-8")) as logs_file:
        logs_file.name = filename
        sent_message = bot.send_document(
            chat_id=chat_id,
            document=logs_file,
            caption=(
                f"Logs file for {session.container_name}\n\n{LOGS_FILE_DELETION_NOTICE}"
            ),
            visible_file_name=filename,
        )

    deletion_result = deletion_manager.schedule_deletion(
        bot=bot,
        chat_id=chat_id,
        message_id=sent_message.message_id,
        user_id=requester_user_id,
        delay_seconds=LOGS_FILE_AUTO_DELETE_DELAY_SECONDS,
        callback=create_post_delete_navigation_callback(
            _logs_file_deletion_callback,
            bot=bot,
            chat_id=chat_id,
            navigation_text=LOGS_FILE_DELETED_NAVIGATION_TEXT,
            nav_keyboard=NAV_DOCKER,
        ),
    )

    callback_text = f"Sent {filename}. Auto-delete in 30s."
    if deletion_result.status == DeletionStatus.LIMIT_EXCEEDED:
        callback_text = f"Sent {filename}. Auto-delete queue is full."
        warning_message = (
            "⚠️ <b>Privacy Notice:</b> Too many pending auto-deletions. "
            "This logs file will not be automatically deleted.\n\n"
            "<i>Please manually delete this file message.</i>"
        )
        send_docker_message(
            bot,
            chat_id=chat_id,
            text=warning_message,
            parse_mode="HTML",
            reply_to_message_id=sent_message.message_id,
        )
        logger.warning("bot.handler.docker.logging.logs.file.warn")
    elif deletion_result.status == DeletionStatus.SCHEDULED:
        logger.info("bot.handler.docker.logging.logs.file.info")
    elif deletion_result.status == DeletionStatus.ALREADY_SCHEDULED:
        logger.warning("bot.handler.docker.logging.logs.file.ok")
    else:
        callback_text = f"Sent {filename}. Delete manually when done."
        logger.error("bot.handler.docker.logging.unexpected.deletion.fail")

    return bot.answer_callback_query(
        callback_query_id=callback_query_id(call), text=callback_text, show_alert=False
    )


def _handle_open(
    call: CallbackQuery,
    bot: TeleBot,
    parsed: ParsedLogsCallback,
    emojis: dict[str, str],
) -> None:
    if parsed.container_ref:
        _open_logs_session(
            call=call,
            bot=bot,
            container_ref=parsed.container_ref,
            user_id=parsed.user_id,
            emojis=emojis,
        )


def _load_owned_session(
    call: CallbackQuery, bot: TeleBot, parsed: ParsedLogsCallback
) -> LogsSession | None:
    if not parsed.session_id:
        return None
    session = _get_session_or_show_error(call, parsed.session_id, bot)
    if session is None:
        return None
    if not _validate_logs_session_access(
        call=call,
        bot=bot,
        session=session,
        requested_action=parsed.action,
    ):
        return None
    return session


def _handle_nav(
    call: CallbackQuery,
    bot: TeleBot,
    parsed: ParsedLogsCallback,
    emojis: dict[str, str],
) -> None:
    session = _load_owned_session(call, bot, parsed)
    if session is not None:
        _edit_logs_message(
            call=call,
            bot=bot,
            session=session,
            page_index=parsed.page_index,
            emojis=emojis,
        )


def _handle_refresh(
    call: CallbackQuery,
    bot: TeleBot,
    parsed: ParsedLogsCallback,
    emojis: dict[str, str],
) -> None:
    old_session = _load_owned_session(call, bot, parsed)
    if old_session is None:
        return
    logs = _fetch_sanitized_logs(
        call, bot, old_session.container_ref, old_session.container_name
    )
    if logs is None:
        return

    _logs_sessions.remove(old_session.session_id)
    refreshed_session = _logs_sessions.create(
        container_ref=old_session.container_ref,
        container_name=old_session.container_name,
        user_id=old_session.user_id,
        raw_logs=logs,
        chunks=_build_logs_chunks(logs),
    )
    _edit_logs_message(
        call=call,
        bot=bot,
        session=refreshed_session,
        page_index=0,
        emojis=emojis,
    )


def _handle_file(
    call: CallbackQuery,
    bot: TeleBot,
    parsed: ParsedLogsCallback,
    emojis: dict[str, str],
) -> None:
    del emojis
    if not parsed.session_id:
        return
    session = _get_session_or_show_error(call, parsed.session_id, bot)
    if session is not None:
        _send_logs_as_file(call=call, bot=bot, session=session)


type _LogsActionHandler = Callable[
    [CallbackQuery, TeleBot, ParsedLogsCallback, dict[str, str]], None
]
_LOGS_ACTION_HANDLERS: Final[dict[str, _LogsActionHandler]] = {
    LOGS_ACTION_OPEN: _handle_open,
    LOGS_ACTION_NAV: _handle_nav,
    LOGS_ACTION_REFRESH: _handle_refresh,
    LOGS_ACTION_FILE: _handle_file,
}


# func=lambda call: call.data.startswith('__get_logs__')
@logger.session_decorator
@two_factor_auth_required
def handle_get_logs(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handles the callback for getting logs of a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        parsed = _parse_logs_callback_data(call.data or "")
    except (ValueError, TypeError):
        logger.warning("bot.handler.docker.logging.invalid.logs.fail")
        show_handler_info(call, text="This logs button is no longer valid.", bot=bot)
        return None

    is_allowed, deny_reason = authorize_docker_callback_request(call, parsed.user_id)
    if not is_allowed:
        logger.warning(
            "bot.handler.docker.logging.user.denied.deny",
            requested_action=parsed.action,
            target_user_id=parsed.user_id,
            reason=deny_reason,
        )
        show_handler_info(call=call, text=f"Getting logs: {deny_reason}", bot=bot)
        return None

    action_handler = _LOGS_ACTION_HANDLERS.get(parsed.action)
    if action_handler is None:
        show_handler_info(call, text="This logs action is not supported.", bot=bot)
        return None

    emojis: dict[str, str] = {"thought_balloon": em.get_emoji("thought_balloon")}
    action_handler(call, bot, parsed, emojis)
    return None
