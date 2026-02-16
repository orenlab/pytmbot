#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import button_data, keyboards, settings
from pytmbot.handlers.docker_handlers.containers import CONTAINERS_PAGE_CALLBACK_PREFIX
from pytmbot.handlers.docker_handlers.pagination import (
    build_page_callback_data,
    parse_container_full_info_callback_data,
)
from pytmbot.handlers.handlers_util.docker import (
    get_comprehensive_container_details,
    get_emojis,
    show_handler_info,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.settings import CONTAINER_NAME_PATTERN, MAX_CONTAINER_NAME_LENGTH

logger = Logger()


def validate_container_name(name: str) -> bool:
    """Validate container name for security."""
    if not name or not isinstance(name, str):
        return False

    if len(name) > MAX_CONTAINER_NAME_LENGTH:
        return False

    if not CONTAINER_NAME_PATTERN.match(name):
        return False

    dangerous_patterns = [
        "..",
        "/",
        "\\",
        "$",
        "`",
        ";",
        "|",
        "&",
        "\n",
        "\r",
        "\t",
        "\0",
    ]

    return not any(pattern in name for pattern in dangerous_patterns)


@logger.catch()
@logger.session_decorator
def handle_containers_full_info(call: CallbackQuery, bot: TeleBot):
    """
    Handle request for comprehensive container information using enhanced utilities.
    """
    try:
        if call.data is None:
            return show_handler_info(call, text="Invalid request format", bot=bot)

        parsed_data = parse_container_full_info_callback_data(call.data)
        if parsed_data is None:
            return show_handler_info(call, text="Invalid request format", bot=bot)

        container_name, called_user_id, source_page = parsed_data

        # Validate container name
        if not validate_container_name(container_name):
            logger.warning(
                f"Invalid container name attempted: '{container_name}' by user {call.from_user.id}"
            )
            return show_handler_info(
                call, text="Invalid container name format", bot=bot
            )

        # Get comprehensive container details using enhanced utilities
        container_details = get_comprehensive_container_details(container_name)

        if not container_details:
            logger.info(
                f"Container '{container_name}' not found, requested by user {call.from_user.id}"
            )
            return show_handler_info(
                call, text=f"{container_name}: Container not found", bot=bot
            )

        container_ref = str(container_details.get("name", container_name)).strip().lower()
        if not container_ref:
            container_ref = container_name

        # Get emojis for template
        emojis = get_emojis()

        # Compile template with all container data
        context = Compiler.quick_render(
            template_name="d_containers_full_info.jinja2",
            # Basic template emojis
            thought_balloon=emojis.get("thought_balloon", "💭"),
            container_emoji=emojis.get("package", "📦"),
            cpu_emoji=emojis.get("gear", "⚙️"),
            chart_emoji=emojis.get("chart_increasing", "📈"),
            network_emoji=emojis.get("globe_with_meridians", "🌐"),
            gear_emoji=emojis.get("gear", "⚙️"),
            env_emoji=emojis.get("herb", "🌿"),
            banjo=emojis.get("banjo", "🪕"),
            # Spread all container details
            **container_details,
        )

        # Build keyboard
        keyboard_buttons = []

        # Add admin buttons if user has permissions
        if call.from_user.id in settings.access_control.allowed_admins_ids and int(
            call.from_user.id
        ) == called_user_id:
            logger.debug(f"User {call.from_user.id} is an admin. Adding admin buttons")

            keyboard_buttons.extend(
                [
                    button_data(
                        text=f"{emojis.get('spiral_calendar', '📅')} Get logs",
                        callback_data=f"__get_logs__:open:{container_ref}:{call.from_user.id}",
                    ),
                    button_data(
                        text=f"{emojis.get('bullseye', '🎯')} Manage",
                        callback_data=f"__manage__:{container_ref}:{call.from_user.id}",
                    ),
                ]
            )

        back_callback_data = "back_to_containers"
        if source_page is not None:
            back_callback_data = build_page_callback_data(
                prefix=CONTAINERS_PAGE_CALLBACK_PREFIX,
                page=source_page,
                user_id=called_user_id,
            )

        # Back button
        keyboard_buttons.append(
            button_data(
                text=f"{emojis.get('BACK_arrow', '⬅️')} Back to all containers",
                callback_data=back_callback_data,
            )
        )

        inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

        # Send response
        return bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=context,
            reply_markup=inline_keyboard,
            parse_mode="HTML",
        )

    except ValueError as e:
        logger.warning(
            f"Value error processing callback_data: '{call.data}' from user {call.from_user.id}, error: {e}"
        )
        return show_handler_info(call, text="Invalid request data", bot=bot)

    except Exception as e:
        logger.error(
            f"Unexpected error in handle_containers_full_info: {e}, "
            f"callback_data: '{call.data}', user: {call.from_user.id}"
        )
        return show_handler_info(
            call, text="An error occurred while processing request", bot=bot
        )
