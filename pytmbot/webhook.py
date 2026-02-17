#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from time import time
from typing import Annotated

import telebot
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from pytmbot.exceptions import BotException, ErrorContext, InitializationError
from pytmbot.globals import settings
from pytmbot.logs import BaseComponent
from pytmbot.models.settings_model import WebhookConfig as SettingsWebhookConfig
from pytmbot.models.telegram_models import TelegramIPValidator
from pytmbot.models.updates_model import UpdateModel
from pytmbot.utils import generate_secret_token, mask_token_in_message

RATELIMIT_EXCEEDED_MESSAGE = "Rate limit exceeded"


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
    return values[0].get_secret_value()


class RateLimit(BaseComponent):
    __slots__ = ("limit", "period", "ban_threshold", "requests", "banned_ips")

    def __init__(self, limit: int, period: int, ban_threshold: int = 50) -> None:
        super().__init__()

        with self.log_context(
            limit=limit, period=period, ban_threshold=ban_threshold
        ) as log:
            log.debug("bot.webhook.rate.limiter.init")
            self.limit = limit
            self.period = period
            self.ban_threshold = ban_threshold
            self.requests: dict[str, deque[float]] = {}
            self.banned_ips: dict[str, datetime] = {}

    def is_banned(self, client_ip: str) -> bool:
        with self.log_context(ip=client_ip, action="check_ban"):
            if client_ip not in self.banned_ips:
                return False

            ban_time = self.banned_ips[client_ip]
            if (datetime.now() - ban_time).total_seconds() > 3600:
                with self.log_context(action="ban_expired", ip=client_ip) as log:
                    log.info("bot.webhook.ban.expired.info")
                del self.banned_ips[client_ip]
                return False
            with self.log_context(action="banned", ip=client_ip) as log:
                log.warning("bot.webhook.request.banned.warn")
            return True

    def is_rate_limited(self, client_ip: str) -> bool:
        with self.log_context(
            ip=client_ip,
            action="rate_check",
            requests_count=len(self.requests.get(client_ip, [])),
        ):
            if self.is_banned(client_ip):
                return True

            current_time = time()
            if client_ip not in self.requests:
                self.requests[client_ip] = deque()

            request_times = self.requests[client_ip]

            while request_times and request_times[0] < current_time - self.period:
                request_times.popleft()

            if len(request_times) >= self.ban_threshold:
                self.banned_ips[client_ip] = datetime.now()
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

    def setup_webhook(self, webhook_path: str) -> None:
        webhook_url = f"https://{self.url}:{self.port}{webhook_path}"
        webhook_settings = _get_webhook_config()
        cert_path = _first_secret(webhook_settings.cert)

        with self.log_context(
            action="setup_webhook",
            webhook_path=mask_token_in_message(webhook_path, self.bot.token),
        ) as log:
            try:
                current_webhook = self.bot.get_webhook_info()
                log.debug(
                    "bot.webhook.config.debug",
                    webhook_info=mask_token_in_message(
                        str(current_webhook), self.bot.token
                    ),
                    cert_present=bool(cert_path),
                )

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
                    drop_pending_updates=True,
                    certificate=cert_path,
                    secret_token=self.secret_token,
                )

                new_webhook = self.bot.get_webhook_info()
                log.info(
                    "bot.webhook.config.ok",
                    new_webhook=mask_token_in_message(str(new_webhook), self.bot.token),
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
        "webhook_path",
        "webhook_manager",
        "app",
        "rate_limiter",
        "rate_limiter_404",
    )

    def __init__(self, bot: TeleBot, token: str, host: str, port: int) -> None:
        super().__init__("webhook_server")
        self.bot = bot
        self.token = token
        self.host = host
        self.port = port
        self.request_counter = 0
        self.last_restart = datetime.now()
        self.telegram_ip_validator = TelegramIPValidator()

        # Generate secure webhook path and secret token
        self.secret_token = generate_secret_token()
        self.webhook_path = f"/webhook/{generate_secret_token(16)}/{self.token}/"

        with self.log_context(
            host=host,
            port=port,
            webhook_path=mask_token_in_message(self.webhook_path, self.token),
        ) as log:
            log.debug("bot.webhook.server.components.init")

            # Initialize webhook manager
            webhook_settings = _get_webhook_config()
            webhook_url = webhook_settings.url[0].get_secret_value()
            webhook_port = webhook_settings.webhook_port[0]

            self.webhook_manager = WebhookManager(
                bot=bot,
                url=webhook_url,
                port=webhook_port,
                secret_token=self.secret_token,
            )

            self.app = self._create_app()
            self.rate_limiter = RateLimit(limit=10, period=10)
            self.rate_limiter_404 = RateLimit(limit=5, period=10)
            log.info("bot.webhook.server.init.ok")

    def _create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
            with self.log_context(
                action="server_lifecycle",
                webhook_path=mask_token_in_message(self.webhook_path, self.token),
            ) as log:
                try:
                    log.info("bot.webhook.server.lifecycle.start")
                    self.webhook_manager.setup_webhook(self.webhook_path)
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
            version="2.1.0",
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

    def _setup_routes(self, app: FastAPI) -> None:
        with self.log_context(action="route_setup") as log:
            log.debug("bot.webhook.config.routes.debug")

            @app.exception_handler(404)
            async def not_found_handler(
                request: Request, exc: HTTPException
            ) -> JSONResponse:
                _ = exc
                client_ip = request.client.host if request.client else "unknown"
                with self.log_context(
                    action="handle_404",
                    client_ip=client_ip,
                    request_url=str(request.url),
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
                if x_forwarded_for:
                    client_ip = x_forwarded_for.split(",")[0].strip()
                else:
                    if request.client is None:
                        raise HTTPException(
                            status_code=400,
                            detail="Cannot determine client IP address",
                        )
                    client_ip = request.client.host

                with self.log_context(
                    action="ip_verification",
                    client_ip=client_ip,
                    x_forwarded_for=x_forwarded_for,
                ) as _log:
                    if not self.telegram_ip_validator.is_telegram_ip(client_ip):
                        _log.warning(
                            "bot.webhook.non.ip.deny",
                        )
                        raise HTTPException(
                            status_code=403,
                            detail="Access denied: Request must come from Telegram servers",
                        )
                    log.info("bot.webhook.ip.verified.ok")
                    return client_ip

            @app.post(self.webhook_path)
            def process_webhook(
                update: UpdateModel,
                client_ip: Annotated[str, Depends(verify_telegram_ip)],
                x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
            ) -> JSONResponse:
                with self.log_context(
                    action="webhook_processing",
                    client_ip=client_ip,
                    request_counter=self.request_counter,
                ) as _log:
                    try:
                        # Rate limiting check
                        if self.rate_limiter.is_rate_limited(client_ip):
                            _log.warning("bot.webhook.rate.limit.warn")
                            raise HTTPException(
                                status_code=429, detail="Rate limit exceeded"
                            )

                        # Token verification
                        if x_telegram_bot_api_secret_token != self.secret_token:
                            _log.warning("bot.webhook.invalid.secret.warn")
                            raise HTTPException(
                                status_code=403, detail="Invalid secret token"
                            )

                        # Update processing
                        self.request_counter += 1
                        update_dict = update.model_dump(
                            exclude_unset=True, by_alias=True
                        )
                        update_type = self._get_update_type(update)

                        # Request counter threshold check
                        if self.request_counter > 1000:
                            _log.warning(
                                "bot.webhook.request.threshold.warn",
                                total_requests=self.request_counter,
                                last_restart=self.last_restart.isoformat(),
                                uptime=(
                                    datetime.now() - self.last_restart
                                ).total_seconds(),
                            )
                            self.request_counter = 0
                            self.last_restart = datetime.now()

                        # Process update
                        with self.log_context(
                            action="update_processing",
                            update_type=update_type,
                            update_id=update_dict.get("update_id"),
                        ) as update_log:
                            update_log.info("bot.webhook.processing.update.info")
                            update_obj = telebot.types.Update.de_json(update_dict)
                            self.bot.process_new_updates([update_obj])
                            update_log.debug("bot.webhook.update.processed.ok")

                        return JSONResponse(
                            status_code=200,
                            content={"status": "ok", "update_type": update_type},
                        )

                    except ValueError as e:
                        log.error(
                            "bot.webhook.invalid.update.fail",
                            error=str(e),
                            update_data=update.model_dump(),
                        )
                        raise HTTPException(
                            status_code=400, detail="Invalid update format"
                        ) from e
                    except Exception as e:
                        log.error(
                            "bot.webhook.update.processing.fail",
                            error=str(e),
                            error_type=type(e).__name__,
                            update_data=update.model_dump(),
                        )
                        raise HTTPException(
                            status_code=500, detail="Internal server error"
                        ) from e

    def start(self) -> None:
        with self.log_context(
            action="server_startup",
            host=self.host,
            port=self.port,
            webhook_path=mask_token_in_message(self.webhook_path, self.token),
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
                cert_file = _first_secret(webhook_settings.cert)
                key_file = _first_secret(webhook_settings.cert_key)

                # Server configuration logging
                with self.log_context(
                    ssl_enabled=bool(cert_file and key_file),
                    ssl_cert_present=bool(cert_file),
                    ssl_key_present=bool(key_file),
                    proxy_enabled=True,
                    workers_count=1,
                ) as config_log:
                    if cert_file and key_file:
                        config_log.debug("bot.webhook.ssl.config.debug")
                        uvicorn.run(
                            self.app,
                            host=self.host,
                            port=self.port,
                            log_level="critical",
                            access_log=False,
                            proxy_headers=True,
                            forwarded_allow_ips="*",
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
                            proxy_headers=True,
                            forwarded_allow_ips="*",
                            workers=1,
                        )

                    config_log.info("bot.webhook.uvicorn.server.start")

            except FileNotFoundError as e:
                error_context = ErrorContext(
                    message="SSL certificate or key file not found",
                    error_code="FILE_NOT_FOUND_ERROR",
                    metadata={"exception": str(e)},
                )
                log.exception("bot.webhook.ssl.files.fail", error=error_context.to_dict())
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
