"""Telegram UI for read-only scans of local Docker image IDs."""

from __future__ import annotations

from typing import Final

from telebot import TeleBot
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from pytmbot.globals import (
    ButtonDataType,
    get_emoji_converter,
    get_keyboards,
    get_session_manager,
    settings,
)
from pytmbot.handlers.handlers_util.rich_messages import (
    screen_updated_at,
    send_rich_main_message,
)
from pytmbot.keyboards.keyboards import reply_button_pattern
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.plugins.trivy.history import HistoryDelta, HistoryError, ScanHistory
from pytmbot.plugins.trivy.runner import (
    ScanError,
    ScanJob,
    ScanQueue,
    ScanSummary,
    local_image_ids,
    resolve_local_id,
)

plugin = PluginCore()
em = get_emoji_converter()
keyboards = get_keyboards()
button_data = ButtonDataType

_CALLBACK_PREFIX: Final[str] = "trivy_scan:"
_BUTTON_LABEL: Final[str] = "Trivy scans"
_NEW_IDS_SHOWN: Final[int] = 8
_SEVERITY_KEYS: Final[tuple[str, ...]] = (
    "CRITICAL",
    "HIGH",
    "MEDIUM",
    "LOW",
    "UNKNOWN",
)
_SEVERITY_LABEL: Final[dict[str, str]] = {
    "CRITICAL": "Critical",
    "HIGH": "High",
    "MEDIUM": "Medium",
    "LOW": "Low",
    "UNKNOWN": "Unknown",
}
_SEVERITY_RANK: Final[dict[str, int]] = {
    key: index for index, key in enumerate(_SEVERITY_KEYS)
}
_TOASTS: Final[dict[str, str]] = {
    "access": "You don't have access to this action.",
    "private": "Open this in a private chat.",
    "session": "Please complete 2FA first.",
    "owner": "This button belongs to another user.",
    "disabled": "Trivy is turned off.",
    "missing": "This image is no longer in the list. Open /trivy again.",
    "unavailable": "Image selection is unavailable. Open /trivy again.",
    "full": "The scan queue is full.",
    "invalid": "Couldn't verify your Telegram account.",
    "queued": "Scan queued",
}


def _gate(user_id: int | None, chat_type: str | None, chat_id: int) -> str | None:
    """Return why this caller cannot see a scan, or None when they can."""
    if user_id is None or user_id not in settings.access_control.allowed_admins_ids:
        return "access"
    if chat_type != "private" or chat_id != user_id:
        return "private"
    if not get_session_manager().is_authenticated(user_id):
        return "session"
    return None


def _short_image_id(image_id: str) -> str:
    return image_id.removeprefix("sha256:")[:12]


def render_notice(
    *,
    icon: str,
    title: str,
    message: str,
    hint: str | None = None,
) -> str:
    """Status screen in the shared notice layout."""
    return Compiler.quick_render(
        template_name="b_notice.jinja2",
        icon=icon,
        title=title,
        message=message,
        hint=hint,
    )


def _notice_for(reason: str) -> str:
    if reason == "private":
        return render_notice(
            icon=em.get_emoji("locked_with_key"),
            title="Private chat",
            message="Open Trivy scans in a private chat with the bot.",
            hint="Scan results are only sent in a private chat.",
        )
    if reason == "session":
        return render_notice(
            icon=em.get_emoji("locked_with_key"),
            title="2FA required",
            message="Please complete 2FA in this private chat, then try again.",
        )
    return render_notice(
        icon=em.get_emoji("no_entry"),
        title="Access denied",
        message="You don't have access to this action.",
    )


def render_menu(*, image_count: int, limit: int) -> str:
    return Compiler.quick_render(
        template_name="plugin_trivy_menu.jinja2",
        image_count=image_count,
        limit=limit,
    )


def render_queued(image_count: int) -> str:
    noun = "scan" if image_count == 1 else "scans"
    return render_notice(
        icon=em.get_emoji("hourglass_not_done"),
        title="Scan queued",
        message=f"{image_count} local image {noun} queued.",
        hint="Results arrive here when each scan finishes. Nothing is pulled or changed.",
    )


def render_failure(image_ref: str) -> str:
    return render_notice(
        icon=em.get_emoji("warning"),
        title="Trivy scan failed",
        message=f"No security result is available for {image_ref}.",
        hint="A failed scan is not a clean image.",
    )


def render_withheld(image_ref: str) -> str:
    return render_notice(
        icon=em.get_emoji("warning"),
        title="Result withheld",
        message=(
            f"The scan of {image_ref} finished, but the private audit record "
            "could not be saved."
        ),
        hint="The report stays hidden until history storage succeeds.",
    )


def _result_rows(summary: ScanSummary) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = [
        {"label": _SEVERITY_LABEL[key], "count": summary.counts.get(key, 0)}
        for key in _SEVERITY_KEYS
    ]
    rows.append({"label": "With a known fix", "count": summary.fixable})
    return rows


def _finding_sort_key(item: tuple[str, str, str]) -> tuple[int, str, str]:
    return (_SEVERITY_RANK.get(item[0], len(_SEVERITY_RANK)), item[1], item[2])


def _finding_rows(summary: ScanSummary) -> list[dict[str, str]]:
    ordered = sorted(summary.findings, key=_finding_sort_key)
    return [
        {
            "severity": _SEVERITY_LABEL.get(severity, severity),
            "identifier": identifier,
            "package": package,
        }
        for severity, identifier, package in ordered
    ]


def _delta_context(
    delta: HistoryDelta | None,
) -> tuple[str, int, tuple[str, ...], int]:
    if delta is None:
        return "none", 0, (), 0
    if not delta.previous:
        return "baseline", 0, (), 0
    shown = delta.new_ids[:_NEW_IDS_SHOWN]
    return "changed", len(delta.new_ids), shown, len(delta.new_ids) - len(shown)


def render_report(summary: ScanSummary, delta: HistoryDelta | None) -> str:
    """Completed scan in the same rich layout as other Docker reports."""
    delta_state, new_count, new_ids, new_more = _delta_context(delta)
    return Compiler.quick_render(
        template_name="plugin_trivy_report.jinja2",
        image_id=_short_image_id(summary.image_id),
        rows=_result_rows(summary),
        findings=_finding_rows(summary),
        delta_state=delta_state,
        new_count=new_count,
        new_ids=list(new_ids),
        new_more=new_more,
        scanned_at=summary.scanned_at,
        db_schema=summary.db_schema,
        db_updated_at=summary.db_updated_at,
        scanner_version=summary.scanner_version,
    )


def render_history(scans: list[ScanSummary], *, listed_at: str) -> str:
    rows = [
        {
            "image_id": _short_image_id(scan.image_id),
            "scanned_at": scan.scanned_at,
            "critical": scan.counts.get("CRITICAL", 0),
            "high": scan.counts.get("HIGH", 0),
        }
        for scan in scans
    ]
    return Compiler.quick_render(
        template_name="plugin_trivy_history.jinja2",
        scans=rows,
        listed_at=listed_at,
    )


def _selection_keyboard(image_ids: list[str], user_id: int) -> InlineKeyboardMarkup:
    """Image targets in the shared inline keyboard, with Scan all on its own row."""
    scan_emoji = em.get_emoji("magnifying_glass_tilted_left")
    buttons = []
    for image_id in image_ids:
        short_id = _short_image_id(image_id)
        buttons.append(
            button_data(
                text=f"{scan_emoji} {short_id}",
                callback_data=f"{_CALLBACK_PREFIX}{short_id}:{user_id}",
            )
        )
    keyboard = keyboards.build_inline_keyboard(buttons)
    all_callback = f"{_CALLBACK_PREFIX}all:{user_id}"
    if keyboards.fits_callback_data_limit(all_callback):
        keyboard.row(
            InlineKeyboardButton(
                text=f"{em.get_emoji('shield')} Scan all",
                callback_data=all_callback,
                style="primary",
            )
        )
    return keyboard


# Dynamically discovered by PluginManager; not referenced by static handlers.
# codeclone: ignore[dead-code]
class TrivyPlugin(PluginInterface):
    """Loaded on request; scanning stays disabled until the config enables it."""

    def __init__(self, bot: TeleBot) -> None:
        super().__init__(bot)
        self.plugin_logger = plugin.logger
        plugins = settings.plugins_config
        self._config = plugins.trivy if plugins else None
        self._queue: ScanQueue | None = None
        self._history: ScanHistory | None = None

    @staticmethod
    def _authorized(user_id: int | None, chat_type: str | None) -> bool:
        chat_id = user_id if chat_type == "private" and user_id is not None else -1
        return _gate(user_id, chat_type, chat_id) is None

    def _reply(self, chat_id: int, text: str) -> None:
        send_rich_main_message(self.bot, chat_id, text)

    def _send_denial(self, chat_id: int, reason: str) -> None:
        self._reply(chat_id, _notice_for(reason))

    def handle_menu(self, message: Message) -> None:
        user = message.from_user
        if user is None:
            self._send_denial(message.chat.id, "access")
            return
        user_id = int(user.id)
        denial = _gate(user_id, message.chat.type, message.chat.id)
        if denial is not None:
            self._send_denial(message.chat.id, denial)
            return
        self.bot.send_chat_action(message.chat.id, "typing")
        config = self._config
        if config is None or not config.enabled or self._queue is None:
            self._reply(
                message.chat.id,
                render_notice(
                    icon=em.get_emoji("warning"),
                    title="Trivy is off",
                    message="Vulnerability scanning is not enabled.",
                    hint="An administrator can enable plugins_config.trivy.",
                ),
            )
            return
        try:
            image_ids = local_image_ids(limit=config.max_images)
        except ScanError as error:
            self.plugin_logger.warning(
                "bot.plugins.trivy.discovery.fail",
                error_type=type(error).__name__,
            )
            self._reply(
                message.chat.id,
                render_notice(
                    icon=em.get_emoji("warning"),
                    title="Couldn't list images",
                    message="Docker image discovery failed.",
                    hint="Check that pyTMBot can reach the Docker socket.",
                ),
            )
            return
        except Exception as error:
            self.plugin_logger.error(
                "bot.plugins.trivy.discovery.unexpected",
                error_type=type(error).__name__,
            )
            self._reply(
                message.chat.id,
                render_notice(
                    icon=em.get_emoji("warning"),
                    title="Couldn't list images",
                    message="Docker image discovery is unavailable.",
                ),
            )
            return
        if not image_ids:
            self._reply(
                message.chat.id,
                render_notice(
                    icon=em.get_emoji("information"),
                    title="No local images",
                    message="No local Docker images were found.",
                ),
            )
            return
        send_rich_main_message(
            self.bot,
            message.chat.id,
            render_menu(image_count=len(image_ids), limit=config.max_images),
            reply_markup=_selection_keyboard(image_ids, user_id),
        )

    def handle_scan(self, call: CallbackQuery) -> None:
        user = call.from_user
        message = call.message
        if user is None or message is None:
            self.bot.answer_callback_query(
                call.id, text=_TOASTS["invalid"], show_alert=True
            )
            return
        user_id = int(user.id)
        if (
            not self._authorized(user_id, message.chat.type)
            or message.chat.id != user_id
        ):
            reason = _gate(user_id, message.chat.type, message.chat.id) or "access"
            self.bot.answer_callback_query(
                call.id, text=_TOASTS[reason], show_alert=True
            )
            return
        data = call.data or ""
        parts = data.split(":")
        if (
            len(parts) != 3
            or parts[0] != "trivy_scan"
            or not parts[2].isascii()
            or not parts[2].isdigit()
            or int(parts[2]) != user_id
        ):
            self.bot.answer_callback_query(
                call.id, text=_TOASTS["owner"], show_alert=True
            )
            return
        config = self._config
        queue = self._queue
        if config is None or not config.enabled or queue is None:
            self.bot.answer_callback_query(
                call.id, text=_TOASTS["disabled"], show_alert=True
            )
            return
        try:
            if parts[1] == "all":
                image_ids = tuple(local_image_ids(limit=config.max_images))
            else:
                image_ids = (resolve_local_id(parts[1], limit=config.max_images),)
            if not image_ids:
                raise ScanError("No images found.")
        except ScanError as error:
            self.plugin_logger.warning(
                "bot.plugins.trivy.selection.fail",
                error_type=type(error).__name__,
            )
            self.bot.answer_callback_query(
                call.id, text=_TOASTS["missing"], show_alert=True
            )
            return
        except Exception as error:
            self.plugin_logger.error(
                "bot.plugins.trivy.selection.unexpected",
                error_type=type(error).__name__,
            )
            self.bot.answer_callback_query(
                call.id, text=_TOASTS["unavailable"], show_alert=True
            )
            return
        job = ScanJob(chat_id=message.chat.id, user_id=user_id, image_ids=image_ids)
        if not queue.submit(job):
            self.bot.answer_callback_query(
                call.id, text=_TOASTS["full"], show_alert=True
            )
            return
        self.bot.answer_callback_query(call.id, text=_TOASTS["queued"])
        self._reply(message.chat.id, render_queued(len(image_ids)))

    def handle_history(self, message: Message) -> None:
        """Show recent completed scans only to authenticated admins."""
        user = message.from_user
        user_id = int(user.id) if user else None
        denial = _gate(user_id, message.chat.type, message.chat.id)
        if denial is not None:
            self._send_denial(message.chat.id, denial)
            return
        history = self._history
        if history is None:
            self._reply(
                message.chat.id,
                render_notice(
                    icon=em.get_emoji("information"),
                    title="History is off",
                    message="Persistent scan history is not configured.",
                    hint="Set plugins_config.trivy.history_file to keep scan records.",
                ),
            )
            return
        self.bot.send_chat_action(message.chat.id, "typing")
        try:
            recent = history.recent()
        except HistoryError:
            self._reply(
                message.chat.id,
                render_notice(
                    icon=em.get_emoji("warning"),
                    title="History unavailable",
                    message="Scan history can't be read right now.",
                ),
            )
            return
        if not recent:
            self._reply(
                message.chat.id,
                render_notice(
                    icon=em.get_emoji("information"),
                    title="No scans yet",
                    message="No completed Trivy scans are stored.",
                ),
            )
            return
        self._reply(
            message.chat.id,
            render_history(recent, listed_at=screen_updated_at()),
        )

    def _image_ref(self, job: ScanJob, summary: ScanSummary | None) -> str:
        if summary is not None:
            return _short_image_id(summary.image_id)
        if job.image_ids:
            return _short_image_id(job.image_ids[0])
        return "unknown"

    def _publish(self, job: ScanJob, status: str, summary: ScanSummary | None) -> None:
        # Recheck admin status before publishing a background result.
        if job.chat_id != job.user_id or not self._authorized(job.user_id, "private"):
            return
        image_ref = self._image_ref(job, summary)
        if status != "complete" or summary is None:
            content = render_failure(image_ref)
        else:
            content = self._completed_report(summary, image_ref)
        try:
            self._reply(job.chat_id, content)
        except Exception as error:
            # Do not allow a Telegram delivery failure to terminate the worker.
            self.plugin_logger.warning(
                "bot.plugins.trivy.publish.fail",
                error_type=type(error).__name__,
            )

    def _completed_report(self, summary: ScanSummary, image_ref: str) -> str:
        delta: HistoryDelta | None = None
        if self._history is not None:
            try:
                delta = self._history.append(summary)
            except HistoryError as error:
                self.plugin_logger.error(
                    "bot.plugins.trivy.history.append.fail",
                    error_type=type(error).__name__,
                )
                return render_withheld(image_ref)
        return render_report(summary, delta)

    def register(self) -> None:
        config = self._config
        if config is not None and config.enabled:
            if config.history_file is not None:
                self._history = ScanHistory(config.history_file)
            self._queue = ScanQueue(config, self._publish)
        # Register the UI even when disabled: the plugin manager already exposes
        # the plugin button, so the handlers must answer instead of going dead.
        self.bot.register_message_handler(self.handle_menu, commands=["trivy"])
        self.bot.register_message_handler(
            self.handle_menu, regexp=reply_button_pattern(_BUTTON_LABEL)
        )
        self.bot.register_message_handler(
            self.handle_history, commands=["trivy_history"]
        )
        self.bot.register_callback_query_handler(
            self.handle_scan,
            func=lambda call: bool(
                isinstance(call.data, str) and call.data.startswith(_CALLBACK_PREFIX)
            ),
        )

    def cleanup(self) -> None:
        if self._queue is not None:
            self._queue.cleanup()
            self._queue = None
