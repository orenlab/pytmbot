#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import ButtonDataType, get_keyboards, settings
from pytmbot.handlers.docker_handlers.containers import CONTAINERS_PAGE_CALLBACK_PREFIX
from pytmbot.handlers.docker_handlers.inline.container_runtime_info import (
    CONTAINER_EXTRA_ACTION_NETWORKS,
    CONTAINER_EXTRA_ACTION_VOLUMES,
    CONTAINER_EXTRA_CALLBACK_PREFIX,
)
from pytmbot.handlers.docker_handlers.pagination import (
    build_page_callback_data,
    parse_container_full_info_callback_data,
)
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    get_comprehensive_container_details,
    get_emojis,
    show_handler_info,
    validate_container_name,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
keyboards = get_keyboards()


@logger.catch()
@logger.session_decorator
def handle_containers_full_info(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handle request for comprehensive container information using enhanced utilities.
    """
    try:
        if call.data is None:
            show_handler_info(call, text="Invalid request format", bot=bot)
            return None

        parsed_data = parse_container_full_info_callback_data(call.data)
        if parsed_data is None:
            show_handler_info(call, text="Invalid request format", bot=bot)
            return None

        container_name, called_user_id, source_page = parsed_data

        is_allowed, deny_reason = authorize_docker_callback_request(
            call=call,
            called_user_id=called_user_id,
            require_admin=False,
            require_owner_match=True,
            require_session=False,
        )
        if not is_allowed:
            logger.warning(
                "bot.handler.docker.container_info.user.denied.deny",
                reason=deny_reason,
            )
            show_handler_info(
                call,
                text=f"Container info: {deny_reason}",
                bot=bot,
            )
            return None

        # Validate container name
        if not validate_container_name(container_name):
            logger.warning("bot.handler.docker.container_info.invalid.container.warn")
            show_handler_info(call, text="Invalid container name format", bot=bot)
            return None

        # Get comprehensive container details using enhanced utilities
        container_details = get_comprehensive_container_details(container_name)

        if not container_details:
            logger.info("bot.handler.docker.container_info.container.not.info")
            show_handler_info(
                call, text=f"{container_name}: Container not found", bot=bot
            )
            return None

        container_ref = (
            str(container_details.get("name", container_name)).strip().lower()
        )
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
        if (
            call.from_user.id in settings.access_control.allowed_admins_ids
            and int(call.from_user.id) == called_user_id
        ):
            logger.debug("bot.handler.docker.container_info.user.admin.debug")

            keyboard_buttons.extend(
                [
                    button_data(
                        text=f"{emojis.get('luggage', '🧳')} Volumes",
                        callback_data=(
                            f"{CONTAINER_EXTRA_CALLBACK_PREFIX}:"
                            f"{CONTAINER_EXTRA_ACTION_VOLUMES}:"
                            f"{container_ref}:{call.from_user.id}"
                        ),
                    ),
                    button_data(
                        text=f"{emojis.get('globe_with_meridians', '🌐')} Networks",
                        callback_data=(
                            f"{CONTAINER_EXTRA_CALLBACK_PREFIX}:"
                            f"{CONTAINER_EXTRA_ACTION_NETWORKS}:"
                            f"{container_ref}:{call.from_user.id}"
                        ),
                    ),
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

        back_callback_data = build_page_callback_data(
            prefix=CONTAINERS_PAGE_CALLBACK_PREFIX,
            page=source_page or 1,
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

        callback_message = call.message
        if callback_message is None:
            show_handler_info(
                call=call,
                text="Cannot render container details in this context",
                bot=bot,
            )
            return None

        # Send response
        bot.edit_message_text(
            chat_id=callback_message.chat.id,
            message_id=callback_message.message_id,
            text=context,
            reply_markup=inline_keyboard,
            parse_mode="HTML",
        )
        return None

    except ValueError:
        logger.warning("bot.handler.docker.container_info.value.fail")
        show_handler_info(call, text="Invalid request data", bot=bot)
        return None

    except Exception:
        logger.error("bot.handler.docker.container_info.unexpected.fail")
        show_handler_info(
            call, text="An error occurred while processing request", bot=bot
        )
        return None
