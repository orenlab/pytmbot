#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.globals import psutil_adapter, keyboards, em
from pytmbot.logs import logged_handler_session, bot_logger
from pytmbot.parsers.compiler import Compiler


# regexp="Memory load"
@logged_handler_session
def handle_memory(message: Message, bot: TeleBot):
    """
    Handle the "Memory load" command.

    This function sends a typing action to the chat, retrieves the memory load info,
    renders a template with the retrieved info, and sends the rendered template
    with an inline button to the chat.
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")
        memory_info = psutil_adapter.get_memory()
        if memory_info is None:
            bot_logger.error(
                f"Failed at {__name__}: Error occurred while getting memory info"
            )
            return bot.send_message(
                message.chat.id, text="Some error occurred. Please try again later("
            )

        button_data = keyboards.ButtonData(
            text="Swap info", callback_data="__swap_info__"
        )
        keyboard = keyboards.build_inline_keyboard(button_data)

        with Compiler(
                template_name="b_memory.jinja2",
                context=memory_info,
                thought_balloon=em.get_emoji("thought_balloon"),
                abacus=em.get_emoji("abacus"),
        ) as compiler:
            bot_answer = compiler.compile()

        return bot.send_message(
            message.chat.id,
            text=bot_answer,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
