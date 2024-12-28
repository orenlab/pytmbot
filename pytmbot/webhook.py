from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from time import time
from typing import Dict, Annotated

import telebot
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from typing_extensions import override

from pytmbot.exceptions import PyTMBotError
from pytmbot.globals import settings
from pytmbot.logs import bot_logger
from pytmbot.models.telegram_models import TelegramIPValidator
from pytmbot.models.updates_model import UpdateModel
from pytmbot.utils.utilities import sanitize_exception, generate_secret_token


class WebhookManager:
    """Manages webhook configuration and lifecycle."""

    def __init__(self, bot: TeleBot, url: str, port: int, secret_token: str = None) -> None:
        self.bot = bot
        self.url = url
        self.port = port
        self.secret_token = secret_token

    async def setup_webhook(self, webhook_path: str) -> None:
        """
        Configures the webhook for the bot.

        Args:
            webhook_path (str): The path component of the webhook URL

        Raises:
            PyTMBotError: If webhook configuration fails
        """
        try:
            # Remove any existing webhook first
            await self.remove_webhook()

            webhook_url = f"https://{self.url}:{self.port}{webhook_path}"
            cert_path = settings.webhook_config.cert[0].get_secret_value() or None

            bot_logger.debug(f"Setting webhook URL: {webhook_url}")

            self.bot.set_webhook(
                url=webhook_url,
                timeout=20,
                allowed_updates=['message', 'edited_message', 'inline_query', 'callback_query', ],
                drop_pending_updates=True,
                certificate=cert_path,
                secret_token=self.secret_token
            )
            bot_logger.info("Webhook successfully configured")

        except ApiTelegramException as e:
            error_msg = f"Failed to set webhook: {sanitize_exception(e)}"
            bot_logger.error(error_msg)
            raise PyTMBotError(error_msg) from e

    async def remove_webhook(self) -> None:
        """
        Removes the existing webhook configuration.

        Raises:
            PyTMBotError: If webhook removal fails
        """
        try:
            self.bot.remove_webhook()
            bot_logger.debug("Existing webhook removed")
        except ApiTelegramException as e:
            error_msg = f"Failed to remove webhook: {sanitize_exception(e)}"
            bot_logger.error(error_msg)
            raise PyTMBotError(error_msg) from e


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware for adding security headers."""

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self.security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "X-XSS-Protection": "1; mode=block",
            "Content-Security-Policy": "default-src 'self'"
        }

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.update(self.security_headers)
        return response


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


class WebhookServer:
    """FastAPI server for handling Telegram webhook requests."""

    def __init__(self, bot: TeleBot, token: str, host: str, port: int) -> None:
        self.bot = bot
        self.token = token
        self.host = host
        self.port = port
        self.request_counter = 0
        self.last_restart = datetime.now()
        self.telegram_ip_validator = TelegramIPValidator()

        # Generate secure webhook path
        self.webhook_path = f"/webhook/{generate_secret_token(16)}/{self.token}/"

        # Initialize webhook manager
        webhook_settings = settings.webhook_config
        self.secret_token = generate_secret_token()
        self.webhook_manager = WebhookManager(
            bot=bot,
            url=webhook_settings.url[0].get_secret_value(),
            port=webhook_settings.webhook_port[0],
            secret_token=self.secret_token
        )

        self.app = self._create_app()
        self.rate_limiter = RateLimit(limit=10, period=10)
        self.rate_limiter_404 = RateLimit(limit=5, period=10)

    def _create_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan():
            bot_logger.info("Initializing webhook server...")
            try:
                # Configure webhook during startup
                await self.webhook_manager.setup_webhook(self.webhook_path)
                yield
                # Cleanup webhook during shutdown
                await self.webhook_manager.remove_webhook()
            except Exception as e:
                bot_logger.error(f"Webhook lifecycle error: {sanitize_exception(e)}")
                raise
            finally:
                bot_logger.info("Shutting down webhook server...")

        app = FastAPI(
            docs_url=None,
            redoc_url=None,
            title="PyTMBot Webhook Server",
            version="2.1.0",
            lifespan=lifespan
        )

        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[],
            allow_credentials=False,
            allow_methods=["POST"],
            allow_headers=["*"],
            max_age=3600,
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
        @app.exception_handler(404)
        async def not_found_handler(request: Request, exc: HTTPException) -> JSONResponse:
            client_ip = request.client.host
            if self.rate_limiter_404.is_rate_limited(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many not found requests"}
                )
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"}
            )

        async def verify_telegram_ip(
                request: Request,
                x_forwarded_for: Annotated[str | None, Header()] = None
        ) -> str:
            client_ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.client.host

            if not self.telegram_ip_validator.is_telegram_ip(client_ip):
                bot_logger.warning(f"Request from non-Telegram IP: {client_ip}")
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: Request must come from Telegram servers"
                )
            return client_ip

        @app.post(self.webhook_path)
        async def process_webhook(
                update: UpdateModel,
                client_ip: Annotated[str, Depends(verify_telegram_ip)],
                x_telegram_bot_api_secret_token: Annotated[str | None, Header()]
        ) -> JSONResponse:
            try:
                if self.rate_limiter.is_rate_limited(client_ip):
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit exceeded"
                    )

                if x_telegram_bot_api_secret_token != self.secret_token:
                    bot_logger.warning(f"Invalid secret token from {client_ip}")
                    raise HTTPException(status_code=403, detail="Invalid secret token")

                self.request_counter += 1

                if self.request_counter > 1000:
                    bot_logger.warning("Request threshold reached, preparing for restart")
                    self.request_counter = 0
                    self.last_restart = datetime.now()

                update_type = self._get_update_type(update)
                bot_logger.debug(
                    f"Processing {update_type} update from {client_ip}: {update.model_dump(exclude_unset=True)}"
                )

                update_dict = update.model_dump(
                    exclude_unset=True,
                    by_alias=True
                )
                update_obj = telebot.types.Update.de_json(update_dict)
                self.bot.process_new_updates([update_obj])

                return JSONResponse(
                    status_code=200,
                    content={"status": "ok", "update_type": update_type}
                )

            except ValueError as e:
                bot_logger.error(f"Invalid update format: {str(e)}")
                raise HTTPException(status_code=400, detail="Invalid update format")
            except Exception as e:
                bot_logger.error(f"Failed to process update: {str(e)}")
                raise HTTPException(status_code=500, detail="Internal server error")

    async def start(self) -> None:
        """
        Starts the webhook server asynchronously.

        Raises:
            PyTMBotError: If server fails to start or if using privileged port
        """
        if self.port < 1024:
            raise PyTMBotError(
                "Cannot run webhook server on privileged ports. Use reverse proxy instead."
            )

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

        server = uvicorn.Server(uvicorn.Config(**uvicorn_config))
        await server.serve()
