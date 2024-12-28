from collections import deque
from time import time
from typing import Dict

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
        if client_ip not in self.requests:
            self.requests[client_ip] = deque()

        request_times = self.requests[client_ip]
        while request_times and request_times[0] < current_time - self.period:
            request_times.popleft()

        if len(request_times) >= self.limit:
            return True

        request_times.append(current_time)
        return False


class WebhookUpdate(BaseModel):
    update_id: int
    message: Dict


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
            Process webhook calls.
            """
            try:
                if not update:
                    bot_logger.warning("No update found in the request.")
                    raise HTTPException(status_code=400, detail="Empty request payload")

                validated_update = WebhookUpdate(**update)
                bot_logger.debug(f"Received webhook update: {validated_update}")
                update_obj = telebot.types.Update.de_json(update)
                self.bot.process_new_updates([update_obj])
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
