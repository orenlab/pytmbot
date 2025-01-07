#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from datetime import datetime

import requests
from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, __version__, em, __github_api_url__
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.utilities import is_bot_development

logger = Logger()


# commands=['check_bot_updates']
@logger.session_decorator
def handle_bot_updates(message: Message, bot: TeleBot) -> None:
    """
    Handle the 'check_bot_updates' command by sending a typing action to the chat,
    compiling the bot's answer, and sending it to the chat with an inline button.

    Args:
        message (Message): The message received by the bot.
        bot (TeleBot): The bot instance.

    Returns:
        None
    """
    bot.send_chat_action(message.chat.id, "typing")

    try:
        # Compile the bot's answer
        bot_answer, need_inline = _process_message()

        keyboard_button = [
            keyboards.ButtonData(text="How update?", callback_data="__how_update__")
        ]

        inline_button = (
            keyboards.build_inline_keyboard(keyboard_button) if need_inline else None
        )

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=bot_answer,
            reply_markup=inline_button,
            parse_mode="HTML",
        )

    except Exception as error:
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling bot updates",
            error_code="HAND_013",
            metadata={"exception": str(error)}
        ))


def _process_message() -> tuple[str, bool]:
    """
    Compiles a message to be sent to the bot based on the bot's version and
    whether it's in development mode or not.

    Returns:
        A tuple containing the bot's answer and a flag indicating if inline
        messages are needed.
    """
    # If in development mode, return a message indicating the bot is in dev
    if is_bot_development(__version__):
        # Render a message indicating that the bot is using the development version
        return _render_development_message(), False

    # Check for updates and return the appropriate message
    update_context = __check_bot_update()

    # If no update context, return a message indicating update difficulties
    if not update_context:
        # Render a message indicating that there were difficulties checking for updates
        return _render_update_difficulties_message(), False

    # Get the tag name from the update context
    tag_name = update_context["tag_name"]

    # Check the version of the update
    if tag_name > __version__:
        # If the tag name is greater than the bot's version, return a new update message
        return _render_new_update_message(update_context), True
    elif tag_name == __version__:
        # If the tag name is equal to the bot's version, return a no update message
        return _render_no_update_message(), False
    else:
        # If the tag name is less than the bot's version, return a future update message
        return _render_future_message(update_context), False


def _render_development_message() -> str:
    """
    Render a message indicating that the bot is using the development version.

    Returns:
        str: The rendered message indicating the bot is using the development version.
    """
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
    }

    message = (
        f"You are using the development version: {__version__}. "
        "We recommend upgrading to a stable release for a better experience."
    )

    with Compiler(template_name="b_none.jinja2", context=message, **emojis) as compiler:
        return compiler.compile()


def _render_update_difficulties_message() -> str:
    """
    Render a message indicating that there were difficulties checking for updates.

    Returns:
        str: The rendered message.
    """
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
    }

    message = (
        "There were some difficulties checking for updates. We should try again later."
    )

    with Compiler(template_name="b_none.jinja2", context=message, **emojis) as compiler:
        return compiler.compile()


def _render_new_update_message(update_context: dict[str, str]) -> str:
    """
    Renders a new update message using the provided update context.

    Args:
        update_context (dict[str, str]): A dictionary containing the update context.
            It should have the following keys:
            - 'tag_name' (str): The version of the update.
            - 'published_at' (str): The release date of the update.
            - 'body' (str): The release notes of the update.

    Returns:
        str: The rendered new update message.
    """
    current_version = update_context["tag_name"]
    release_date = update_context["published_at"]
    release_notes = update_context["body"]

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "spouting_whale": em.get_emoji("spouting_whale"),
        "calendar": em.get_emoji("calendar"),
        "cooking": em.get_emoji("cooking"),
    }

    with Compiler(
            template_name="b_bot_update.jinja2",
            current_version=current_version,
            release_date=release_date,
            release_notes=release_notes,
            **emojis,
    ) as compiler:
        return compiler.compile()


def _render_no_update_message() -> str:
    """
    Render a message indicating that there is no update available.

    Returns:
        str: The rendered message.
    """
    context: str = f"Current version: {__version__}. No update available."

    emojis: dict = {
        "thought_balloon": em.get_emoji("thought_balloon"),
    }

    with Compiler(template_name="b_none.jinja2", context=context, **emojis) as compiler:
        return compiler.compile()


def _render_future_message(update_context: dict[str, str]) -> str:
    """
    Render a message indicating that the user is living in the future.

    Args:
        update_context (dict[str, str]): A dictionary containing the update context.
            It should have the following keys:
            - 'tag_name' (str): The version of the update.

    Returns:
        str: The rendered message.
    """
    current_version: str = update_context["tag_name"]

    context: str = (
        f"Current version: {current_version}. Your version: {__version__}. "
        "You are living in the future, and I am glad to say that I will continue to grow and evolve!"
    )

    emojis: dict = {
        "thought_balloon": em.get_emoji("thought_balloon"),
    }

    with Compiler(template_name="b_none.jinja2", context=context, **emojis) as compiler:
        return compiler.compile()


def __check_bot_update() -> dict[str, str]:
    """
    Check for bot updates and return release information.

    This function sends a GET request to the GitHub API to retrieve the latest release information
    of the bot. It uses the `__github_api_url__` constant to construct the URL.

    Returns:
        dict[str, str]: A dictionary containing the tag name, published date, and release body.
                        If an error occurs during the update check, an empty dictionary is returned.
    """
    try:
        logger.debug("Checking for bot updates...")
        with requests.get(__github_api_url__, timeout=5) as response:
            response.raise_for_status()

            logger.debug(f"GitHub API response code: {response.status_code}")

            data = response.json()

            # Validate required fields in the response
            if not isinstance(data, dict):
                raise ValueError("Response data is not a dictionary")

            tag_name = data.get("tag_name")
            published_at = data.get("published_at")
            body = data.get("body")

            if not tag_name or not isinstance(tag_name, str):
                raise ValueError("Invalid or missing 'tag_name' in the response")

            if not published_at or not isinstance(published_at, str):
                raise ValueError("Invalid or missing 'published_at' in the response")

            if not body or not isinstance(body, str):
                raise ValueError("Invalid or missing 'body' in the response")

            try:
                published_date = datetime.fromisoformat(published_at)
            except ValueError:
                raise ValueError("Invalid 'published_at' format. Expected ISO format.")

            release_info = {
                "tag_name": tag_name,
                "published_at": published_date.strftime("%Y-%m-%d, %H:%M:%S"),
                "body": body,
            }

            logger.debug(f"GitHub API response: {release_info}")

            return release_info

    except (requests.RequestException, ValueError) as e:
        logger.error(f"An error occurred during update check: {e}")
        return {}
