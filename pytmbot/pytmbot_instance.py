#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import time

import telebot

from pytmbot import exceptions
from pytmbot.globals import settings, var_config, __version__, __repository__
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
    # Parse command line arguments to get the bot mode
    bot_mode = parse_cli_args()

    # Log the bot mode for debugging purposes
    bot_logger.debug(f"Operational bot mode: {bot_mode.mode}")

    # Return the appropriate bot token based on the bot mode
    return (
        settings.bot_token.dev_bot_token[0].get_secret_value()  # If bot mode is "dev", return the dev bot token
        if bot_mode.mode == "dev"
        else settings.bot_token.prod_token[0].get_secret_value()  # Otherwise, return the regular bot token
    )


def __create_bot_instance():
    """
    Create the bot instance.

    Returns:
        telebot.TeleBot: The created bot instance.
    """
    try:
        bot_token = __get_bot_token()
    except (FileNotFoundError, ValueError) as error:
        raise exceptions.PyTMBotError(".pytmbotenv file is not valid or not found") from error

    bot_logger.debug("Bot token setup successful")

    # Create the bot instance
    bot = telebot.TeleBot(
        token=bot_token,
        threaded=True,
        use_class_middlewares=True,
        exception_handler=exceptions.TelebotCustomExceptionHandler(),
        skip_pending=True,
    )

    bot_logger.debug("Bot instance created")

    bot_logger.debug("Now we need to test the bot token...")

    # Test the bot token
    try:
        test_bot = bot.get_me()
    except (telebot.apihelper.ApiTelegramException, ConnectionError) as error:
        if isinstance(error, telebot.apihelper.ApiTelegramException):
            error_message = "Bot token is not valid. Please check the token and try again."
        else:
            error_message = "Connection to the Telegram API failed."
        raise exceptions.PyTMBotError(error_message) from error

    bot_logger.debug("Bot token is valid.")
    bot_logger.debug(f"Bot info: {test_bot}.")

    commands = [telebot.types.BotCommand(command, desc) for command, desc in var_config.bot_commands.items()]
    # Set up the bot commands
    try:
        bot.set_my_commands(commands)
        bot_logger.debug(f"Bot commands setup successful with {len(commands)} commands.")

        bot.set_my_description(var_config.description)
        bot_logger.debug("Bot description setup successful.")
    except telebot.apihelper.ApiTelegramException as error:
        bot_logger.error(f"Error setting up bot commands and description: {error}")

    bot_logger.debug("Basic configuration done. We are now continuing with...")
    # Set up the middleware
    try:
        bot_logger.debug("Setting up middleware...")
        bot.setup_middleware(AccessControl())
        bot_logger.debug(f"Middleware setup successful: {AccessControl.__name__}.")
    except telebot.apihelper.ApiTelegramException as error:
        bot_logger.error(f"Failed at @{__name__}: {error}")

    bot_logger.debug("Registering message handlers...")
    # Register the message handlers
    try:
        for handlers in handler_factory().values():
            for handler in handlers:
                bot.register_message_handler(handler.callback, **handler.kwargs, pass_bot=True)
    except Exception as err:
        raise exceptions.PyTMBotError(f"Failed to register handlers: {err}")
    bot_logger.debug(f"Registered {len(handler_factory())} message handlers.")

    bot_logger.debug("Registering inline message handlers...")
    # Register the inline message handlers
    try:
        for handlers in inline_handler_factory().values():
            for handler in handlers:
                bot.register_callback_query_handler(handler.callback, **handler.kwargs, pass_bot=True)
    except Exception as err:
        raise exceptions.PyTMBotError(f"Failed to register inline handlers: {err}")
    bot_logger.debug(f"Registered {len(inline_handler_factory())} inline message handlers.")

    bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")

    # Return the bot instance
    return bot


def start_bot_instance():
    """
    Start the bot instance.
    """
    bot_instance = __create_bot_instance()

    # Start the bot
    bot_logger.info("Starting polling............")

    try:
        bot_instance.infinity_polling(
            skip_pending=True,
            timeout=var_config.bot_polling_timeout,
            long_polling_timeout=var_config.bot_long_polling_timeout
        )
    except telebot.apihelper.ApiTelegramException as error:
        bot_logger.error(f"Failed at @{__name__}: {error}")
        time.sleep(10)
        return
