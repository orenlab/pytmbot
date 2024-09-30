import cherrypy
import telebot
from telebot import TeleBot
from pytmbot.logs import bot_logger


class CherryPyLogger:
    """
    Custom logger to redirect CherryPy logs to the bot_logger.
    """

    def debug(self, message, *args, **kwargs):
        bot_logger.debug(message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        bot_logger.info(message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        bot_logger.warning(message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        bot_logger.error(message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        bot_logger.critical(message, *args, **kwargs)

    def exception(self, message, *args, **kwargs):
        bot_logger.exception(message, *args, **kwargs)


class WebhookServer:
    """
    A CherryPy server for handling Telegram bot webhooks.

    This class exposes an endpoint for Telegram to send updates to
    the bot, processes incoming updates, and logs any exceptions.
    """

    def __init__(self, bot: TeleBot):
        """
        Initialize the WebhookServer with the given TeleBot instance.

        Args:
            bot (TeleBot): The instance of the Telegram bot to process updates.
        """
        self.bot = bot
        # Redirect CherryPy logs to bot_logger
        cherrypy.log.access_log.setHandler(CherryPyLogger())
        cherrypy.log.error_log.setHandler(CherryPyLogger())

    @cherrypy.expose
    def index(self):
        """
        Expose the index endpoint for receiving webhook requests from Telegram.

        This method reads the incoming JSON payload, processes the update, and
        logs any errors that occur during processing.

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
                # Process the JSON using Telebot types
                update = telebot.types.Update.de_json(json_string)
                self.bot.process_new_updates([update])
                return ''  # Return an empty string in response
            else:
                raise cherrypy.HTTPError(400, "Invalid Content-Type")
        except telebot.apihelper.ApiTelegramException as api_error:
            # Log Telegram API errors
            bot_logger.error(f"Telegram API error: {api_error}")
            raise cherrypy.HTTPError(400, "Bad Request")
        except Exception as error:
            # Log other errors and return 500 Internal Server Error
            bot_logger.exception(f"Failed to process webhook request: {error}")
            raise cherrypy.HTTPError(500, "Internal Server Error")