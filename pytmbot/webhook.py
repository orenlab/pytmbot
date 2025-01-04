from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from time import time
from typing import Dict, Annotated, AsyncGenerator

import telebot
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.responses import JSONResponse

from pytmbot.exceptions import InitializationError, ErrorContext, ShutdownError, BotException
from pytmbot.globals import settings
from pytmbot.logs import BaseComponent
from pytmbot.models.telegram_models import TelegramIPValidator
from pytmbot.models.updates_model import UpdateModel
from pytmbot.utils.utilities import generate_secret_token, mask_token_in_message


class RateLimit(BaseComponent):
    def __init__(self, limit: int, period: int, ban_threshold: int = 50) -> None:
        super().__init__()

        with self.log_context(limit=limit, period=period, ban_threshold=ban_threshold) as log:
            log.debug("Initializing rate limit")
            self.limit = limit
            self.period = period
            self.ban_threshold = ban_threshold
            self.requests: Dict[str, deque[float]] = {}
            self.banned_ips: Dict[str, datetime] = {}

    def is_banned(self, client_ip: str) -> bool:
        with self.log_context(ip=client_ip, action="check_ban"):
            if client_ip not in self.banned_ips:
                return False

            ban_time = self.banned_ips[client_ip]
            if (datetime.now() - ban_time).total_seconds() > 3600:
                with self.log_context(action="ban_expired", ip=client_ip) as log:
                    log.info("Ban expired, removing IP from banned list")
                del self.banned_ips[client_ip]
                return False
            with self.log_context(action="banned", ip=client_ip) as log:
                log.warning("Request from banned IP rejected")
            return True

    def is_rate_limited(self, client_ip: str) -> bool:
        with self.log_context(
                ip=client_ip,
                action="rate_check",
                requests_count=len(self.requests.get(client_ip, []))
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
                    log.warning("IP banned for excessive requests")
                return True

            if len(request_times) >= self.limit:
                with self.log_context(action="rate_limit", ip=client_ip) as log:
                    log.warning("Rate limit exceeded")
                return True

            request_times.append(current_time)
            return False


from typing import Optional
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException


class WebhookManager(BaseComponent):
    def __init__(self, bot: TeleBot, url: str, port: int, secret_token: Optional[str] = None) -> None:
        super().__init__("webhook_manager")
        self.bot = bot
        self.url = url
        self.port = port
        self.secret_token = secret_token

        with self.log_context(
                webhook_url=mask_token_in_message(url, bot.token),
                port=port,
                has_secret_token=bool(secret_token)
        ) as log:
            log.debug("Webhook manager initialized")

    def setup_webhook(self, webhook_path: str) -> None:
        webhook_url = f"https://{self.url}:{self.port}{webhook_path}"
        cert_path = settings.webhook_config.cert[0].get_secret_value() or None

        with self.log_context(
                action="setup_webhook",
                webhook_path=mask_token_in_message(webhook_path, self.bot.token)
        ) as log:
            try:
                current_webhook = self.bot.get_webhook_info()
                log.debug(
                    "Current webhook configuration",
                    webhook_info=current_webhook,
                    cert_present=bool(cert_path)
                )

                self.remove_webhook()

                self.bot.set_webhook(
                    url=webhook_url,
                    timeout=20,
                    allowed_updates=['message', 'edited_message', 'inline_query', 'callback_query'],
                    drop_pending_updates=True,
                    certificate=cert_path,
                    secret_token=self.secret_token
                )

                new_webhook = self.bot.get_webhook_info()
                log.info(
                    "Webhook successfully configured",
                    old_webhook=current_webhook,
                    new_webhook=new_webhook
                )

            except ApiTelegramException as e:
                error_context = ErrorContext(
                    message="Webhook setup failed",
                    error_code="WEBHOOK_SETUP_FAILED",
                    metadata={"exception": str(e)}
                )
                log.exception(
                    "Failed to setup webhook",
                    error=error_context.dict()
                )
                raise InitializationError(error_context)

    def remove_webhook(self) -> None:
        with self.log_context(action="remove_webhook") as log:
            try:
                current_webhook = self.bot.get_webhook_info()
                log.debug("Removing webhook", current_webhook=current_webhook)

                self.bot.remove_webhook()

                new_webhook = self.bot.get_webhook_info()
                log.debug(
                    "Webhook removed",
                    old_webhook=current_webhook,
                    new_webhook=new_webhook
                )

            except ApiTelegramException as e:
                error_context = ErrorContext(
                    message="Failed to remove webhook",
                    error_code="WEBHOOK_REMOVE_FAILED",
                    metadata={"exception": str(e)}
                )
                log.exception(
                    "Webhook removal failed",
                    error=error_context.dict()
                )
                raise InitializationError(error_context)


class WebhookServer(BaseComponent):
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
                webhook_path=mask_token_in_message(self.webhook_path, self.token)
        ) as log:
            log.debug("Initializing webhook server components")

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
            log.info("Webhook server initialized successfully")

    def _create_app(self) -> FastAPI:
        @asynccontextmanager
        def lifespan(fastapi_app: FastAPI) -> AsyncGenerator[None, None]:
            with self.log_context(
                    action="server_lifecycle",
                    webhook_path=mask_token_in_message(self.webhook_path, self.token)
            ) as log:
                try:
                    log.info("Starting webhook server lifecycle")
                    self.webhook_manager.setup_webhook(self.webhook_path)
                    yield
                except Exception as e:
                    error_context = ErrorContext(
                        message="Webhook lifecycle error",
                        error_code="WEBHOOK_LIFECYCLE_ERROR",
                        metadata={"exception": str(e)}
                    )
                    log.exception("Failed to initialize webhook lifecycle", error=error_context.dict())
                    raise InitializationError(error_context)
                finally:
                    try:
                        self.webhook_manager.remove_webhook()
                        log.info("Webhook server shutdown completed")
                    except Exception as e:
                        error_context = ErrorContext(
                            message="Error during webhook cleanup",
                            error_code="WEBHOOK_CLEANUP_ERROR",
                            metadata={"exception": str(e)}
                        )
                        log.exception("Failed to cleanup webhook", error=error_context.dict())
                        raise ShutdownError(error_context)

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
        return next((field for field in update_types if getattr(update, field) is not None), "unknown")

    def _setup_routes(self, app: FastAPI) -> None:
        with self.log_context(action="route_setup") as log:
            log.debug("Configuring FastAPI routes")

            @app.exception_handler(404)
            def not_found_handler(request: Request) -> JSONResponse:
                client_ip = request.client.host
                with self.log_context(
                        action="handle_404",
                        client_ip=client_ip,
                        request_url=str(request.url)
                ) as _log:
                    if self.rate_limiter_404.is_rate_limited(client_ip):
                        _log.warning("Rate limit exceeded for 404 requests")
                        return JSONResponse(status_code=429, content={"detail": "Too many not found requests"})

                    log.warning("404 request received")
                    return JSONResponse(status_code=404, content={"detail": "Not found"})

            def verify_telegram_ip(
                    request: Request,
                    x_forwarded_for: Annotated[str | None, Header()] = None
            ) -> str:
                client_ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.client.host

                with self.log_context(
                        action="ip_verification",
                        client_ip=client_ip,
                        x_forwarded_for=x_forwarded_for
                ) as _log:
                    if not self.telegram_ip_validator.is_telegram_ip(client_ip):
                        _log.warning(
                            "Non-Telegram IP request blocked",
                        )
                        raise HTTPException(
                            status_code=403,
                            detail="Access denied: Request must come from Telegram servers"
                        )
                    log.debug("Telegram IP verified successfully")
                    return client_ip

            @app.post(self.webhook_path)
            def process_webhook(
                    update: UpdateModel,
                    client_ip: Annotated[str, Depends(verify_telegram_ip)],
                    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None
            ) -> JSONResponse:
                with self.log_context(
                        action="webhook_processing",
                        client_ip=client_ip,
                        request_counter=self.request_counter
                ) as _log:
                    try:
                        # Rate limiting check
                        if self.rate_limiter.is_rate_limited(client_ip):
                            _log.warning(
                                "Rate limit exceeded",
                            )
                            raise HTTPException(status_code=429, detail="Rate limit exceeded")

                        # Token verification
                        if x_telegram_bot_api_secret_token != self.secret_token:
                            _log.warning("Invalid secret token received")
                            raise HTTPException(status_code=403, detail="Invalid secret token")

                        # Update processing
                        self.request_counter += 1
                        update_dict = update.model_dump(exclude_unset=True, by_alias=True)
                        update_type = self._get_update_type(update)

                        # Request counter threshold check
                        if self.request_counter > 1000:
                            _log.warning(
                                "Request threshold reached",
                                total_requests=self.request_counter,
                                last_restart=self.last_restart.isoformat(),
                                uptime=(datetime.now() - self.last_restart).total_seconds()
                            )
                            self.request_counter = 0
                            self.last_restart = datetime.now()

                        # Process update
                        with self.log_context(
                                action="update_processing",
                                update_type=update_type,
                                update_id=update_dict.get('update_id')
                        ) as update_log:
                            update_log.debug("Processing Telegram update")
                            update_obj = telebot.types.Update.de_json(update_dict)
                            self.bot.process_new_updates([update_obj])
                            update_log.debug("Update processed successfully")

                        return JSONResponse(
                            status_code=200,
                            content={"status": "ok", "update_type": update_type}
                        )

                    except ValueError as e:
                        log.error(
                            "Invalid update format",
                            error=str(e),
                            update_data=update.model_dump()
                        )
                        raise HTTPException(status_code=400, detail="Invalid update format")
                    except Exception as e:
                        log.error(
                            "Update processing failed",
                            error=str(e),
                            error_type=type(e).__name__,
                            update_data=update.model_dump()
                        )
                        raise HTTPException(status_code=500, detail="Internal server error")

    def start(self) -> None:
        with self.log_context(
                action="server_startup",
                host=self.host,
                port=self.port,
                webhook_path=mask_token_in_message(self.webhook_path, self.token)
        ) as log:
            # Port validation
            if self.port < 1024:
                error_context = ErrorContext(
                    message="Cannot run webhook server on privileged ports",
                    error_code="PRIVILEGED_PORT_ERROR",
                    metadata={"requested_port": self.port}
                )
                log.error("Privileged port access attempted", error=error_context.dict())
                raise InitializationError(error_context)

            try:
                # SSL configuration
                cert_file = settings.webhook_config.cert[0].get_secret_value()
                key_file = settings.webhook_config.cert_key[0].get_secret_value()

                uvicorn_config = {
                    "app": self.app,
                    "host": self.host,
                    "port": self.port,
                    "log_level": "debug",
                    "access_log": False,
                    "proxy_headers": True,
                    "forwarded_allow_ips": "*",
                    "workers": 1
                }

                # Server configuration logging
                with self.log_context(
                        ssl_enabled=bool(cert_file and key_file),
                        ssl_cert_present=bool(cert_file),
                        ssl_key_present=bool(key_file),
                        proxy_enabled=True,
                        workers_count=1
                ) as config_log:
                    if cert_file and key_file:
                        uvicorn_config.update({
                            "ssl_certfile": cert_file,
                            "ssl_keyfile": key_file
                        })
                        config_log.debug("SSL configuration enabled")

                    config_log.info("Starting uvicorn server with configuration")
                    uvicorn.run(**uvicorn_config)

            except FileNotFoundError as e:
                error_context = ErrorContext(
                    message="SSL certificate or key file not found",
                    error_code="FILE_NOT_FOUND_ERROR",
                    metadata={"exception": str(e)}
                )
                log.exception("SSL files not found", error=error_context.dict())
                raise InitializationError(error_context)

            except PermissionError as e:
                error_context = ErrorContext(
                    message="Permission denied while starting server",
                    error_code="PERMISSION_ERROR",
                    metadata={"exception": str(e)}
                )
                log.exception("Permission error on server start", error=error_context.dict())
                raise InitializationError(error_context)

            except OSError as e:
                error_context = ErrorContext(
                    message="System error while starting server",
                    error_code="OS_ERROR",
                    metadata={"exception": str(e)}
                )
                log.exception("OS error on server start", error=error_context.dict())
                raise InitializationError(error_context)

            except Exception as e:
                error_context = ErrorContext(
                    message="Failed to start webhook server",
                    error_code="UNEXPECTED_ERROR",
                    metadata={
                        "error_class": e.__class__.__name__,
                        "exception": str(e)
                    }
                )
                log.exception("Unexpected error on server start", error=error_context.dict())
                raise BotException(error_context)
