import cherrypy
import telebot
from telebot import TeleBot

from pytmbot.logs import bot_logger


class WebhookServer:
    def __init__(self, bot: TeleBot):
        self.bot = bot

    @cherrypy.expose
    def index(self):
        request = cherrypy.request
        if request.headers.get('content-type') == 'application/json':
            json_string = request.body.read().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            self.bot.process_new_updates([update])
            return ''
        raise cherrypy.HTTPError(403)

