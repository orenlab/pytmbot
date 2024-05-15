#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from time import sleep

from requests.exceptions import (
    ReadTimeout,
    HTTPError,
    ConnectionError)

from app import (
    __version__,
    __repository__,
    bot,
    bot_logger,
    telebot
)
from app.core.handlers.handlers_aggregator import HandlersAggregator
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
                self.bot.stop_polling()
                bot_logger.debug(f"Connection error: {e}. Retry after {self.sleep_time} seconds")
                bot_logger.error(f'Connection error. Retry after {self.sleep_time} seconds')
                sleep(self.sleep_time)
                continue
            except telebot.apihelper.ApiTelegramException as e:
                self.bot.stop_polling()
                bot_logger.debug(f'Telegram API error: {e}. Connection attempt after {self.sleep_time} seconds.')
                bot_logger.error(f'Telegram API error. Connection attempt after {self.sleep_time} seconds.')
                sleep(self.sleep_time)
                continue
            except Exception as e:
                self.bot.stop_polling()
                bot_logger.debug(f"Unexpected exception: {e}. Unable to perform an automatic restart. Shutdown bot ")
                bot_logger.error("Unexpected exception. Unable to perform an automatic restart. Shutdown bot")
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
