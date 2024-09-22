#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot import exceptions
from pytmbot.globals import em
from pytmbot.logs import logged_inline_handler_session
from pytmbot.parsers.compiler import Compiler


# func=lambda call: call.data == '__how_update__'
@logged_inline_handler_session
def handle_update_info(call: CallbackQuery, bot: TeleBot):
    """
    Handle the 'check_update_info' command

    Args:
        call (CallbackQuery): The callback query received by the bot.
        bot (TeleBot): The bot instance.

    Returns:
        None
    """
    emojis = {"thought_balloon": em.get_emoji("thought_balloon")}

    try:
        with Compiler(template_name="b_how_update.jinja2", **emojis) as compiler:
            bot_answer = compiler.compile()

        return bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=bot_answer,
            parse_mode="Markdown",
        )
    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
