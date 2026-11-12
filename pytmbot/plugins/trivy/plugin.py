"""Telegram UI for read-only scans of local Docker image IDs."""

from __future__ import annotations

from html import escape
from typing import Final

from telebot import TeleBot
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from pytmbot.globals import get_session_manager, settings
from pytmbot.handlers.handlers_util.rich_messages import send_rich_main_message
from pytmbot.keyboards.keyboards import reply_button_pattern
from pytmbot.logs import Logger
from pytmbot.models.settings_model import TrivyConfig
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.trivy.history import HistoryError, ScanHistory
from pytmbot.plugins.trivy.runner import (
    ScanError,
    ScanJob,
    ScanQueue,
    ScanSummary,
    local_image_ids,
    resolve_local_id,
)

_CALLBACK_PREFIX: Final[str] = "trivy_scan:"
_BUTTON_LABEL: Final[str] = "Trivy scans"


# Dynamically discovered by PluginManager; not referenced by static handlers.
# codeclone: ignore[dead-code]
class TrivyPlugin(PluginInterface):
    """Only registered when explicitly enabled and configured."""

    def __init__(self, bot: TeleBot) -> None:
        super().__init__(bot)
        self.plugin_logger = Logger()
        plugins = settings.plugins_config
        self._config: TrivyConfig | None = plugins.trivy if plugins else None
        self._queue: ScanQueue | None = None
        self._history: ScanHistory | None = None

    @staticmethod
    def _authorized(user_id: int | None, chat_type: str | None) -> bool:
        return bool(
            user_id is not None
            and chat_type == "private"
            and user_id in settings.access_control.allowed_admins_ids
            and get_session_manager().is_authenticated(user_id)
        )

    def _reply(self, chat_id: int, text: str) -> None:
        send_rich_main_message(self.bot, chat_id, text)

    @staticmethod
    def _button(ref: str, user_id: int, label: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=label[:64], callback_data=f"{_CALLBACK_PREFIX}{ref}:{user_id}"
        )

    def handle_menu(self, message: Message) -> None:
        user = message.from_user
        user_id = int(user.id) if user else None
        if message.chat.type != "private":
            self._reply(message.chat.id, "<p>Open Trivy scans in a private chat.</p>")
            return
        if user_id is None:
            return
        if not self._authorized(user_id, message.chat.type):
            self._reply(
                message.chat.id,
                "<p>Admin access and a verified 2FA session are required.</p>",
            )
            return
        config = self._config
        if config is None or not config.enabled or self._queue is None:
            self._reply(message.chat.id, "<p>Trivy scanning is not enabled.</p>")
            return
        try:
            image_ids = local_image_ids(limit=config.max_images)
        except ScanError as error:
            self.plugin_logger.warning(
                "bot.plugins.trivy.discovery.fail",
                error_type=type(error).__name__,
            )
            self._reply(message.chat.id, "<p>Docker image discovery failed.</p>")
            return
        except Exception as error:
            self.plugin_logger.error(
                "bot.plugins.trivy.discovery.unexpected",
                error_type=type(error).__name__,
            )
            self._reply(
                message.chat.id, "<p>Docker image discovery is unavailable.</p>"
            )
            return
        if not image_ids:
            self._reply(message.chat.id, "<p>No local Docker images were found.</p>")
            return
        keyboard = InlineKeyboardMarkup(row_width=1)
        for image_id in image_ids:
            keyboard.add(self._button(image_id[:12], user_id, f"Scan {image_id[:12]}"))
        keyboard.add(self._button("all", user_id, "Scan all listed images"))
        send_rich_main_message(
            self.bot,
            message.chat.id,
            "<p><b>Trivy — local image scan</b></p>"
            "<p>Read-only vulnerability assessment. No image pull or remediation.</p>"
            f"<p>{len(image_ids)} verified local images (limit "
            f"{config.max_images}). Select a target:</p>",
            reply_markup=keyboard,
        )

    def handle_scan(self, call: CallbackQuery) -> None:
        user = call.from_user
        message = call.message
        if user is None or message is None:
            self.bot.answer_callback_query(
                call.id, text="Invalid scan request.", show_alert=True
            )
            return
        user_id = int(user.id)
        if (
            not self._authorized(user_id, message.chat.type)
            or message.chat.id != user_id
        ):
            self.bot.answer_callback_query(
                call.id, text="Admin 2FA required.", show_alert=True
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
                call.id, text="This scan button is not yours.", show_alert=True
            )
            return
        config = self._config
        queue = self._queue
        if config is None or not config.enabled or queue is None:
            self.bot.answer_callback_query(
                call.id, text="Trivy is disabled.", show_alert=True
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
                call.id,
                text="Image selection expired. Refresh /trivy.",
                show_alert=True,
            )
            return
        except Exception as error:
            self.plugin_logger.error(
                "bot.plugins.trivy.selection.unexpected",
                error_type=type(error).__name__,
            )
            self.bot.answer_callback_query(
                call.id,
                text="Image selection is unavailable. Refresh /trivy.",
                show_alert=True,
            )
            return
        job = ScanJob(chat_id=message.chat.id, user_id=user_id, image_ids=image_ids)
        if not queue.submit(job):
            self.bot.answer_callback_query(
                call.id, text="Scan queue is full.", show_alert=True
            )
            return
        self.bot.answer_callback_query(call.id, text="Scan queued.")
        self._reply(
            message.chat.id, f"<p>Queued {len(image_ids)} local image scan(s).</p>"
        )

    def handle_history(self, message: Message) -> None:
        """Show recent completed scans only to authenticated admins."""
        user = message.from_user
        user_id = int(user.id) if user else None
        if (
            not self._authorized(user_id, message.chat.type)
            or message.chat.id != user_id
        ):
            self._reply(message.chat.id, "<p>Admin access and 2FA are required.</p>")
            return
        history = self._history
        if history is None:
            self._reply(
                message.chat.id, "<p>Persistent scan history is not configured.</p>"
            )
            return
        try:
            recent = history.recent()
        except HistoryError:
            self._reply(
                message.chat.id, "<p>Scan history is currently unavailable.</p>"
            )
            return
        if not recent:
            self._reply(message.chat.id, "<p>No completed Trivy scans yet.</p>")
            return
        entries = "".join(
            f"<li>{escape(scan.scanned_at[:19])}: "
            f"{escape(scan.image_id[:12])} — "
            f"{scan.counts.get('CRITICAL', 0)} critical, "
            f"{scan.counts.get('HIGH', 0)} high</li>"
            for scan in recent
        )
        self._reply(
            message.chat.id,
            f"<p><b>Recent vulnerability scans</b></p><ul>{entries}</ul>",
        )

    def _publish(self, job: ScanJob, status: str, summary: ScanSummary | None) -> None:
        # Recheck admin status before publishing a background result.
        if job.chat_id != job.user_id or not self._authorized(job.user_id, "private"):
            return
        if status != "complete" or summary is None:
            self._reply(
                job.chat_id,
                "<p>Trivy scan failed. No security result is available.</p>",
            )
            return
        delta_html = ""
        if self._history is not None:
            try:
                delta = self._history.append(summary)
            except HistoryError as error:
                self.plugin_logger.error(
                    "bot.plugins.trivy.history.append.fail",
                    error_type=type(error).__name__,
                )
                self._reply(
                    job.chat_id,
                    "<p>Scan completed but audit storage failed; results are withheld.</p>",
                )
                return
            if delta.previous:
                delta_html = f"<p>New vulnerability IDs since previous scan: {len(delta.new_ids)}</p>"
                if delta.new_ids:
                    delta_html += (
                        "<p>"
                        + ", ".join(escape(item) for item in delta.new_ids[:5])
                        + "</p>"
                    )
            else:
                delta_html = "<p>First scan recorded as baseline.</p>"
        counts = summary.counts
        details = "".join(
            f"<li>{escape(severity)}: {escape(identifier)} — {escape(package)}</li>"
            for severity, identifier, package in summary.findings
        )
        if details:
            details = f"<p><b>Selected high-severity findings</b></p><ul>{details}</ul>"
        content = (
            "<p><b>Trivy vulnerability scan completed</b></p>"
            f"<p><b>Image:</b> sha256:{escape(summary.image_id[:16])}…</p>"
            f"<p><b>Scanned:</b> {escape(summary.scanned_at)}</p>"
            f"<p><b>DB:</b> schema {summary.db_schema}, updated {escape(summary.db_updated_at)}</p>"
            f"<p><b>Trivy:</b> {escape(summary.scanner_version[:48])}</p>"
            f"<p>Critical: {counts['CRITICAL']} · High: {counts['HIGH']} · "
            f"Medium: {counts['MEDIUM']} · Low: {counts['LOW']} · "
            f"Unknown: {counts['UNKNOWN']}</p>"
            f"<p>Findings with known fixed versions: {summary.fixable}</p>"
            f"{delta_html}{details}"
            "<p><i>Known CVEs are not proof of exploitability. "
            "The scan used the operator-managed local Trivy DB.</i></p>"
        )
        try:
            self._reply(job.chat_id, content)
        except Exception as error:
            # Do not allow a Telegram delivery failure to terminate the worker.
            self.plugin_logger.warning(
                "bot.plugins.trivy.publish.fail",
                error_type=type(error).__name__,
            )
            return

    def register(self) -> None:
        config = self._config
        if config is None or not config.enabled:
            return
        if config.history_file is not None:
            self._history = ScanHistory(config.history_file)
        self._queue = ScanQueue(config, self._publish)
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
