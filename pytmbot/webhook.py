from collections import deque
from functools import cached_property
from time import time
from typing import Optional, Dict

import telebot
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from telebot import TeleBot

from pytmbot.exceptions import PyTMBotError
from pytmbot.globals import settings
from pytmbot.logs import bot_logger


class RateLimit404:
    def __init__(self, limit: int, period: int):
        """
        Initializes the rate limiter for 404 requests.
        """
        self.limit = limit
        self.period = period
        self.requests: Dict[str, deque] = {}

    def is_rate_limited(self, client_ip: str) -> bool:
        """
        Checks if a client IP exceeds the rate limit for 404 errors.
        """
        current_time = time()
        request_times = self.requests.setdefault(client_ip, deque())

        while request_times and request_times[0] < current_time - self.period:
            request_times.popleft()

        if len(request_times) >= self.limit:
            return True

        request_times.append(current_time)
        return False


# Define Pydantic models for strict validation
class Message(BaseModel):
    message_id: int
    text: Optional[str]


class InlineQuery(BaseModel):
    id: str
    query: str
    offset: str


class CallbackQuery(BaseModel):
    id: str
    data: Optional[str]
    message: Optional[Message]


class WebhookUpdate(BaseModel):
    update_id: int
    message: Optional[Message]
    inline_query: Optional[InlineQuery]
    callback_query: Optional[CallbackQuery]


class WebhookServer:
    def __init__(self, bot: TeleBot, token: str, host: str, port: int):
        """
        Initializes the FastAPI webhook server.
        """
        self.bot = bot
        self.token = token
        self.host = host
        self.port = port
        self.app = FastAPI(
            docs_url=None, redoc_url=None, title="PyTMBot Webhook Server", version="0.1.0"
        )
        self.rate_limiter = RateLimit404(limit=8, period=10)
        self._setup_routes()

    @cached_property
    def hashed_token(self) -> str:
        """
        Returns a hashed version of the token for added security.
        """
        import hashlib
        return hashlib.sha256(self.token.encode()).hexdigest()

    def _setup_routes(self):
        """
        Set up routes and handlers.
        """

        @self.app.exception_handler(404)
        async def not_found_handler(request: Request, exc: HTTPException):
            client_ip = request.client.host
            if self.rate_limiter.is_rate_limited(client_ip):
                return JSONResponse(
                    status_code=429, content={"detail": "Rate limit exceeded"}
                )
            return JSONResponse(
                status_code=404,
                content={"detail": "Endpoint not found or method not allowed"},
            )

        @self.app.post(f"/webhook/{self.token}/")
        async def process_webhook(update: dict):
            """
            Process webhook calls using validated models and telebot.types.Update.de_json.
            """
            try:
                # Validate update using Pydantic
                validated_update = WebhookUpdate(**update)
                bot_logger.debug(f"Validated update: {validated_update.model_dump_json()}")

                # Deserialize using telebot for processing
                update_obj = telebot.types.Update.de_json(update)

                # Handle updates based on their type
                match validated_update:
                    case _ if validated_update.message:
                        bot_logger.info(f"Processing message: {validated_update.message.message_id}")
                        self.bot.process_new_updates([update_obj])

                    case _ if validated_update.inline_query:
                        bot_logger.info(f"Processing inline query: {validated_update.inline_query.id}")
                        self.bot.process_new_updates([update_obj])

                    case _ if validated_update.callback_query:
                        bot_logger.info(f"Processing callback query: {validated_update.callback_query.id}")
                        self.bot.process_new_updates([update_obj])

                    case _:
                        bot_logger.warning("Unsupported update type received.")
                        return {"status": "no_action"}

                return {"status": "ok"}

            except ValidationError as ve:
                bot_logger.error(f"Validation error: {ve}")
                raise HTTPException(status_code=400, detail="Invalid request format")

            except Exception as e:
                bot_logger.error(f"Failed to process update: {e}")
                raise HTTPException(status_code=500, detail="Internal Server Error")

    def run(self):
        """
        Starts the FastAPI application.
        """
        if self.port == 80:
            bot_logger.critical(
                "Cannot run webhook server on port 80 for security reasons. Use reverse proxy instead."
            )
            raise PyTMBotError(
                "Cannot run webhook server on port 80 for security reasons. Use reverse proxy instead."
            )

        bot_logger.info(
            f"Starting FastAPI webhook server on {self.host}:{self.port}..."
        )

        try:
            uvicorn.run(
                self.app,
                host=self.host,
                port=self.port,
                ssl_certfile=settings.webhook_config.cert[0].get_secret_value(),
                ssl_keyfile=settings.webhook_config.cert_key[0].get_secret_value(),
                log_level="critical",
                access_log=False,
            )
        except Exception as e:
            bot_logger.critical(f"Failed to start FastAPI server: {e}")
            raise
