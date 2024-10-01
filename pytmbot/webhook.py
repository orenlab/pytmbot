import telebot
from fastapi import FastAPI, HTTPException
from telebot import TeleBot

from pytmbot.globals import settings
from pytmbot.logs import bot_logger


class WebhookServer:

    def __init__(self, bot: TeleBot, token: str, host: str, port: int):
        """
        Initializes the FastAPI webhook server.

        Args:
            bot (TeleBot): The instance of the Telegram bot.
            token (str): The Telegram bot token.
            host (str): The host for the server.
            port (int): The port for the server.
        """
        self.bot = bot
        self.token = token
        self.app = FastAPI(docs=None, redoc_url=None, title="PyTMBot Webhook Server", version="0.1.0")
        self.host = host
        self.port = port

        @self.app.post(f"/webhook/{self.token}/")
        def process_webhook(update: dict):
            """
            Process webhook calls
            """
            try:
                if update:
                    bot_logger.debug(f"Received webhook update: {update}")
                    update = telebot.types.Update.de_json(update)
                    self.bot.process_new_updates([update])
                else:
                    bot_logger.warning("No update found in the request.")
                    raise HTTPException(status_code=400, detail="Bad Request")

                return {"status": "ok"}
            except Exception as e:
                bot_logger.error(f"Failed to process update: {e}")
                raise HTTPException(status_code=500, detail="Internal Server Error")

    def run(self):
        """
        Starts the FastAPI application.
        """
        import uvicorn

        # Start the server with error handling
        try:
            bot_logger.info(f"Starting FastAPI webhook server on {self.host}:{self.port}...")

            uvicorn.run(
                self.app,
                host=self.host,
                port=self.port,
                ssl_certfile=settings.webhook_config.cert[0].get_secret_value(),
                ssl_keyfile=settings.webhook_config.cert_key[0].get_secret_value(),
                log_level="critical",
                use_colors=True
            )
        except Exception as e:
            bot_logger.critical(f"Failed to start FastAPI server: {e}")
            raise
