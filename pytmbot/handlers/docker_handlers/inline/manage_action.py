#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.container_manager import ContainerManager
from pytmbot.adapters.docker.utils import check_container_state
from pytmbot.globals import session_manager, keyboards
from pytmbot.handlers.handlers_util.docker import show_handler_info
from pytmbot.logs import logged_inline_handler_session, bot_logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.models.containers_model import ContainersState
from pytmbot.utils.utilities import split_string_into_octets, is_new_name_valid

container_manager = ContainerManager()
containers_state = ContainersState()


def managing_action_fabric(call: CallbackQuery):
    """
    Checks if a callback query data starts with a specific action.

    Args:
        call (CallbackQuery): The callback query object.

    Returns:
        bool: True if the callback query data starts with '__start__', '__stop__', or '__restart__',
        False otherwise.
    """
    action = [
        '__start__',
        '__stop__',
        '__restart__',
    ]
    return any(call.data.startswith(callback_data) for callback_data in action)


# func=lambda call: managing_action_fabric(call)
@two_factor_auth_required
@logged_inline_handler_session
def handle_manage_container_action(call: CallbackQuery, bot: TeleBot):
    container_name, called_user_id = split_string_into_octets(call.data), split_string_into_octets(call.data, octet_index=2)
    """
    Handles the callback query for managing a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    if int(call.from_user.id) != int(called_user_id):
        bot_logger.log("DENIED", f"User {call.from_user.id}: Denied '__manage__' function")
        return show_handler_info(call=call, text=f"Starting {container_name}: Access denied", bot=bot)

    if not session_manager.is_authenticated(call.from_user.id):
        bot_logger.log("DENIED", f"User {call.from_user.id}: Not authenticated. Denied '__start__' function")
        return show_handler_info(call=call, text=f"Managing {container_name}: Not authenticated user", bot=bot)

    managing_actions = {
        '__start__': __start_container,
        '__stop__': __stop_container,
        '__restart__': __restart_container,
    }
    managing_action = split_string_into_octets(call.data, octet_index=0)

    if managing_action in managing_actions:
        managing_actions[managing_action](call=call, container_name=container_name, bot=bot)
    else:
        bot_logger.log("ERROR",
                       f"Error occurred while managing {container_name}: Unknown action {managing_action}")


def __start_container(call: CallbackQuery, container_name: str, bot: TeleBot):
    """
    Starts a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to start.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        if container_manager.managing_container(call.from_user.id, container_name, action="start") is None:
            return show_handler_info(call=call, text=f"Starting {container_name}: Success", bot=bot)
        else:
            return show_handler_info(call=call, text=f"Starting {container_name}: Error occurred. See logs", bot=bot)
    except Exception as e:
        bot_logger.log("ERROR", f"Error occurred while starting {container_name}: {e}")
        return


def __stop_container(call: CallbackQuery, container_name: str, bot: TeleBot):
    """
    Stops a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to stop.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        if container_manager.managing_container(call.from_user.id, container_name, action="stop") is None:
            return show_handler_info(call=call, text=f"Stopping {container_name}: Success", bot=bot)
        else:
            return show_handler_info(call=call, text=f"Stopping {container_name}: Error occurred. See logs", bot=bot)
    except Exception as e:
        bot_logger.log("ERROR", f"Error occurred while stopping {container_name}: {e}")
        return


def __restart_container(call: CallbackQuery, container_name: str, bot: TeleBot):
    """
    Restarts a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to restart.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        container_manager.managing_container(call.from_user.id, container_name, action="restart")
        container_state = check_container_state(container_name)

        if container_state == containers_state.running:

            bot_logger.info(
                f"Restarting {container_name} for user {call.from_user.id}: Success. State: {container_state}")
            keyboards_key = keyboards.ButtonData(text=f"Back to {container_name}",
                                                 callback_data=f"__manage__:{container_name}:{call.from_user.id}")
            keyboard = keyboards.build_inline_keyboard(keyboards_key)

            return bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Restarting {container_name}: Success. State: {container_state}",
                reply_markup=keyboard)
        else:
            bot_logger.error(f"Error occurred while restarting {container_name}: State: {container_state}")

            return show_handler_info(call=call, text=f"Restarting {container_name}: Error occurred. See logs", bot=bot)

    except Exception as e:
        bot_logger.log("ERROR", f"Error occurred while restarting {container_name}: {e}")
        return


def __rename_container(call: CallbackQuery, container_name: str, new_container_name: str, bot: TeleBot):
    """
    Renames a Docker container based on the provided parameters.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to rename.
        new_container_name (str): The new name for the container.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    if is_new_name_valid(new_container_name):
        try:
            if container_manager.managing_container(call.from_user.id, container_name, action="rename",
                                                    new_container_name=new_container_name):
                return show_handler_info(call=call, text=f"Renaming {container_name}: Success", bot=bot)
            else:
                return show_handler_info(call=call, text=f"Renaming {container_name}: Error occurred. See logs",
                                         bot=bot)
        except Exception as e:
            bot_logger.log("ERROR", f"Error occurred while renaming {container_name}: {e}")
            return
    else:
        return show_handler_info(call=call, text=f"Renaming {container_name}: Invalid new name", bot=bot)
