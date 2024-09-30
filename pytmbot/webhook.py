import cherrypy
import telebot
from telebot import TeleBot

from pytmbot.logs import bot_logger


class WebhookServer:
    def __init__(self, bot: TeleBot):
        self.bot = bot

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def webhook(self):
        """
        Receives updates from Telegram and processes them.
        """
        try:
            # Retrieve the JSON payload from the request
            payload = cherrypy.request.json
            if payload:
                # Process the update
                self.bot.process_new_updates([telebot.types.Update.de_json(payload)])
            return "OK", 200
        except Exception as e:
            bot_logger.error(f"Error processing webhook: {e}")
            return "Error", 500
