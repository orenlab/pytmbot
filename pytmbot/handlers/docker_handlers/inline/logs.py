#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import hashlib
import io
import time
from dataclasses import dataclass
from threading import RLock
from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import button_data, em, keyboards
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    get_sanitized_logs,
    show_handler_info,
)
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler

logger = Logger()

MAX_TELEGRAM_MESSAGE_LENGTH: Final[int] = 4096
MAX_LOGS_PAGE_CHARS: Final[int] = 3200
LOGS_SESSION_TTL_SECONDS: Final[int] = 300
LOGS_CALLBACK_PREFIX: Final[str] = "__get_logs__"
LOGS_ACTION_OPEN: Final[str] = "open"
LOGS_ACTION_NAV: Final[str] = "nav"
LOGS_ACTION_REFRESH: Final[str] = "refresh"
LOGS_ACTION_FILE: Final[str] = "file"
LOGS_TRUNCATION_NOTICE: Final[str] = "[LOGS TRUNCATED FOR TELEGRAM LENGTH LIMIT]\n"
LOGS_EMPTY_MESSAGE: Final[str] = "No logs available for this container."


@dataclass(frozen=True, slots=True)
class ParsedLogsCallback:
    action: str
    user_id: int
    container_name: str | None = None
    session_id: str | None = None
    page_index: int = 0


@dataclass(slots=True)
class LogsSession:
    session_id: str
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
    def _generate_session_id(container_name: str, user_id: int) -> str:
        seed = f"{container_name}:{user_id}:{time.time_ns()}"
        return hashlib.blake2s(seed.encode(), digest_size=6).hexdigest()

    def create(
        self,
        container_name: str,
        user_id: int,
        raw_logs: str,
        chunks: list[str],
    ) -> LogsSession:
        now = time.time()
        with self._lock:
            self._cleanup_expired_unlocked(now)

            session_id = self._generate_session_id(container_name, user_id)
            while session_id in self._sessions:
                session_id = self._generate_session_id(container_name, user_id)

            session = LogsSession(
                session_id=session_id,
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


def _render_logs_template(
    logs: str, container_name: str, emojis: dict[str, str]
) -> str:
    """Render logs template with provided context."""
    return Compiler.quick_render("d_logs.jinja2", emojis=emojis, logs=logs, container_name=container_name)


def _parse_logs_callback_data(callback_data: str) -> ParsedLogsCallback:
    """
    Parse callback data for logs actions.

    Supported:
    - Legacy: __get_logs__:<container_name>:<user_id>
    - New: __get_logs__:open:<container_name>:<user_id>
    - New: __get_logs__:nav:<session_id>:<page_index>:<user_id>
    - New: __get_logs__:refresh:<session_id>:<user_id>
    - New: __get_logs__:file:<session_id>:<user_id>
    """
    parts = callback_data.split(":")
    if not parts or parts[0] != LOGS_CALLBACK_PREFIX:
        raise ValueError("Invalid logs callback prefix")

    # Backward-compatible format.
    if len(parts) == 3 and parts[1] not in {
        LOGS_ACTION_OPEN,
        LOGS_ACTION_NAV,
        LOGS_ACTION_REFRESH,
        LOGS_ACTION_FILE,
    }:
        return ParsedLogsCallback(
            action=LOGS_ACTION_OPEN,
            container_name=parts[1],
            user_id=int(parts[2]),
        )

    if len(parts) == 4 and parts[1] == LOGS_ACTION_OPEN:
        return ParsedLogsCallback(
            action=LOGS_ACTION_OPEN,
            container_name=parts[2],
            user_id=int(parts[3]),
        )

    if len(parts) == 5 and parts[1] == LOGS_ACTION_NAV:
        return ParsedLogsCallback(
            action=LOGS_ACTION_NAV,
            session_id=parts[2],
            page_index=int(parts[3]),
            user_id=int(parts[4]),
        )

    if len(parts) == 4 and parts[1] in {LOGS_ACTION_REFRESH, LOGS_ACTION_FILE}:
        return ParsedLogsCallback(
            action=parts[1],
            session_id=parts[2],
            user_id=int(parts[3]),
        )

    raise ValueError("Unsupported logs callback format")


def _build_logs_chunks(logs: str, max_chunk_chars: int = MAX_LOGS_PAGE_CHARS) -> list[str]:
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
):
    """Build logs keyboard with navigation and actions."""
    keyboard_buttons = []

    if current_page > 0:
        keyboard_buttons.append(
            button_data(
                text="Newer",
                callback_data=(
                    f"{LOGS_CALLBACK_PREFIX}:{LOGS_ACTION_NAV}:"
                    f"{session.session_id}:{current_page - 1}:{session.user_id}"
                ),
            )
        )

    if current_page < total_pages - 1:
        keyboard_buttons.append(
            button_data(
                text="Older",
                callback_data=(
                    f"{LOGS_CALLBACK_PREFIX}:{LOGS_ACTION_NAV}:"
                    f"{session.session_id}:{current_page + 1}:{session.user_id}"
                ),
            )
        )

    keyboard_buttons.extend(
        [
            button_data(
                text="Refresh",
                callback_data=(
                    f"{LOGS_CALLBACK_PREFIX}:{LOGS_ACTION_REFRESH}:"
                    f"{session.session_id}:{session.user_id}"
                ),
            ),
            button_data(
                text="As file",
                callback_data=(
                    f"{LOGS_CALLBACK_PREFIX}:{LOGS_ACTION_FILE}:"
                    f"{session.session_id}:{session.user_id}"
                ),
            ),
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Back to {session.container_name} info",
                callback_data=f"__get_full__:{session.container_name}:{session.user_id}",
            ),
            button_data(
                text=f"{em.get_emoji('house')} Back to all containers",
                callback_data="back_to_containers",
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
):
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
        f"Successfully compiled logs for container {session.container_name}",
        page=f"{safe_page_index + 1}/{total_pages}",
        message_length=len(context),
        logs_truncated_for_telegram=was_truncated,
    )

    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
    )


def _open_logs_session(
    call: CallbackQuery,
    bot: TeleBot,
    container_name: str,
    user_id: int,
    emojis: dict[str, str],
):
    logger.info(f"User {call.from_user.id}: Getting logs for container {container_name}")
    logs = get_sanitized_logs(container_name, call, bot.token)

    if not logs:
        logger.error(f"Error getting logs for container {container_name}")
        return show_handler_info(call, text=f"{container_name}: Error getting logs", bot=bot)

    session = _logs_sessions.create(
        container_name=container_name,
        user_id=user_id,
        raw_logs=logs,
        chunks=_build_logs_chunks(logs),
    )
    return _edit_logs_message(call=call, bot=bot, session=session, page_index=0, emojis=emojis)


def _get_session_or_show_error(call: CallbackQuery, session_id: str, bot: TeleBot):
    session = _logs_sessions.get(session_id)
    if session is None:
        logger.warning(f"Logs session expired or not found: {session_id}")
        show_handler_info(
            call,
            text="Logs session expired. Open logs again from container info.",
            bot=bot,
        )
    return session


def _send_logs_as_file(call: CallbackQuery, bot: TeleBot, session: LogsSession):
    if not session.raw_logs.strip():
        return show_handler_info(
            call, text=f"{session.container_name}: No logs available", bot=bot
        )

    filename = f"{session.container_name}-logs.txt"
    with io.BytesIO(session.raw_logs.encode("utf-8")) as logs_file:
        logs_file.name = filename
        bot.send_document(
            chat_id=call.message.chat.id,
            document=logs_file,
            caption=f"Logs file for {session.container_name}",
            visible_file_name=filename,
        )

    return bot.answer_callback_query(
        callback_query_id=call.id, text=f"Sent {filename}", show_alert=False
    )


# func=lambda call: call.data.startswith('__get_logs__')
@logger.session_decorator
@two_factor_auth_required
def handle_get_logs(call: CallbackQuery, bot: TeleBot):
    """
    Handles the callback for getting logs of a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        parsed = _parse_logs_callback_data(call.data)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid logs callback format: '{call.data}', error: {e}")
        return show_handler_info(call, text="Invalid logs request format", bot=bot)

    is_allowed, deny_reason = authorize_docker_callback_request(call, parsed.user_id)
    if not is_allowed:
        current_user_id = call.from_user.id if call.from_user else "unknown"
        logger.warning(
            f"User {current_user_id}: Denied '__get_logs__' function",
            requested_action=parsed.action,
            target_user_id=parsed.user_id,
            reason=deny_reason,
        )
        return show_handler_info(
            call=call, text=f"Getting logs: {deny_reason}", bot=bot
        )

    emojis: dict[str, str] = {"thought_balloon": em.get_emoji("thought_balloon")}

    if parsed.action == LOGS_ACTION_OPEN and parsed.container_name:
        return _open_logs_session(
            call=call,
            bot=bot,
            container_name=parsed.container_name,
            user_id=parsed.user_id,
            emojis=emojis,
        )

    if parsed.action == LOGS_ACTION_NAV and parsed.session_id:
        session = _get_session_or_show_error(call, parsed.session_id, bot)
        if not session:
            return None
        return _edit_logs_message(
            call=call,
            bot=bot,
            session=session,
            page_index=parsed.page_index,
            emojis=emojis,
        )

    if parsed.action == LOGS_ACTION_REFRESH and parsed.session_id:
        old_session = _get_session_or_show_error(call, parsed.session_id, bot)
        if not old_session:
            return None

        logs = get_sanitized_logs(old_session.container_name, call, bot.token)
        if not logs:
            logger.error(f"Error getting logs for container {old_session.container_name}")
            return show_handler_info(
                call,
                text=f"{old_session.container_name}: Error getting logs",
                bot=bot,
            )

        _logs_sessions.remove(parsed.session_id)
        refreshed_session = _logs_sessions.create(
            container_name=old_session.container_name,
            user_id=old_session.user_id,
            raw_logs=logs,
            chunks=_build_logs_chunks(logs),
        )
        return _edit_logs_message(
            call=call,
            bot=bot,
            session=refreshed_session,
            page_index=0,
            emojis=emojis,
        )

    if parsed.action == LOGS_ACTION_FILE and parsed.session_id:
        session = _get_session_or_show_error(call, parsed.session_id, bot)
        if not session:
            return None
        return _send_logs_as_file(call=call, bot=bot, session=session)

    return show_handler_info(call, text="Unsupported logs action", bot=bot)
