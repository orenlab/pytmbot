from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from time import time
from typing import Dict, Annotated, AsyncGenerator

import telebot
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.responses import JSONResponse
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from pytmbot.exceptions import PyTMBotError
from pytmbot.globals import settings
from pytmbot.logs import bot_logger
from pytmbot.models.telegram_models import TelegramIPValidator
from pytmbot.models.updates_model import UpdateModel
from pytmbot.utils.utilities import sanitize_exception, generate_secret_token


class RateLimit:
    def __init__(self, limit: int, period: int, ban_threshold: int = 50) -> None:
        self.limit = limit
        self.period = period
        self.ban_threshold = ban_threshold
        self.requests: Dict[str, deque[float]] = {}
        self.banned_ips: Dict[str, datetime] = {}

    def is_banned(self, client_ip: str) -> bool:
        if client_ip not in self.banned_ips:
            return False

        ban_time = self.banned_ips[client_ip]
        if (datetime.now() - ban_time).total_seconds() > 3600:
            del self.banned_ips[client_ip]
            return False
        return True

    def is_rate_limited(self, client_ip: str) -> bool:
        if self.is_banned(client_ip):
            return True

        current_time = time()
        if client_ip not in self.requests:
            self.requests[client_ip] = deque()

        request_times = self.requests[client_ip]

        # Clean up old requests
        while request_times and request_times[0] < current_time - self.period:
            request_times.popleft()

        if len(request_times) >= self.ban_threshold:
            self.banned_ips[client_ip] = datetime.now()
            bot_logger.warning(f"IP {client_ip} banned for excessive requests")
            return True

        if len(request_times) >= self.limit:
            return True

        request_times.append(current_time)
        return False


class WebhookManager:
    """Manages webhook configuration and lifecycle."""

    def __init__(self, bot: TeleBot, url: str, port: int, secret_token: str = None) -> None:
        self.bot = bot
        self.url = url
        self.port = port
        self.secret_token = secret_token
        bot_logger.debug(
            f"Initialized WebhookManager with URL: {url}, port: {port}, "
            f"secret token present: {bool(secret_token)}"
        )

    def setup_webhook(self, webhook_path: str) -> None:
        """Configures the webhook for the bot."""
        try:
            bot_logger.debug(f"Starting webhook setup with path: {webhook_path}")

            # Remove any existing webhook first
            self.remove_webhook()

            webhook_url = f"https://{self.url}:{self.port}{webhook_path}"
            cert_path = settings.webhook_config.cert[0].get_secret_value() or None
            bot_logger.debug(
                f"Webhook configuration - URL: {webhook_url}, "
                f"Certificate present: {bool(cert_path)}"
            )

            webhook_info = self.bot.get_webhook_info()
            bot_logger.debug(f"Current webhook info before setup: {webhook_info}")

            self.bot.set_webhook(
                url=webhook_url,
                timeout=20,
                allowed_updates=['message', 'edited_message', 'inline_query', 'callback_query'],
                drop_pending_updates=True,
                certificate=cert_path,
                secret_token=self.secret_token
            )

            # Verify webhook was set correctly
            new_webhook_info = self.bot.get_webhook_info()
            bot_logger.info(
                f"Webhook successfully configured. New webhook info: {new_webhook_info}"
            )

        except ApiTelegramException as e:
            error_msg = f"Failed to set webhook: {sanitize_exception(e)}"
            bot_logger.error(error_msg)
            raise PyTMBotError(error_msg) from e

    def remove_webhook(self) -> None:
        """Removes the existing webhook configuration."""
        try:
            bot_logger.debug("Attempting to remove existing webhook")
            webhook_info = self.bot.get_webhook_info()
            bot_logger.debug(f"Current webhook info before removal: {webhook_info}")

            self.bot.remove_webhook()

            # Verify webhook was removed
            new_webhook_info = self.bot.get_webhook_info()
            bot_logger.debug(f"Webhook removed. New webhook info: {new_webhook_info}")
        except ApiTelegramException as e:
            error_msg = f"Failed to remove webhook: {sanitize_exception(e)}"
            bot_logger.error(error_msg)
            raise PyTMBotError(error_msg) from e


class WebhookServer:
    """FastAPI server for handling Telegram webhook requests."""

    def __init__(self, bot: TeleBot, token: str, host: str, port: int) -> None:
        bot_logger.debug(
            f"Initializing WebhookServer - host: {host}, port: {port}"
        )

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
        bot_logger.debug(f"Generated webhook path: {self.webhook_path}")

        # Initialize webhook manager
        webhook_settings = settings.webhook_config
        webhook_url = webhook_settings.url[0].get_secret_value()
        webhook_port = webhook_settings.webhook_port[0]

        bot_logger.debug(
            f"Creating WebhookManager with URL: {webhook_url}, port: {webhook_port}"
        )

        self.webhook_manager = WebhookManager(
            bot=bot,
            url=webhook_url,
            port=webhook_port,
            secret_token=self.secret_token
        )

        self.app = self._create_app()
        self.rate_limiter = RateLimit(limit=10, period=10)
        self.rate_limiter_404 = RateLimit(limit=5, period=10)

    def _create_app(self) -> FastAPI:
        bot_logger.debug("Creating FastAPI application")

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            """
            Async context manager for FastAPI lifespan events.
            Handles webhook setup on startup and cleanup on shutdown.

            Args:
                app: FastAPI application instance

            Yields:
                None
            """
            bot_logger.info("Starting webhook server lifecycle")
            try:
                bot_logger.debug("Configuring webhook during startup")
                self.webhook_manager.setup_webhook(self.webhook_path)
                yield
            except Exception as e:
                error_msg = f"Webhook lifecycle error: {sanitize_exception(e)}"
                bot_logger.error(error_msg)
                raise
            finally:
                try:
                    bot_logger.debug("Removing webhook during shutdown")
                    self.webhook_manager.remove_webhook()
                except Exception as e:
                    bot_logger.error(f"Error during webhook cleanup: {sanitize_exception(e)}")
                bot_logger.info("Webhook server shutdown complete")

        app = FastAPI(
            docs_url=None,
            redoc_url=None,
            title="PyTMBot Webhook Server",
            version="2.1.0",
            lifespan=lifespan
        )

        self._setup_routes(app)
        return app

    @staticmethod
    def _get_update_type(update: UpdateModel) -> str:
        update_types = [
            'message', 'edited_message', 'inline_query', 'callback_query',
        ]

        for field in update_types:
            if getattr(update, field) is not None:
                return field
        return "unknown"

    def _setup_routes(self, app: FastAPI) -> None:
        bot_logger.debug("Setting up FastAPI routes")

        @app.exception_handler(404)
        def not_found_handler(request: Request, exc: HTTPException) -> JSONResponse:
            client_ip = request.client.host
            bot_logger.warning(f"404 request from {client_ip}: {request.url}")

            if self.rate_limiter_404.is_rate_limited(client_ip):
                bot_logger.warning(f"Rate limit exceeded for 404 requests from {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many not found requests"}
                )
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"}
            )

        def verify_telegram_ip(
                request: Request,
                x_forwarded_for: Annotated[str | None, Header()] = None
        ) -> str:
            client_ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.client.host
            bot_logger.debug(f"Verifying Telegram IP: {client_ip}")

            if not self.telegram_ip_validator.is_telegram_ip(client_ip):
                bot_logger.warning(f"Request from non-Telegram IP: {client_ip}")
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: Request must come from Telegram servers"
                )
            return client_ip

        @app.post(self.webhook_path)
        def process_webhook(
                update: UpdateModel,
                client_ip: Annotated[str, Depends(verify_telegram_ip)],
                x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None
        ) -> JSONResponse:
            bot_logger.debug(f"Received webhook request from {client_ip}")

            try:
                if self.rate_limiter.is_rate_limited(client_ip):
                    bot_logger.warning(f"Rate limit exceeded for {client_ip}")
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit exceeded"
                    )

                if x_telegram_bot_api_secret_token != self.secret_token:
                    bot_logger.warning(
                        f"Invalid secret token from {client_ip}. "
                        f"Expected: {self.secret_token}, "
                        f"Received: {x_telegram_bot_api_secret_token}"
                    )
                    raise HTTPException(status_code=403, detail="Invalid secret token")

                self.request_counter += 1
                bot_logger.debug(f"Request counter: {self.request_counter}")

                if self.request_counter > 1000:
                    bot_logger.warning("Request threshold reached, preparing for restart")
                    self.request_counter = 0
                    self.last_restart = datetime.now()

                update_dict = update.model_dump(exclude_unset=True, by_alias=True)
                update_type = self._get_update_type(update)

                bot_logger.debug(
                    f"Processing {update_type} update from {client_ip}: {update_dict}"
                )

                update_obj = telebot.types.Update.de_json(update_dict)
                self.bot.process_new_updates([update_obj])

                bot_logger.debug(f"Successfully processed {update_type} update")
                return JSONResponse(
                    status_code=200,
                    content={"status": "ok", "update_type": update_type}
                )

            except ValueError as e:
                error_msg = f"Invalid update format: {str(e)}"
                bot_logger.error(f"{error_msg}\nUpdate data: {update.model_dump()}")
                raise HTTPException(status_code=400, detail="Invalid update format")
            except Exception as e:
                error_msg = f"Failed to process update: {str(e)}"
                bot_logger.error(f"{error_msg}\nUpdate data: {update.model_dump()}")
                raise HTTPException(status_code=500, detail="Internal server error")

    def start(self) -> None:
        """Starts the webhook server."""
        bot_logger.info("Starting webhook server")

        if self.port < 1024:
            error_msg = "Cannot run webhook server on privileged ports. Use reverse proxy instead."
            bot_logger.error(error_msg)
            raise PyTMBotError(error_msg)

        try:
            cert_file = settings.webhook_config.cert[0].get_secret_value()
            key_file = settings.webhook_config.cert_key[0].get_secret_value()

            uvicorn_config = {
                "app": self.app,
                "host": self.host,
                "port": self.port,
                "log_level": "critical",
                "access_log": False,
                "proxy_headers": True,
                "forwarded_allow_ips": "*",
                "workers": 1
            }

            if cert_file and key_file:
                bot_logger.info(f"Starting webhook server with SSL on {self.host}:{self.port}")
                uvicorn_config.update({
                    "ssl_certfile": cert_file,
                    "ssl_keyfile": key_file
                })
            else:
                bot_logger.info(f"Starting webhook server without SSL on {self.host}:{self.port}")

            uvicorn.run(**uvicorn_config)

        except Exception as e:
            error_msg = f"Failed to start webhook server: {sanitize_exception(e)}"
            bot_logger.error(error_msg)
            raise PyTMBotError(error_msg) from e
