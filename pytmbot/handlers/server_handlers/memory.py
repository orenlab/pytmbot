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
from pytmbot.globals import psutil_adapter, keyboards, em, button_data
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# regexp="Memory load"
@logger.session_decorator
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
            logger.error(
                f"Failed at {__name__}: Error occurred while getting memory info"
            )
            return bot.send_message(
                message.chat.id, text="⚠️ Some error occurred. Please try again later("
            )

        data = button_data(
            text="Swap info", callback_data="__swap_info__"
        )
        keyboard = keyboards.build_inline_keyboard(data)

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
            parse_mode="HTML",
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling memory command",
            error_code="HAND_006",
            metadata={"exception": str(error)}
        ))
