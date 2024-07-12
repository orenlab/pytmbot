#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from functools import lru_cache
from typing import Dict

import requests
from telebot.types import Message

from app import (
    __github_api_url__,
    __version__,
)
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import bot_logger
from app.core.logs import logged_handler_session


class BotUpdatesHandler(HandlerConstructor):
    """Class for handling bot updates"""

    @staticmethod
    def __check_bot_update() -> Dict[str, str]:
        """
        Check for bot updates and return release information.

        This function sends a GET request to the GitHub API to retrieve the latest release information
        of the bot. It uses the `__github_api_url__` constant to construct the URL.

        Returns:
            Dict[str, str]: A dictionary containing the tag name, published date, and release body.
                            If an error occurs during the update check, an empty dictionary is returned.
        """
        try:
            # Send a GET request to the GitHub API
            with requests.get(__github_api_url__, timeout=5) as resp:
                # Log the response status and update info for debugging purposes
                bot_logger.debug(f"Response status: {resp.status_code}")
                bot_logger.debug(f"Update info: {resp.json()}")

                # Raise an exception if the request was not successful
                resp.raise_for_status()

                # Extract the relevant information from the response
                release_info = {
                    'tag_name': resp.json().get('tag_name'),
                    'published_at': resp.json().get('published_at'),
                    'body': resp.json().get('body'),
                }

            # Return the release information
            return release_info
        except requests.exceptions.RequestException as e:
            # Log the error and return an empty dictionary
            bot_logger.error(f"Can't get update info: {e}")
            return {}

    @staticmethod
    @lru_cache
    def _is_bot_development(app_version: str) -> bool:
        """
        Check if the bot is in development mode.

        Args:
            app_version (str): The version of the bot application.

        Returns:
            bool: True if the bot is in development mode, False otherwise.
        """
        return len(app_version) > 6

    def _compile_message(self) -> tuple[str, bool]:
        """
        Compiles a message to be sent to the bot based on the bot's version and
        whether it's in development mode or not.

        Returns:
            A tuple containing the bot's answer and a flag indicating if inline
            messages are needed.
        """

        # Check if the bot is in development mode
        is_development_mode = self._is_bot_development(__version__)

        # If in development mode, return a message indicating the bot is in dev
        if is_development_mode:
            # Render a message indicating that the bot is using the development version
            return self._render_development_message(), False

        # Check for updates and return the appropriate message
        update_context = self.__check_bot_update()

        # If no update context, return a message indicating update difficulties
        if not update_context:
            # Render a message indicating that there were difficulties checking for updates
            return self._render_update_difficulties_message(), False

        # Get the tag name from the update context
        tag_name = update_context['tag_name']

        # Check the version of the update
        if tag_name > __version__:
            # If the tag name is greater than the bot's version, return a new update message
            return self._render_new_update_message(update_context), True
        elif tag_name == __version__:
            # If the tag name is equal to the bot's version, return a no update message
            return self._render_no_update_message(), False
        else:
            # If the tag name is less than the bot's version, return a future update message
            return self._render_future_message(update_context), False

    def _render_development_message(self) -> str:
        """
        Render a message indicating that the bot is using the development version.

        This function renders a message using a template to inform the user that the bot is currently using the
        development version. The message includes the current version of the bot and a recommendation to upgrade
        to a stable release for a better experience.

        Returns:
            str: The rendered message indicating the bot is using the development version.
        """
        # Define the template name for rendering
        template_name: str = 'none.jinja2'

        # Create a dictionary of emojis to be used in the template
        emojis: Dict[str, str] = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
        }

        # Create the message context with the current version
        message_context: str = (
            f"You are using the development version: {__version__}. "
            "We recommend upgrading to a stable release for a better experience."
        )

        # Render the message using the template and message context
        return self.jinja.render_templates(template_name, **emojis, context=message_context)

    def _render_update_difficulties_message(self) -> str:
        """
        Render a message indicating that there were difficulties checking for updates.

        Returns:
            str: The rendered message.

        Args:
            self (CheckBotUpdateHandler): The instance of the CheckBotUpdateHandler class.

        """
        # Define the template name for rendering
        template_name: str = 'none.jinja2'

        # Create a dictionary of emojis to be used in the template
        emojis: Dict[str, str] = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
        }

        # Define the message to be rendered
        message: str = "There were some difficulties checking for updates. We should try again later."

        # Render the 'none.jinja2' template with the context message
        return self.jinja.render_templates(template_name, **emojis, context=message)

    def _render_new_update_message(self, update_context: dict[str, str]) -> str:
        """
        Render a message indicating a new update is available.

        Parameters:
            update_context (dict[str, str]): A dictionary containing the update context.
                It should have the following keys:
                - 'tag_name' (str): The version of the update.
                - 'published_at' (str): The release date of the update.
                - 'body' (str): The release notes of the update.

        Returns:
            str: The rendered message.
        """
        # Define the template name for rendering
        template_name = 'bot_update.jinja2'

        # Extract the current version from the update context
        current_version = update_context['tag_name']
        release_date = update_context['published_at']
        release_notes = update_context['body']

        # Define the emojis to be used in the message
        emojis = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
            'spouting_whale': self.emojis.get_emoji('spouting_whale'),
            'calendar': self.emojis.get_emoji('calendar'),
            'cooking': self.emojis.get_emoji('cooking'),
        }

        # Render the message using Jinja templates
        return self.jinja.render_templates(
            template_name, **emojis,
            current_version=current_version,
            release_date=release_date,
            release_notes=release_notes
        )

    def _render_no_update_message(self) -> str:
        """
        Render a message indicating that there is no update available.

        Args:
            self: The instance of the class.

        Returns:
            str: The rendered message.
        """
        # Create the context message with the current version
        context: str = f"Current version: {__version__}. No update available."

        # Define the template name for rendering
        template_name: str = 'none.jinja2'

        emojis: dict = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
        }

        # Render the 'none.jinja2' template with the context message and emoji
        return self.jinja.render_templates(template_name, **emojis, context=context)

    def _render_future_message(self, update_context: dict[str, str]) -> str:
        """
        Render a message indicating that the user is living in the future.

        Args:
            update_context (dict[str, str]): A dictionary containing the update context.
                It should have the following keys:
                - 'tag_name' (str): The version of the update.

        Returns:
            str: The rendered message.
        """
        # Extract the current version from the update context
        current_version: str = update_context['tag_name']

        # Create the context message with the current and user's versions
        context: str = (
            f"Current version: {current_version}. Your version: {__version__}. "
            "You are living in the future, and I am glad to say that I will continue to grow and evolve!"
        )

        # Define the template name for rendering
        template_name: str = 'none.jinja2'

        emojis: dict = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
        }

        # Render the 'none.jinja2' template with the context message and emoji
        return self.jinja.render_templates(template_name, **emojis, context=context)

    def handle(self):
        """
        Handle the 'check_bot_updates' command.

        This function sets up a message handler for the 'check_bot_updates' command.
        When the command is received, it sends a typing action to the chat,
        compiles the bot's answer, and sends it to the chat.

        Raises:
            PyTeleMonBotHandlerError: If there is a ValueError while rendering the template.
        """

        @self.bot.message_handler(commands=['check_bot_updates'])
        @logged_handler_session
        def updates(message: Message) -> None:
            """
            Check bot update handler.

            This function handles the 'check_bot_updates' command.
            It sends a typing action to the chat, compiles the bot's answer,
            and sends it to the chat.

            Args:
                message (Message): The message received by the bot.

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError while rendering the template.
                PyTeleMonBotTemplateError: If there is a TemplateError while rendering the template.
            """
            try:
                # Send typing action to chat
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Compile the bot's answer
                bot_answer, need_inline = self._compile_message()

                # Send the bot's answer to the chat
                if need_inline:
                    inline_button = self.keyboard.build_inline_keyboard("How update?")
                    self._send_bot_answer(
                        message.chat.id,
                        text=bot_answer,
                        parse_mode='HTML',
                        reply_markup=inline_button
                    )
                else:
                    self._send_bot_answer(
                        message.chat.id,
                        text=bot_answer,
                        parse_mode='HTML',
                    )

            except ValueError:
                # Raise error if there is a ValueError while rendering the template
                error_msg = self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                raise self.exceptions.PyTeleMonBotHandlerError(error_msg)
