#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.exceptions import (
    DockerConnectionError,
    DockerOperationException,
    InvalidContainerReferenceError,
)
from pytmbot.globals import ButtonDataType, get_keyboards, settings
from pytmbot.handlers.docker_handlers.callback_data import (
    LOGS_CALLBACK_PREFIX,
    MANAGE_CALLBACK_PREFIX,
    build_callback_data,
    build_container_callback,
    container_short_id,
)
from pytmbot.handlers.docker_handlers.containers import CONTAINERS_PAGE_CALLBACK_PREFIX
from pytmbot.handlers.docker_handlers.inline.container_runtime_info import (
    CONTAINER_EXTRA_ACTION_NETWORKS,
    CONTAINER_EXTRA_ACTION_RUNTIME,
    CONTAINER_EXTRA_ACTION_VOLUMES,
    CONTAINER_EXTRA_CALLBACK_PREFIX,
)
from pytmbot.handlers.docker_handlers.pagination import (
    build_page_callback_data,
    parse_container_full_info_callback_data,
)
from pytmbot.handlers.docker_handlers.user_messages import (
    CONTAINER_DETAILS_FAILED_TEXT,
    CONTAINER_NOT_FOUND_TEXT,
    DOCKER_REQUEST_FAILED_TEXT,
    DOCKER_UNAVAILABLE_TEXT,
    INVALID_CONTAINER_REF_TEXT,
)
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    can_view_command_arguments,
    get_comprehensive_container_details,
    get_emojis,
    hide_command_arguments,
    show_handler_info,
    validate_container_name,
)
from pytmbot.handlers.handlers_util.rich_messages import build_rich_html_message
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.keyboards.keyboards import ButtonData
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
keyboards = get_keyboards()


def _load_container_details(
    call: CallbackQuery, bot: TeleBot, container_ref: str
) -> dict[str, object] | None:
    """Load details, or tell the user honestly why they are unavailable."""
    try:
        container_details = get_comprehensive_container_details(container_ref)
    except DockerConnectionError:
        logger.warning("bot.handler.docker.container_info.docker.unavailable.warn")
        show_handler_info(call, text=DOCKER_UNAVAILABLE_TEXT, bot=bot)
        return None
    except InvalidContainerReferenceError:
        show_handler_info(call, text=INVALID_CONTAINER_REF_TEXT, bot=bot)
        return None
    except DockerOperationException:
        show_handler_info(call, text=DOCKER_REQUEST_FAILED_TEXT, bot=bot)
        return None

    if not container_details:
        logger.info("bot.handler.docker.container_info.container.not.info")
        show_handler_info(call, text=CONTAINER_NOT_FOUND_TEXT, bot=bot)
        return None
    return container_details


def _build_admin_buttons(
    container_ref: str, user_id: int, emojis: dict[str, str]
) -> list[ButtonData]:
    """Buttons for 2FA-protected container views, bound to ``user_id``."""

    def extra(action: str) -> str:
        return build_callback_data(
            CONTAINER_EXTRA_CALLBACK_PREFIX, action, container_ref, user_id
        )

    return [
        button_data(
            text=f"{emojis.get('luggage', '🧳')} Volumes",
            callback_data=extra(CONTAINER_EXTRA_ACTION_VOLUMES),
        ),
        button_data(
            text=f"{emojis.get('globe_with_meridians', '🌐')} Networks",
            callback_data=extra(CONTAINER_EXTRA_ACTION_NETWORKS),
        ),
        button_data(
            text=f"{emojis.get('stethoscope', '🩺')} Runtime",
            callback_data=extra(CONTAINER_EXTRA_ACTION_RUNTIME),
        ),
        button_data(
            text=f"{emojis.get('spiral_calendar', '📅')} Get logs",
            callback_data=build_callback_data(
                LOGS_CALLBACK_PREFIX, "open", container_ref, user_id
            ),
        ),
        button_data(
            text=f"{emojis.get('bullseye', '🎯')} Manage",
            callback_data=build_container_callback(
                MANAGE_CALLBACK_PREFIX, container_ref, user_id
            ),
        ),
    ]


def _render_details(
    container_details: dict[str, object],
    emojis: dict[str, str],
    *,
    show_command_arguments: bool,
) -> str:
    if not show_command_arguments:
        container_details = hide_command_arguments(container_details)
    return Compiler.quick_render(
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
        command_arguments_visible=show_command_arguments,
        # Spread all container details
        **container_details,
    )


@logger.catch()
@logger.session_decorator
def handle_containers_full_info(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handle request for comprehensive container information using enhanced utilities.
    """
    try:
        parsed_data = (
            parse_container_full_info_callback_data(call.data) if call.data else None
        )
        if parsed_data is None:
            show_handler_info(
                call, text="This container details button is no longer valid.", bot=bot
            )
            return None

        container_ref, called_user_id, source_page = parsed_data

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

        # Validate container reference
        if not validate_container_name(container_ref):
            logger.warning("bot.handler.docker.container_info.invalid.container.warn")
            show_handler_info(call, text=INVALID_CONTAINER_REF_TEXT, bot=bot)
            return None

        # Get comprehensive container details using enhanced utilities
        container_details = _load_container_details(call, bot, container_ref)
        if container_details is None:
            return None

        # Buttons always carry the short container ID reported by Docker.
        button_ref = container_short_id(container_details.get("id")) or container_ref

        emojis = get_emojis()
        context = _render_details(
            container_details,
            emojis,
            show_command_arguments=can_view_command_arguments(call.from_user.id),
        )

        keyboard_buttons: list[ButtonData] = []

        # Add admin buttons if user has permissions
        if (
            call.from_user.id in settings.access_control.allowed_admins_ids
            and int(call.from_user.id) == called_user_id
        ):
            logger.debug("bot.handler.docker.container_info.user.admin.debug")
            keyboard_buttons.extend(
                _build_admin_buttons(button_ref, called_user_id, emojis)
            )

        # Back button
        keyboard_buttons.append(
            button_data(
                text=f"{emojis.get('BACK_arrow', '⬅️')} All containers",
                callback_data=build_page_callback_data(
                    prefix=CONTAINERS_PAGE_CALLBACK_PREFIX,
                    page=source_page or 1,
                    user_id=called_user_id,
                ),
            )
        )

        inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

        callback_message = call.message
        if callback_message is None:
            show_handler_info(
                call=call,
                text="This container details message can no longer be updated.",
                bot=bot,
            )
            return None

        # Send response
        edit_callback_message_text(
            call=call,
            bot=bot,
            rich_message=build_rich_html_message(context),
            reply_markup=inline_keyboard,
            not_modified_text="Container details are already current.",
        )
        return None

    except ValueError:
        logger.warning("bot.handler.docker.container_info.value.fail")
        show_handler_info(
            call, text="This container details request is no longer valid.", bot=bot
        )
        return None

    except Exception:
        logger.error("bot.handler.docker.container_info.unexpected.fail")
        show_handler_info(call, text=CONTAINER_DETAILS_FAILED_TEXT, bot=bot)
        return None
