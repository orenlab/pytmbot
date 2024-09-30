import cherrypy
import telebot
from telebot import TeleBot
from pytmbot.logs import bot_logger


class WebhookServer:
    """
    A CherryPy server for handling Telegram bot webhooks.
    """

    def __init__(self, bot: TeleBot):
        """
        Initialize the WebhookServer with the given TeleBot instance.

        Args:
            bot (TeleBot): The instance of the Telegram bot to process updates.
        """
        self.bot = bot
        # Redirect CherryPy logs to bot_logger
        cherrypy.log.access_log.addHandler(bot_logger)
        cherrypy.log.error_log.addHandler(bot_logger)

    @cherrypy.expose
    def index(self):
        """
        Expose the index endpoint for receiving webhook requests from Telegram.

        Raises:
            cherrypy.HTTPError: If the request method is not POST or if there is an error
                                while processing the request.
        """
        # Ensure that the method allows only POST requests
        if cherrypy.request.method != 'POST':
            raise cherrypy.HTTPError(405, "Method Not Allowed")

        try:
            request = cherrypy.request
            if request.headers.get('content-type') == 'application/json':
                json_string = request.body.read().decode('utf-8')
                update = telebot.types.Update.de_json(json_string)
                self.bot.process_new_updates([update])
                return ''  # Return an empty string in response
            else:
                raise cherrypy.HTTPError(400, "Invalid Content-Type")
        except telebot.apihelper.ApiTelegramException as api_error:
            bot_logger.error(f"Telegram API error: {api_error}")
            raise cherrypy.HTTPError(400, "Bad Request")
        except Exception as error:
            bot_logger.exception(f"Failed to process webhook request: {error}")
            raise cherrypy.HTTPError(500, "Internal Server Error")
