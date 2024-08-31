#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.containers_info import get_container_state
from pytmbot.globals import keyboards, em, session_manager
from pytmbot.handlers.handlers_util.docker import show_handler_info
from pytmbot.logs import logged_inline_handler_session, bot_logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.models.containers_model import ContainersState
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.utilities import split_string_into_octets

container_state = ContainersState


# func=lambda call: call.data.startswith('__manage__')
@bot_logger.catch()
@two_factor_auth_required
@logged_inline_handler_session
def handle_manage_container(call: CallbackQuery, bot: TeleBot):
    """
    Handles the callback for managing a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    # Extract container name and called user ID from the callback data
    container_name = split_string_into_octets(call.data)
    called_user_id = split_string_into_octets(call.data, octet_index=2)

    # Check if the user is an admin
    if int(call.from_user.id) != int(called_user_id):
        bot_logger.log("DENIED", f"User {call.from_user.id} NOT is an admin. Denied '__manage__' function")
        return show_handler_info(call=call, text=f"Managing {container_name}: Access denied", bot=bot)

    is_authenticated = session_manager.is_authenticated(call.from_user.id)
    bot_logger.debug(f"User {call.from_user.id} authenticated status: {is_authenticated}")

    if not is_authenticated:
        bot_logger.log("DENIED",
                       f"User {call.from_user.id} NOT authenticated. "
                       f"Denied '__manage__' function for container {container_name}")
        return show_handler_info(call=call, text=f"Managing {container_name}: Not authenticated user", bot=bot)

    # Create the keyboard buttons
    keyboard_buttons = [
        keyboards.ButtonData(text=f"{em.get_emoji('BACK_arrow')} Back to {container_name} info",
                             callback_data=f'__get_full__:{container_name}:{call.from_user.id}'),
    ]

    state = get_container_state(container_name)

    bot_logger.info(f"Container {container_name} state: {state}")

    if state == container_state.running:
        bot_logger.debug(f"Added '__stop__' button for {container_name}")
        keyboard_buttons.insert(
            0,
            keyboards.ButtonData(text=f"{em.get_emoji('no_entry')} Stop",
                                 callback_data=f'__stop__:{container_name}:{call.from_user.id}'),
        )

        bot_logger.debug(f"Added '__restart__' button for {container_name}")
        keyboard_buttons.insert(
            1,
            keyboards.ButtonData(text=f"{em.get_emoji('recycling_symbol')} Restart",
                                 callback_data=f'__restart__:{container_name}:{call.from_user.id}'),
        )

    elif state in [container_state.exited, container_state.stopped, container_state.dead]:
        bot_logger.debug(f"Added '__start__' button for {container_name}")
        keyboard_buttons.insert(
            0,
            keyboards.ButtonData(text=f"{em.get_emoji('glowing_star')} Start",
                                 callback_data=f'__start__:{container_name}:{call.from_user.id}'),
        )

    inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

    emojis: dict = {
        'cross_mark': em.get_emoji('cross_mark'),
        'briefcase': em.get_emoji('briefcase'),
        'anxious_face_with_sweat': em.get_emoji('anxious_face_with_sweat'),
        'double_exclamation_mark': em.get_emoji('double_exclamation_mark'),
    }

    with Compiler(
            'd_managing_containers.jinja2',
            emojis=emojis,
            state=state,
            container_name=container_name
    ) as compiler:
        context = compiler.compile()

    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML"
    )
