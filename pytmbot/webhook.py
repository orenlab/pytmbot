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

from pytmbot.exceptions import InitializationError, ErrorContext, ShutdownError, BotException
from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.models.telegram_models import TelegramIPValidator
from pytmbot.models.updates_model import UpdateModel
from pytmbot.utils.utilities import generate_secret_token, mask_token_in_message

logger = Logger()


class RateLimit:
    def __init__(self, limit: int, period: int, ban_threshold: int = 50) -> None:
        self.log = logger.bind_context(
            component="rate_limiter",
            limit=limit,
            period=period,
            ban_threshold=ban_threshold
        )
        self.limit = limit
        self.period = period
        self.ban_threshold = ban_threshold
        self.requests: Dict[str, deque[float]] = {}
        self.banned_ips: Dict[str, datetime] = {}

    def is_banned(self, client_ip: str) -> bool:
        self.log = self.log.bind_context(
            ip=client_ip,
            action="check_ban",
            banned_ips_count=len(self.banned_ips)
        )
        if client_ip not in self.banned_ips:
            return False

        ban_time = self.banned_ips[client_ip]
        if (datetime.now() - ban_time).total_seconds() > 3600:
            self.log.info("Ban expired, removing IP from banned list")
            del self.banned_ips[client_ip]
            return False
        self.log.warning("Request from banned IP rejected")
        return True

    def is_rate_limited(self, client_ip: str) -> bool:
        self.log = self.log.bind_context(
            ip=client_ip,
            action="rate_check",
            current_requests_count=len(self.requests.get(client_ip, []))
        )
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
            self.log.warning(
                "IP banned for excessive requests",
                requests_count=len(request_times),
                time_window=self.period
            )
            return True

        if len(request_times) >= self.limit:
            self.log.warning(
                "Rate limit exceeded",
                requests_count=len(request_times),
                time_window=self.period
            )
            return True

        request_times.append(current_time)
        return False


class WebhookManager:
    """Manages webhook configuration and lifecycle."""

    def __init__(self, bot: TeleBot, url: str, port: int, secret_token: str = None) -> None:
        self.log = logger.bind_context(
            component="webhook_manager",
            webhook_url=mask_token_in_message(url, bot.token),
            port=port,
            has_secret_token=bool(secret_token)
        )
        self.bot = bot
        self.url = url
        self.port = port
        self.secret_token = secret_token
        self.log.debug("Initialized WebhookManager")

    def setup_webhook(self, webhook_path: str) -> None:
        log = self.log.bind_context(
            action="setup",
            webhook_path=mask_token_in_message(webhook_path, self.bot.token)
        )

        try:
            self.remove_webhook()
            webhook_url = f"https://{self.url}:{self.port}{webhook_path}"
            cert_path = settings.webhook_config.cert[0].get_secret_value() or None

            log.debug(
                "Configuring webhook",
                webhook_info=self.bot.get_webhook_info(),
                cert_present=bool(cert_path),
                webhook_url=mask_token_in_message(webhook_url, self.bot.token)
            )

            self.bot.set_webhook(
                url=webhook_url,
                timeout=20,
                allowed_updates=['message', 'edited_message', 'inline_query', 'callback_query'],
                drop_pending_updates=True,
                certificate=cert_path,
                secret_token=self.secret_token
            )

            new_webhook_info = self.bot.get_webhook_info()
            log.info(
                "Webhook configured successfully",
                new_webhook_info=mask_token_in_message(str(new_webhook_info), self.bot.token)
            )

        except ApiTelegramException as e:
            log.error(
                "Webhook setup failed",
                error=e
            )
            raise InitializationError(ErrorContext(
                message="Webhook setup failed",
                error_code="WEBHOOK_SETUP_FAILED",
                metadata={
                    "exception": e
                })
            )

    def remove_webhook(self) -> None:
        """Removes the existing webhook configuration."""

        log = self.log.bind_context(
            action="remove_webhook"
        )

        try:
            webhook_info = self.bot.get_webhook_info()
            log.debug(
                "Checking existing webhook",
                current_webhook_info=webhook_info
            )

            self.bot.remove_webhook()

            # Verify webhook was removed
            new_webhook_info = self.bot.get_webhook_info()
            log.debug(
                "Webhook removed successfully",
                new_webhook_info=new_webhook_info
            )
        except ApiTelegramException as e:
            raise InitializationError(ErrorContext(
                message="Failed to remove webhook",
                error_code="WEBHOOK_REMOVE_FAILED",
                metadata={
                    "exception": e
                }
            ))


class WebhookServer:
    """FastAPI server for handling Telegram webhook requests."""

    def __init__(self, bot: TeleBot, token: str, host: str, port: int) -> None:
        self.log = logger.bind_context(
            component="webhook_server",
            host=host,
            port=port
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

        # Initialize webhook manager
        webhook_settings = settings.webhook_config
        webhook_url = webhook_settings.url[0].get_secret_value()
        webhook_port = webhook_settings.webhook_port[0]

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

        @asynccontextmanager
        async def lifespan() -> AsyncGenerator[None, None]:
            context = {
                "action": "lifespan",
                "webhook_path": mask_token_in_message(self.webhook_path, self.token)
            }
            self.log.info("Starting webhook server lifecycle...", context=context)
            try:
                self.log.debug("Initiating webhook configuration")
                self.webhook_manager.setup_webhook(self.webhook_path)
                yield
            except Exception as e:
                raise InitializationError(ErrorContext(
                    message="Webhook lifecycle error",
                    error_code="WEBHOOK_LIFECYCLE_ERROR",
                    metadata={
                        "exception": e
                    }
                ))
            finally:
                try:
                    self.log.debug("Removing webhook during shutdown")
                    self.webhook_manager.remove_webhook()
                except Exception as e:
                    raise ShutdownError(ErrorContext(
                        message="Error during webhook cleanup",
                        error_code="WEBHOOK_CLEANUP_ERROR",
                        metadata={
                            "exception": e
                        }
                    ))
                self.log.info("Webhook server shutdown complete")

        app = FastAPI(
            docs_url=None,
            redoc_url=None,
            title="PyTMBot Webhook Server",
            version="2.1.0",
            lifespan=lifespan
        )

        self._setup_routes(app)
        self.log.info("FastAPI application created successfully")
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
        context = {
            "action": "setup_routes"
        }
        self.log.debug("Setting up FastAPI routes", context=context)

        @app.exception_handler(404)
        def not_found_handler(request: Request) -> JSONResponse:
            client_ip = request.client.host
            _context = {
                "action": "handle_404",
                "client_ip": client_ip,
                "url": str(request.url)
            }
            self.log.warning("404 request received", context=_context)

            if self.rate_limiter_404.is_rate_limited(client_ip):
                self.log.warning("Rate limit exceeded for 404 requests")
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
            _context = {
                "action": "verify_ip",
                "client_ip": client_ip,
                "x_forwarded_for": x_forwarded_for
            }
            self.log.debug("Verifying Telegram IP", context=_context)

            if not self.telegram_ip_validator.is_telegram_ip(client_ip):
                self.log.warning("Request from non-Telegram IP rejected")
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
            _context = {
                "action": "process_webhook",
                "client_ip": client_ip,
                "request_counter": self.request_counter
            }
            self.log.debug("Received webhook request", context=_context)

            try:
                if self.rate_limiter.is_rate_limited(client_ip):
                    self.log.warning("Rate limit exceeded")
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit exceeded"
                    )

                if x_telegram_bot_api_secret_token != self.secret_token:
                    self.log.warning(
                        "Invalid secret token",
                        received_token=x_telegram_bot_api_secret_token
                    )
                    raise HTTPException(status_code=403, detail="Invalid secret token")

                self.request_counter += 1

                update_dict = update.model_dump(exclude_unset=True, by_alias=True)
                update_type = self._get_update_type(update)

                _update_context = {
                    "action": "process_update",
                    "update_type": update_type,
                    "update_id": update_dict.get('update_id')
                }
                self.log.debug("Processing update", context=_update_context)

                if self.request_counter > 1000:
                    self.log.warning(
                        "Request threshold reached",
                        total_requests=self.request_counter,
                        last_restart=self.last_restart
                    )
                    self.request_counter = 0
                    self.last_restart = datetime.now()

                update_obj = telebot.types.Update.de_json(update_dict)
                self.bot.process_new_updates([update_obj])

                self.log.debug("Update processed successfully")
                return JSONResponse(
                    status_code=200,
                    content={"status": "ok", "update_type": update_type}
                )

            except ValueError as e:
                self.log.error(
                    "Invalid update format",
                    error=str(e),
                    update_data=update.model_dump()
                )
                raise HTTPException(status_code=400, detail="Invalid update format")
            except Exception as e:
                self.log.error(
                    "Failed to process update",
                    error=str(e),
                    update_data=update.model_dump()
                )
                raise HTTPException(status_code=500, detail="Internal server error")

    def start(self) -> None:
        """Starts the webhook server."""
        _context = {
            "action": "start_server",
            "host": self.host,
            "port": self.port,
            "server_type": "uvicorn",
            "webhook_path": mask_token_in_message(self.webhook_path, self.token)
        }
        self.log.info("Initializing webhook server start", context=_context)

        if self.port < 1024:
            raise InitializationError(ErrorContext(
                message="Cannot run webhook server on privileged ports.",
                error_code="PRIVILEGED_PORT_ERROR",
                metadata={
                    "requested_port": self.port
                }
            ))

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

            _context = {
                "ssl_enabled": bool(cert_file and key_file),
                "ssl_cert_present": bool(cert_file),
                "ssl_key_present": bool(key_file),
                "config": uvicorn_config,
                "proxy_enabled": True,
                "workers_count": 1
            }
            self.log.info("Starting webhook server with configuration", context=_context)

            if cert_file and key_file:
                ssl_config = {
                    "ssl_certfile": cert_file,
                    "ssl_keyfile": key_file
                }
                uvicorn_config.update(ssl_config)
                self.log.debug("SSL configuration added to server config")

            self.log.info("Running uvicorn server")
            uvicorn.run(**uvicorn_config)

        except FileNotFoundError as e:
            raise InitializationError(ErrorContext(
                message="Failed to start webhook server - SSL certificate or key file not found",
                error_code="FILE_NOT_FOUND_ERROR",
                metadata={
                    "exception": e
                }
            ))

        except PermissionError as e:
            raise InitializationError(ErrorContext(
                message="Failed to start webhook server - Permission denied",
                error_code="PERMISSION_ERROR",
                metadata={
                    "exception": e
                }
            ))

        except OSError as e:
            raise InitializationError(ErrorContext(
                message="Failed to start webhook server - System error",
                error_code="OS_ERROR",
                metadata={
                    "exception": e
                }
            ))

        except Exception as e:
            self.log.exception(f"Failed to start webhook server: {e}")
            raise BotException(ErrorContext(
                message="Failed to start webhook server",
                error_code="UNEXPECTED_ERROR",
                metadata={
                    "error_class": e.__class__.__name__,
                    "exception": e
                }
            ))
