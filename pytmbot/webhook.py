#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import ipaddress
import json
import os
import tempfile
import threading
from collections import deque
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from time import time
from typing import Annotated, Final

import telebot
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from pytmbot.exceptions import BotException, ErrorContext, InitializationError
from pytmbot.globals import __version__ as app_version
from pytmbot.globals import settings
from pytmbot.logs import BaseComponent
from pytmbot.models.settings_model import WebhookConfig as SettingsWebhookConfig
from pytmbot.models.telegram_models import TelegramIPValidator
from pytmbot.models.updates_model import UpdateModel
from pytmbot.utils import (
    generate_secret_token,
    mask_ip_address,
    mask_token_in_message,
    mask_webhook_path,
)

RATELIMIT_EXCEEDED_MESSAGE = "Rate limit exceeded"
BAN_TTL_SECONDS = 3600
SSL_PLACEHOLDER_VALUES: Final[frozenset[str]] = frozenset(
    {"YOUR_CERTIFICATE", "YOUR_CERTIFICATE_KEY"}
)

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


def _get_webhook_config() -> SettingsWebhookConfig:
    """Get webhook config and fail fast with typed error when it's unavailable."""
    webhook_config = settings.webhook_config
    if webhook_config is None:
        raise InitializationError(
            ErrorContext(
                message="Webhook configuration is missing",
                error_code="WEBHOOK_CONFIG_MISSING",
                metadata={},
            )
        )
    return webhook_config


def _first_secret(values: list[SecretStr] | None) -> str | None:
    """Safely extract first secret value from optional secret list."""
    if not values:
        return None
    secret_value = values[0].get_secret_value().strip()
    return secret_value or None


def _normalize_ssl_path(path: str | None) -> str | None:
    """Treat empty and placeholder SSL values as missing."""
    if path is None:
        return None
    normalized = path.strip()
    if not normalized or normalized in SSL_PLACEHOLDER_VALUES:
        return None
    return normalized


class RateLimit(BaseComponent):
    __slots__ = (
        "limit",
        "period",
        "ban_threshold",
        "requests",
        "banned_ips",
        "_last_seen",
        "max_tracked_ips",
        "_last_cleanup_ts",
        "_state_lock",
        "_state_file",
        "_state_loaded",
        "_last_state_persist_ts",
        "_ban_ttl_seconds",
    )

    def __init__(
        self,
        limit: int,
        period: int,
        ban_threshold: int = 50,
        max_tracked_ips: int = 4096,
        state_file: str | None = None,
    ) -> None:
        super().__init__()

        with self.log_context(
            limit=limit,
            period=period,
            ban_threshold=ban_threshold,
            max_tracked_ips=max_tracked_ips,
        ) as log:
            log.debug("bot.webhook.rate.limiter.init")
            self.limit = limit
            self.period = period
            self.ban_threshold = ban_threshold
            self.requests: dict[str, deque[float]] = {}
            self.banned_ips: dict[str, datetime] = {}
            self._last_seen: dict[str, float] = {}
            self.max_tracked_ips = max(128, max_tracked_ips)
            self._last_cleanup_ts = 0.0
            self._state_lock = threading.RLock()
            self._state_file = self._prepare_state_file(state_file)
            self._state_loaded = False
            self._last_state_persist_ts = 0.0
            self._ban_ttl_seconds = BAN_TTL_SECONDS

    def _prepare_state_file(self, state_file: str | None) -> str | None:
        """Ensure state persistence directory is private to current user."""
        if not state_file:
            return None

        state_path = os.path.abspath(state_file)
        state_dir = os.path.dirname(state_path)
        try:
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            os.chmod(state_dir, 0o700)
            return state_path
        except OSError as error:
            with self.log_context(
                action="prepare_state_file",
                state_file=state_path,
                error=str(error),
                error_type=type(error).__name__,
            ) as log:
                log.warning("bot.webhook.state.file.prepare.fail.warn")
            return None

    def _ensure_state_loaded(self) -> None:
        """Lazily restore persisted state on first access."""
        if self._state_loaded:
            return
        self._restore_state()
        self._state_loaded = True

    def _restore_state(self) -> None:
        """Load persisted bans from disk if available."""
        if not self._state_file:
            return

        try:
            with open(self._state_file, encoding="utf-8") as state_stream:
                payload = json.load(state_stream)
        except FileNotFoundError:
            return
        except Exception as error:
            with self.log_context(
                action="restore_state",
                state_file=self._state_file,
                error=str(error),
                error_type=type(error).__name__,
            ) as log:
                log.warning("bot.webhook.state.restore.fail.warn")
            return

        if not isinstance(payload, dict):
            return

        now = datetime.now()
        restored_bans = payload.get("banned_ips", {})
        if not isinstance(restored_bans, dict):
            return

        for ip, iso_banned_at in restored_bans.items():
            if not isinstance(ip, str) or not isinstance(iso_banned_at, str):
                continue
            try:
                banned_at = datetime.fromisoformat(iso_banned_at)
            except ValueError:
                continue
            if (now - banned_at).total_seconds() <= self._ban_ttl_seconds:
                self.banned_ips[ip] = banned_at
                self._last_seen[ip] = time()

    def _persist_state(self, *, force: bool = False) -> None:
        """Persist current ban state to disk."""
        if not self._state_file:
            return

        now_ts = time()
        if not force and now_ts - self._last_state_persist_ts < 5.0:
            return

        self._last_state_persist_ts = now_ts
        payload = {
            "banned_ips": {
                ip: banned_at.isoformat() for ip, banned_at in self.banned_ips.items()
            },
            "saved_at": datetime.now().isoformat(),
        }
        state_dir = os.path.dirname(self._state_file)
        tmp_state_path: str | None = None
        try:
            fd, tmp_state_path = tempfile.mkstemp(
                prefix=".pytmbot_ratelimit_",
                suffix=".tmp",
                dir=state_dir,
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as state_stream:
                json.dump(payload, state_stream)
            os.chmod(tmp_state_path, 0o600)
            os.replace(tmp_state_path, self._state_file)
        except Exception as error:
            if tmp_state_path and os.path.exists(tmp_state_path):
                try:
                    os.unlink(tmp_state_path)
                except OSError:
                    pass
            with self.log_context(
                action="persist_state",
                state_file=self._state_file,
                error=str(error),
                error_type=type(error).__name__,
            ) as log:
                log.warning("bot.webhook.state.persist.fail.warn")

    def _drop_ip_state(self, client_ip: str) -> None:
        """Remove all in-memory state for an IP."""
        self.requests.pop(client_ip, None)
        self.banned_ips.pop(client_ip, None)
        self._last_seen.pop(client_ip, None)

    def _evict_oldest_ip(self) -> None:
        """Evict least recently seen IP to keep memory bounded."""
        if not self._last_seen:
            return
        oldest_ip = min(self._last_seen, key=lambda ip: self._last_seen[ip])
        self._drop_ip_state(oldest_ip)

    def _cleanup_state(self, current_time: float) -> None:
        """
        Cleanup stale in-memory state.

        Runs at most once per minute unless cache is above hard limit.
        """
        should_cleanup_now = current_time - self._last_cleanup_ts >= 60.0
        if not should_cleanup_now and len(self._last_seen) <= self.max_tracked_ips:
            return

        self._last_cleanup_ts = current_time
        now = datetime.now()
        expired_bans = [
            ip
            for ip, banned_at in self.banned_ips.items()
            if (now - banned_at).total_seconds() > self._ban_ttl_seconds
        ]
        for ip in expired_bans:
            self.banned_ips.pop(ip, None)

        stale_ips = [
            ip
            for ip, request_times in self.requests.items()
            if not request_times and ip not in self.banned_ips
        ]
        for ip in stale_ips:
            self._drop_ip_state(ip)

        while len(self._last_seen) > self.max_tracked_ips:
            self._evict_oldest_ip()

        if expired_bans or stale_ips:
            self._persist_state()

    def is_banned(self, client_ip: str) -> bool:
        with self._state_lock:
            self._ensure_state_loaded()
            self._cleanup_state(time())
            with self.log_context(ip=client_ip, action="check_ban"):
                if client_ip not in self.banned_ips:
                    return False

                ban_time = self.banned_ips[client_ip]
                if (datetime.now() - ban_time).total_seconds() > self._ban_ttl_seconds:
                    with self.log_context(action="ban_expired", ip=client_ip) as log:
                        log.info("bot.webhook.ban.expired.info")
                    del self.banned_ips[client_ip]
                    self._persist_state()
                    return False
                with self.log_context(action="banned", ip=client_ip) as log:
                    log.warning("bot.webhook.request.banned.warn")
                return True

    def is_rate_limited(self, client_ip: str) -> bool:
        with self._state_lock:
            self._ensure_state_loaded()
            current_time = time()
            self._cleanup_state(current_time)

            if (
                client_ip not in self.requests
                and client_ip not in self._last_seen
                and len(self._last_seen) >= self.max_tracked_ips
            ):
                self._evict_oldest_ip()
            self._last_seen[client_ip] = current_time

            with self.log_context(
                ip=client_ip,
                action="rate_check",
                requests_count=len(self.requests.get(client_ip, [])),
            ):
                if self.is_banned(client_ip):
                    return True

                if client_ip not in self.requests:
                    self.requests[client_ip] = deque()

                request_times = self.requests[client_ip]

                while request_times and request_times[0] < current_time - self.period:
                    request_times.popleft()

                if len(request_times) >= self.ban_threshold:
                    self.banned_ips[client_ip] = datetime.now()
                    self._persist_state()
                    with self.log_context(action="ban_ip", ip=client_ip) as log:
                        log.warning("bot.webhook.ip.banned.warn")
                    return True

                if len(request_times) >= self.limit:
                    with self.log_context(action="rate_limit", ip=client_ip) as log:
                        log.warning("bot.webhook.rate.limit.warn")
                    return True

                request_times.append(current_time)
                return False


class WebhookManager(BaseComponent):
    __slots__ = ("bot", "url", "port", "secret_token")

    def __init__(
        self, bot: TeleBot, url: str, port: int, secret_token: str | None = None
    ) -> None:
        super().__init__("webhook_manager")
        self.bot = bot
        self.url = url
        self.port = port
        self.secret_token = secret_token

        with self.log_context(
            webhook_url=mask_token_in_message(url, bot.token),
            port=port,
            has_secret_token=bool(secret_token),
        ) as log:
            log.debug("bot.webhook.manager.init")

    def setup_webhook(
        self,
        webhook_path: str,
        *,
        secret_token: str | None = None,
        drop_pending_updates: bool = True,
        reset_existing: bool = True,
    ) -> None:
        webhook_url = f"https://{self.url}:{self.port}{webhook_path}"
        webhook_settings = _get_webhook_config()
        cert_path = _normalize_ssl_path(_first_secret(webhook_settings.cert))
        if secret_token is not None:
            self.secret_token = secret_token

        with self.log_context(
            action="setup_webhook",
            webhook_path=mask_webhook_path(webhook_path),
            drop_pending_updates=drop_pending_updates,
            reset_existing=reset_existing,
        ) as log:
            try:
                current_webhook = self.bot.get_webhook_info()
                log.debug(
                    "bot.webhook.config.debug",
                    webhook_info=mask_webhook_path(
                        mask_token_in_message(str(current_webhook), self.bot.token)
                    ),
                    cert_present=bool(cert_path),
                )

                if reset_existing:
                    self.remove_webhook()

                self.bot.set_webhook(
                    url=webhook_url,
                    timeout=20,
                    allowed_updates=[
                        "message",
                        "edited_message",
                        "inline_query",
                        "callback_query",
                    ],
                    drop_pending_updates=drop_pending_updates,
                    certificate=cert_path,
                    secret_token=self.secret_token,
                )

                new_webhook = self.bot.get_webhook_info()
                log.info(
                    "bot.webhook.config.ok",
                    new_webhook=mask_webhook_path(
                        mask_token_in_message(str(new_webhook), self.bot.token)
                    ),
                )

            except ApiTelegramException as e:
                error_context = ErrorContext(
                    message="Webhook setup failed",
                    error_code="WEBHOOK_SETUP_FAILED",
                    metadata={"exception": str(e)},
                )
                log.exception("bot.webhook.init.fail", error=error_context.to_dict())
                raise InitializationError(error_context) from e

    def remove_webhook(self) -> None:
        with self.log_context(action="remove_webhook") as log:
            try:
                self.bot.remove_webhook()

            except ApiTelegramException as e:
                error_context = ErrorContext(
                    message="Failed to remove webhook",
                    error_code="WEBHOOK_REMOVE_FAILED",
                    metadata={"exception": str(e)},
                )
                log.exception("bot.webhook.removal.fail", error=error_context.to_dict())
                raise InitializationError(error_context) from e


class WebhookServer(BaseComponent):
    __slots__ = (
        "bot",
        "token",
        "host",
        "port",
        "request_counter",
        "last_restart",
        "telegram_ip_validator",
        "secret_token",
        "webhook_path_token",
        "webhook_path",
        "_accepted_webhook_credentials",
        "_rotation_lock",
        "_rotation_in_progress",
        "_rotation_thread",
        "trusted_proxy_sources",
        "trusted_proxy_networks",
        "webhook_manager",
        "app",
        "rate_limiter",
        "rate_limiter_404",
    )
    WEBHOOK_ROUTE_PATH = "/webhook/{path_token}/"
    WEBHOOK_ROTATION_REQUEST_THRESHOLD = 10_000
    WEBHOOK_ROTATION_GRACE_PERIOD_SECONDS = 300

    def __init__(self, bot: TeleBot, token: str, host: str, port: int) -> None:
        super().__init__("webhook_server")
        self.bot = bot
        self.token = token
        self.host = host
        self.port = port
        self.request_counter = 0
        self.last_restart = datetime.now()

        # Generate secure webhook path and secret token
        self.secret_token = generate_secret_token()
        self.webhook_path_token = self._generate_webhook_path_token()
        self.webhook_path = self._build_webhook_path(self.webhook_path_token)
        self._accepted_webhook_credentials: dict[str, tuple[str, datetime | None]] = {
            self.webhook_path_token: (self.secret_token, None)
        }
        self._rotation_lock = threading.RLock()
        self._rotation_in_progress = False
        self._rotation_thread: threading.Thread | None = None

        with self.log_context(
            host=host,
            port=port,
            webhook_path=mask_webhook_path(self.webhook_path),
        ) as log:
            log.debug("bot.webhook.server.components.init")

            # Initialize webhook manager
            webhook_settings = _get_webhook_config()
            webhook_url = webhook_settings.url[0].get_secret_value()
            webhook_port = webhook_settings.webhook_port[0]
            self.trusted_proxy_sources = webhook_settings.trusted_proxy_ips or []
            self.telegram_ip_validator = TelegramIPValidator(
                additional_ranges=webhook_settings.additional_telegram_ip_ranges or []
            )
            self.trusted_proxy_networks = self._parse_proxy_networks(
                self.trusted_proxy_sources
            )

            self.webhook_manager = WebhookManager(
                bot=bot,
                url=webhook_url,
                port=webhook_port,
                secret_token=self.secret_token,
            )

            self.app = self._create_app()
            enable_rate_state_persistence = "PYTEST_CURRENT_TEST" not in os.environ
            state_dir = os.path.join(
                "/tmp", "pytmbot_webhook_ratelimit", str(self.port)
            )
            self.rate_limiter = RateLimit(
                limit=10,
                period=10,
                max_tracked_ips=4096,
                state_file=(
                    os.path.join(state_dir, "main.json")
                    if enable_rate_state_persistence
                    else None
                ),
            )
            self.rate_limiter_404 = RateLimit(
                limit=5,
                period=10,
                max_tracked_ips=1024,
                state_file=(
                    os.path.join(state_dir, "404.json")
                    if enable_rate_state_persistence
                    else None
                ),
            )
            log.info("bot.webhook.server.init.ok")

    def _create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
            with self.log_context(
                action="server_lifecycle",
                webhook_path=mask_webhook_path(self.webhook_path),
            ) as log:
                try:
                    log.info("bot.webhook.server.lifecycle.start")
                    self.webhook_manager.setup_webhook(
                        self.webhook_path,
                        secret_token=self.secret_token,
                        drop_pending_updates=True,
                        reset_existing=True,
                    )
                    yield
                except Exception as e:
                    error_context = ErrorContext(
                        message="Webhook lifecycle error",
                        error_code="WEBHOOK_LIFECYCLE_ERROR",
                        metadata={"exception": str(e)},
                    )
                    log.exception(
                        "bot.webhook.initialize.lifecycle.fail",
                        error=error_context.to_dict(),
                    )
                    raise InitializationError(error_context) from e

        app = FastAPI(
            docs_url=None,
            redoc_url=None,
            title="PyTMBot Webhook Server",
            version=app_version,
            lifespan=lifespan,
        )

        self._setup_routes(app)
        return app

    @staticmethod
    def _get_update_type(update: UpdateModel) -> str:
        update_types = [
            "message",
            "edited_message",
            "inline_query",
            "callback_query",
        ]
        return next(
            (field for field in update_types if getattr(update, field) is not None),
            "unknown",
        )

    @staticmethod
    def _generate_webhook_path_token() -> str:
        """Generate secure webhook path token."""
        return generate_secret_token(16)

    @staticmethod
    def _build_webhook_path(path_token: str) -> str:
        """Build webhook path from token."""
        return f"/webhook/{path_token}/"

    def _cleanup_expired_webhook_credentials(self, now: datetime) -> None:
        """Cleanup expired webhook credentials from grace window."""
        expired_path_tokens = [
            path_token
            for path_token, (
                _,
                expires_at,
            ) in self._accepted_webhook_credentials.items()
            if expires_at is not None and now >= expires_at
        ]
        for path_token in expired_path_tokens:
            self._accepted_webhook_credentials.pop(path_token, None)

    def _resolve_expected_secret(self, path_token: str) -> str | None:
        """Resolve expected secret token for webhook path."""
        now = datetime.now()
        with self._rotation_lock:
            self._cleanup_expired_webhook_credentials(now)
            credentials = self._accepted_webhook_credentials.get(path_token)
            if credentials is None:
                return None
            return credentials[0]

    def _maybe_rotate_webhook(self) -> None:
        """Schedule webhook rotation after request threshold without blocking request."""
        with self._rotation_lock:
            if self.request_counter < self.WEBHOOK_ROTATION_REQUEST_THRESHOLD:
                return
            if self._rotation_in_progress:
                return
            self._rotation_in_progress = True

            rotation_thread = threading.Thread(
                target=self._rotate_webhook_credentials,
                name="webhook-rotation",
                daemon=True,
            )
            self._rotation_thread = rotation_thread

        rotation_thread.start()

    def _rotate_webhook_credentials(self) -> None:
        """Rotate webhook path and secret in background worker."""
        previous_path_token: str | None
        previous_secret_token: str | None

        with self._rotation_lock:
            previous_path_token = self.webhook_path_token
            previous_secret_token = self.secret_token

        if previous_path_token is None or previous_secret_token is None:
            with self._rotation_lock:
                self._rotation_in_progress = False
                self._rotation_thread = None
            return

        new_path_token = self._generate_webhook_path_token()
        new_secret_token = generate_secret_token()
        new_webhook_path = self._build_webhook_path(new_path_token)

        try:
            self.webhook_manager.setup_webhook(
                new_webhook_path,
                secret_token=new_secret_token,
                drop_pending_updates=False,
                reset_existing=False,
            )

            rotated_at = datetime.now()
            grace_deadline = rotated_at + timedelta(
                seconds=self.WEBHOOK_ROTATION_GRACE_PERIOD_SECONDS
            )

            with self._rotation_lock:
                self._accepted_webhook_credentials[previous_path_token] = (
                    previous_secret_token,
                    grace_deadline,
                )
                self._accepted_webhook_credentials[new_path_token] = (
                    new_secret_token,
                    None,
                )
                self.webhook_path_token = new_path_token
                self.webhook_path = new_webhook_path
                self.secret_token = new_secret_token
                self.request_counter = 0
                self.last_restart = rotated_at

            with self.log_context(
                action="webhook_rotation",
                previous_webhook_path=mask_webhook_path(
                    self._build_webhook_path(previous_path_token)
                ),
                new_webhook_path=mask_webhook_path(new_webhook_path),
                grace_period_seconds=self.WEBHOOK_ROTATION_GRACE_PERIOD_SECONDS,
            ) as log:
                log.info("bot.webhook.rotation.completed.ok")

        except Exception as error:
            with self.log_context(
                action="webhook_rotation",
                error_type=type(error).__name__,
                error=str(error),
            ) as log:
                log.error("bot.webhook.rotation.fail")
        finally:
            with self._rotation_lock:
                self._rotation_in_progress = False
                self._rotation_thread = None

    @staticmethod
    def _parse_proxy_networks(
        proxy_sources: list[str],
    ) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """Parse trusted proxy CIDR/IP list into network objects."""
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for source in proxy_sources:
            networks.append(ipaddress.ip_network(source, strict=False))
        return networks

    def _is_trusted_proxy(self, source_ip: str) -> bool:
        """Validate source IP against configured trusted proxies."""
        try:
            ip_obj = ipaddress.ip_address(source_ip)
        except ValueError:
            return False
        return any(ip_obj in network for network in self.trusted_proxy_networks)

    def _resolve_client_ip(
        self, request: Request, x_forwarded_for: str | None
    ) -> tuple[str, str]:
        """
        Resolve real client IP safely.

        Returns:
            Tuple of (peer_ip, resolved_client_ip)
        """
        if request.client is None:
            raise HTTPException(
                status_code=400, detail="Cannot determine peer client IP address"
            )

        peer_ip = request.client.host

        if not x_forwarded_for:
            return peer_ip, peer_ip

        if not self.trusted_proxy_networks:
            raise HTTPException(
                status_code=403,
                detail="Access denied: Forwarded headers are not allowed",
            )

        if not self._is_trusted_proxy(peer_ip):
            raise HTTPException(
                status_code=403,
                detail="Access denied: Untrusted proxy source",
            )

        if len(x_forwarded_for) > 512:
            raise HTTPException(
                status_code=400, detail="Malformed X-Forwarded-For header"
            )

        forwarded_chain = [
            item.strip() for item in x_forwarded_for.split(",") if item.strip()
        ]
        if not forwarded_chain:
            raise HTTPException(
                status_code=400, detail="Malformed X-Forwarded-For header"
            )

        client_ip = forwarded_chain[0]
        try:
            _ = ipaddress.ip_address(client_ip)
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail="Invalid client IP in forwarded header"
            ) from error

        return peer_ip, client_ip

    def _get_update_error_context(self, update: UpdateModel) -> dict[str, int | str]:
        """Return minimal and safe update context for error logs."""
        return {
            "update_id": update.update_id,
            "update_type": self._get_update_type(update),
        }

    def _setup_routes(self, app: FastAPI) -> None:
        with self.log_context(action="route_setup") as log:
            log.debug("bot.webhook.config.routes.debug")

            @app.exception_handler(404)
            async def not_found_handler(
                request: Request, exc: HTTPException
            ) -> JSONResponse:
                _ = exc
                client_ip = request.client.host if request.client else "unknown"
                masked_client_ip = mask_ip_address(client_ip)
                request_path = request.url.path.replace("\n", "\\n").replace(
                    "\r", "\\r"
                )
                with self.log_context(
                    action="handle_404",
                    client_ip=masked_client_ip,
                    request_path=request_path,
                ) as _log:
                    if self.rate_limiter_404.is_rate_limited(client_ip):
                        _log.warning("bot.webhook.rate.limit.warn")
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Too many not found requests"},
                        )

                    _log.warning("bot.webhook.404.request.warn")
                    return JSONResponse(
                        status_code=404, content={"detail": "Not found"}
                    )

            def verify_telegram_ip(
                request: Request,
                x_forwarded_for: Annotated[str | None, Header()] = None,
            ) -> str:
                peer_ip, client_ip = self._resolve_client_ip(request, x_forwarded_for)
                masked_client_ip = mask_ip_address(client_ip)
                masked_peer_ip = mask_ip_address(peer_ip)

                with self.log_context(
                    action="ip_verification",
                    client_ip=masked_client_ip,
                    peer_ip=masked_peer_ip,
                    has_forwarded_header=bool(x_forwarded_for),
                ) as _log:
                    if not self.telegram_ip_validator.is_telegram_ip(client_ip):
                        _log.warning(
                            "bot.webhook.non.ip.deny",
                        )
                        raise HTTPException(
                            status_code=403,
                            detail="Access denied: Request must come from Telegram servers",
                        )
                    _log.info("bot.webhook.ip.verified.ok")
                    return client_ip

            @app.post(self.WEBHOOK_ROUTE_PATH)
            def process_webhook(
                path_token: str,
                update: UpdateModel,
                client_ip: Annotated[str, Depends(verify_telegram_ip)],
                x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
            ) -> JSONResponse:
                masked_client_ip = mask_ip_address(client_ip)
                with self.log_context(
                    action="webhook_processing",
                    client_ip=masked_client_ip,
                    request_counter=self.request_counter,
                ) as _log:
                    try:
                        expected_secret = self._resolve_expected_secret(path_token)
                        if expected_secret is None:
                            if self.rate_limiter_404.is_rate_limited(client_ip):
                                _log.warning("bot.webhook.rate.limit.warn")
                                raise HTTPException(
                                    status_code=429,
                                    detail="Too many not found requests",
                                )
                            _log.warning("bot.webhook.404.request.warn")
                            raise HTTPException(status_code=404, detail="Not found")

                        # Rate limiting check
                        if self.rate_limiter.is_rate_limited(client_ip):
                            _log.warning("bot.webhook.rate.limit.warn")
                            raise HTTPException(
                                status_code=429, detail="Rate limit exceeded"
                            )

                        # Token verification
                        if x_telegram_bot_api_secret_token != expected_secret:
                            _log.warning("bot.webhook.invalid.secret.warn")
                            raise HTTPException(
                                status_code=403, detail="Invalid secret token"
                            )

                        # Update processing
                        with self._rotation_lock:
                            self.request_counter += 1

                        update_dict = update.model_dump(
                            exclude_unset=True, by_alias=True
                        )
                        update_type = self._get_update_type(update)

                        # Process update
                        with self.log_context(
                            action="update_processing",
                            update_type=update_type,
                            update_id=update_dict.get("update_id"),
                        ) as update_log:
                            update_log.info("bot.webhook.processing.update.info")
                            update_from_json: Callable[
                                [dict[str, JsonValue]],
                                telebot.types.Update,
                            ] = telebot.types.Update.de_json
                            update_obj = update_from_json(update_dict)
                            self.bot.process_new_updates([update_obj])
                            update_log.debug("bot.webhook.update.processed.ok")

                        self._maybe_rotate_webhook()

                        return JSONResponse(
                            status_code=200,
                            content={"status": "ok", "update_type": update_type},
                        )

                    except ValueError as e:
                        _log.error(
                            "bot.webhook.invalid.update.fail",
                            error=str(e),
                            **self._get_update_error_context(update),
                        )
                        raise HTTPException(
                            status_code=400, detail="Invalid update format"
                        ) from e
                    except HTTPException:
                        # Preserve original status codes (e.g., 403/429) from guard checks.
                        raise
                    except Exception as e:
                        _log.error(
                            "bot.webhook.update.processing.fail",
                            error=str(e),
                            error_type=type(e).__name__,
                            **self._get_update_error_context(update),
                        )
                        raise HTTPException(
                            status_code=500, detail="Internal server error"
                        ) from e

    def start(self) -> None:
        with self.log_context(
            action="server_startup",
            host=self.host,
            port=self.port,
            webhook_path=mask_webhook_path(self.webhook_path),
        ) as log:
            # Port validation
            if self.port < 1024:
                error_context = ErrorContext(
                    message="Cannot run webhook server on privileged ports",
                    error_code="PRIVILEGED_PORT_ERROR",
                    metadata={"requested_port": self.port},
                )
                log.error(
                    "bot.webhook.privileged.port.fail", error=error_context.to_dict()
                )
                raise InitializationError(error_context)

            try:
                # SSL configuration
                webhook_settings = _get_webhook_config()
                cert_file = _normalize_ssl_path(_first_secret(webhook_settings.cert))
                key_file = _normalize_ssl_path(_first_secret(webhook_settings.cert_key))
                ssl_enabled = bool(cert_file and key_file)

                if ssl_enabled and cert_file is not None and key_file is not None:
                    cert_exists = os.path.isfile(cert_file)
                    key_exists = os.path.isfile(key_file)
                    if not cert_exists or not key_exists:
                        with self.log_context(
                            cert_file=cert_file,
                            key_file=key_file,
                            cert_exists=cert_exists,
                            key_exists=key_exists,
                        ) as ssl_log:
                            ssl_log.warning(
                                "bot.webhook.ssl.files.missing.fallback.warn"
                            )
                        cert_file = None
                        key_file = None
                        ssl_enabled = False

                # Server configuration logging
                with self.log_context(
                    ssl_enabled=ssl_enabled,
                    ssl_cert_present=bool(cert_file),
                    ssl_key_present=bool(key_file),
                    proxy_enabled=bool(self.trusted_proxy_sources),
                    uvicorn_proxy_headers=False,
                    trusted_proxy_count=len(self.trusted_proxy_sources),
                    workers_count=1,
                ) as config_log:
                    if ssl_enabled and cert_file and key_file:
                        config_log.debug("bot.webhook.ssl.config.debug")
                        uvicorn.run(
                            self.app,
                            host=self.host,
                            port=self.port,
                            log_level="critical",
                            access_log=False,
                            proxy_headers=False,
                            workers=1,
                            ssl_certfile=cert_file,
                            ssl_keyfile=key_file,
                        )
                    else:
                        uvicorn.run(
                            self.app,
                            host=self.host,
                            port=self.port,
                            log_level="critical",
                            access_log=False,
                            proxy_headers=False,
                            workers=1,
                        )

                    config_log.info("bot.webhook.uvicorn.server.start")

            except FileNotFoundError as e:
                error_context = ErrorContext(
                    message="SSL certificate or key file not found",
                    error_code="FILE_NOT_FOUND_ERROR",
                    metadata={"exception": str(e)},
                )
                log.exception(
                    "bot.webhook.ssl.files.fail", error=error_context.to_dict()
                )
                raise InitializationError(error_context) from e

            except PermissionError as e:
                error_context = ErrorContext(
                    message="Permission denied while starting server",
                    error_code="PERMISSION_ERROR",
                    metadata={"exception": str(e)},
                )
                log.exception(
                    "bot.webhook.permission.fail", error=error_context.to_dict()
                )
                raise InitializationError(error_context) from e

            except OSError as e:
                error_context = ErrorContext(
                    message="System error while starting server",
                    error_code="OS_ERROR",
                    metadata={"exception": str(e)},
                )
                log.exception("bot.webhook.os.fail", error=error_context.to_dict())
                raise InitializationError(error_context) from e

            except Exception as e:
                error_context = ErrorContext(
                    message="Failed to start webhook server",
                    error_code="UNEXPECTED_ERROR",
                    metadata={"error_class": e.__class__.__name__, "exception": str(e)},
                )
                log.exception(
                    "bot.webhook.unexpected.fail", error=error_context.to_dict()
                )
                raise BotException(error_context) from e
