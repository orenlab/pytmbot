#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from requests.exceptions import ReadTimeout, HTTPError, ConnectionError
from time import sleep
from telebot import apihelper

from app import (
    __version__,
    __repository__,
    bot,
    bot_logger,
)

from app.core.handlers.handlers_aggregator import HandlersAggregator
import app.core.exceptions as exceptions
from app.core.middleware.auth import AllowedUser


class PyTMBot:
    """Main PyTMBot class"""

    def __init__(self):
        """Initialize the PyTMBot class"""
        self.bot = bot
        self.handler = HandlersAggregator(self.bot)
        self.sleep_time: int = 0

    def start_polling(self):
        """Start bot polling"""
        while True:
            try:
                self.sleep_time += 5  # The time in seconds that we sleep for after each cycle.
                bot_logger.info('Start polling')
                self.bot.polling(timeout=60, long_polling_timeout=60, none_stop=True, skip_pending=True)
            except (ReadTimeout, HTTPError, ConnectionError) as e:
                bot_logger.debug(f"Connection error: {e}. Retry after {self.sleep_time} seconds")
                bot_logger.error("Connection error.")
                self.bot.stop_polling()
                bot_logger.error(f'PyTMBot stopped... Connection attempt after {self.sleep_time} seconds.')
                sleep(self.sleep_time)
                continue
            except apihelper.ApiTelegramException as e:
                bot_logger.debug(f'Telegram API error: {e}')
                bot_logger.error(f'Telegram API error. Connection attempt after {self.sleep_time} seconds.')
                self.bot.stop_polling()
                continue
            except Exception as e:
                bot_logger.debug(f"Unexpected exception: {e}")
                bot_logger.error("Unexpected exception")
                self.bot.stop_polling()
                bot_logger.error('PyTMBot stopped... Unable to perform an automatic restart. Shutdown bot')
            break

    def run_bot(self):
        """Run the bot"""
        try:
            self.bot.setup_middleware(AllowedUser())
            self.handler.run_handlers()
            bot_logger.info(f"New instance started! PyTMBot v.{__version__} ({__repository__})")
            self.start_polling()
        except ConnectionError:
            bot_logger.error("Connection error.")


if __name__ == "__main__":
    # Run bot!
    PyTMBot().run_bot()
