#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import time

import telebot

from pytmbot import exceptions
from pytmbot.globals import (
    settings,
    __version__,
    __repository__,
    bot_command_settings,
    bot_description_settings,
    var_config
)
from pytmbot.handlers.handler_manager import handler_factory, inline_handler_factory
from pytmbot.logs import bot_logger
from pytmbot.middleware.access_control import AccessControl
from pytmbot.utils.utilities import parse_cli_args


def __get_bot_token():
    """
    Get the bot token based on the bot mode from the command line arguments.
    Returns:
        str: The bot token.
    """
    bot_mode = parse_cli_args()
    bot_logger.debug(f"Operational bot mode: {bot_mode.mode}")

    try:
        return (
            settings.bot_token.dev_bot_token[0].get_secret_value()
            if bot_mode.mode == "dev"
            else settings.bot_token.prod_token[0].get_secret_value()
        )
    except (FileNotFoundError, ValueError) as error:
        raise exceptions.PyTMBotError(".pytmbotenv file is not valid or not found") from error


def __create_bot_instance():
    """
    Create the bot instance.
    Returns:
        telebot.TeleBot: The created bot instance.
    """
    bot_token = __get_bot_token()
    bot_logger.debug("Bot token setup successful")

    bot = telebot.TeleBot(
        token=bot_token,
        threaded=True,
        use_class_middlewares=True,
        exception_handler=exceptions.TelebotCustomExceptionHandler(),
        skip_pending=True,
    )
    bot_logger.debug("Bot instance created")

    # Test the bot token
    try:
        test_bot = bot.get_me()
        bot_logger.debug(f"Bot info: {test_bot}.")
    except telebot.apihelper.ApiTelegramException:
        error_message = "Bot token is not valid. Please check the token and try again."
        raise exceptions.PyTMBotError(error_message)
    except ConnectionError:
        raise exceptions.PyTMBotError("Connection to the Telegram API failed.")

    # Set up bot commands and description
    try:
        commands = [telebot.types.BotCommand(command, desc) for command, desc in
                    bot_command_settings.bot_commands.items()]
        bot.set_my_commands(commands)
        bot.set_my_description(bot_description_settings.bot_description)
        bot_logger.debug("Bot commands and description setup successful.")
    except telebot.apihelper.ApiTelegramException as error:
        bot_logger.error(f"Error setting up bot commands and description: {error}")

    # Set up middleware
    try:
        bot.setup_middleware(AccessControl(bot=bot))
        bot_logger.debug(f"Middleware setup successful: {AccessControl.__name__}.")
    except telebot.apihelper.ApiTelegramException as error:
        bot_logger.error(f"Failed at @{__name__}: {error}")

    # Register message and inline handlers
    try:
        bot_logger.debug("Registering message handlers...")
        for handlers in handler_factory().values():
            for handler in handlers:
                bot.register_message_handler(handler.callback, **handler.kwargs, pass_bot=True)
        bot_logger.debug(f"Registered {len(handler_factory())} message handlers.")

        bot_logger.debug("Registering inline message handlers...")
        for handlers in inline_handler_factory().values():
            for handler in handlers:
                bot.register_callback_query_handler(handler.callback, **handler.kwargs, pass_bot=True)
        bot_logger.debug(f"Registered {len(inline_handler_factory())} inline message handlers.")
    except Exception as err:
        raise exceptions.PyTMBotError(f"Failed to register handlers: {err}")

    bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")
    return bot


def start_bot_instance():
    """
    Start the bot instance.
    """
    bot_instance = __create_bot_instance()
    bot_logger.info("Starting polling............")

    while True:
        try:
            bot_instance.infinity_polling(
                skip_pending=True,
                timeout=var_config.bot_polling_timeout,
                long_polling_timeout=var_config.bot_long_polling_timeout
            )
        except telebot.apihelper.ApiTelegramException as error:
            bot_logger.error(f"Polling failed: {error}")
            time.sleep(10)
        except Exception as error:
            bot_logger.error(f"Unexpected error: {error}")
            time.sleep(10)
