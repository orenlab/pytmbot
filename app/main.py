#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from app import (
    __version__,
    __repository__,
    logger,
    bot
)
from app.core.handlers.handlers_aggregator import HandlersAggregator
import app.core.exceptions as exceptions
from app.core.middleware.auth import AllowedUser


class PyTMBot:
    """Main PyTMBot class"""

    def __init__(self):
        """Initialize the PyTMBot class"""
        self.log = logger
        self.bot = bot
        self.handler = HandlersAggregator(self.bot)

    def run_bot(self):
        """Run the bot"""
        try:
            self.bot.setup_middleware(AllowedUser())
            self.handler.run_handlers()
            self.log.info(f"New instance started! PyTMBot v.{__version__} ({__repository__})")
            self.bot.infinity_polling()
        except ConnectionError:
            self.log.critical('Error connecting to Telegram API')
            self.bot.stop_polling()
            self.log.critical('PyTMBot stopped...')
            raise exceptions.PyTeleMonBotConnectionError('Error connecting to Telegram API')


if __name__ == "__main__":
    # Run bot!
    PyTMBot().run_bot()
