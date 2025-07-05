#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import keyboards, em, settings, button_data
from pytmbot.handlers.handlers_util.docker import (
    get_container_full_details,
    show_handler_info,
    get_emojis,
    parse_container_memory_stats,
    parse_container_cpu_stats,
    parse_container_network_stats,
    parse_container_attrs,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import split_string_into_octets

logger = Logger()


# func=lambda call: call.data.startswith('__get_full__'))
@logger.catch()
@logger.session_decorator
def handle_containers_full_info(call: CallbackQuery, bot: TeleBot):
    container_name = split_string_into_octets(call.data)
    called_user_id = split_string_into_octets(call.data, octet_index=2)
    container_details = get_container_full_details(container_name)

    if not container_details:
        return show_handler_info(
            call, text=f"{container_name}: Container not found", bot=bot
        )

    container_stats = container_details.stats(decode=None, stream=False)
    container_attrs = container_details.attrs

    emojis = get_emojis()

    with Compiler(
        template_name="d_containers_full_info.jinja2",
        **emojis,
        container_name=container_name,
        container_memory_stats=parse_container_memory_stats(container_stats),
        container_cpu_stats=parse_container_cpu_stats(container_stats),
        container_network_stats=parse_container_network_stats(container_stats),
        container_attrs=parse_container_attrs(container_attrs),
    ) as compiler:
        context = compiler.compile()

    keyboard_buttons = []

    if call.from_user.id in settings.access_control.allowed_admins_ids and int(
        call.from_user.id
    ) == int(called_user_id):
        logger.debug(f"User {call.from_user.id} is an admin. Adding admin buttons")

        keyboard_buttons.extend(
            [
                button_data(
                    text=f"{em.get_emoji('spiral_calendar')} Get logs",
                    callback_data=f"__get_logs__:{container_name}:{call.from_user.id}",
                ),
                button_data(
                    text=f"{em.get_emoji('bullseye')} Manage",
                    callback_data=f"__manage__:{container_name}:{call.from_user.id}",
                ),
            ]
        )

    keyboard_buttons.append(
        button_data(
            text=f"{em.get_emoji('BACK_arrow')} Back to all containers",
            callback_data="back_to_containers",
        )
    )

    inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
    )
