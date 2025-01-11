#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.plugin_manager import PluginManager

logger = Logger()
plugin_manager = PluginManager()


@logger.session_decorator
def handle_plugins(message: Message, bot: TeleBot) -> None:
    """
    Handle the plugin menu for the bot.

    Parameters:
        message (Message): A message object received from the user.
        bot (TeleBot): The bot instance.

    Returns:
        None
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")

        # Fetch plugin information
        keys = plugin_manager.get_merged_index_keys()
        plugin_names = plugin_manager.get_plugin_names()

        # Check if there are any plugins available
        if not plugin_names:
            first_name: str = message.from_user.first_name

            send_telegram_message(
                bot=bot,
                chat_id=message.chat.id,
                text=f"⚠️ {first_name}, there are no plugins available...",
                parse_mode="Markdown"
            )
            return

        # Continue with normal plugin handling if plugins exist
        plugin_descriptions = plugin_manager.get_plugin_descriptions()

        # Create plugin information dictionary
        plugins = {
            name: plugin_descriptions.get(name, "No description available")
            for name in plugin_names
        }

        # Build the keyboard
        plugins_keyboard = keyboards.build_reply_keyboard(plugin_keyboard_data=keys)

        first_name: str = message.from_user.first_name
        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
        }

        # Compile the response using the template
        with Compiler(
                template_name="b_plugins.jinja2",
                first_name=first_name,
                plugins=plugins,
                **emojis,
        ) as compiler:
            response = compiler.compile()

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=response,
            reply_markup=plugins_keyboard,
            parse_mode="Markdown"
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the plugins command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling plugins",
            error_code="HAND_015",
            metadata={"exception": str(error)}
        ))
