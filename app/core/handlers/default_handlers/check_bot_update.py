#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
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
    def __check_bot_update() -> dict:
        """
        Check for updates of pyTMbot.

        This function sends a GET request to the GitHub API to retrieve the latest release information
        of pyTMbot. If the request is successful, it extracts the relevant information from the response
        and returns it as a dictionary. If the request fails, it logs an error message and returns an empty dictionary.

        Returns:
            dict: A dictionary containing the tag name, published date, and body of the latest release.
                  If the request fails, an empty dictionary is returned.
        """
        try:
            # Initialize an empty dictionary to store the release information
            release_info: dict = {}

            # Send a GET request to the GitHub API to retrieve the latest release information
            resp = requests.get(__github_api_url__, timeout=5)

            # Log a debug message indicating that the request has been submitted
            bot_logger.debug("Request has been submitted")

            # Check if the request was successful (status code 200)
            if resp.status_code == 200:
                # Extract the relevant information from the response and update the release_info dictionary
                release_info.update({
                    'tag_name': resp.json()['tag_name'],
                    'published_at': resp.json()['published_at'],
                    'body': resp.json()['body'],
                })

                # Log a debug message indicating that the response code is 200
                bot_logger.debug("Response code - 200")

                # Return the release_info dictionary
                return release_info
            else:
                # Log a debug message indicating the response code and return an empty dictionary
                bot_logger.debug(f"Response code - {resp.status_code}. Return empty dict")
                return {}
        except ConnectionError as e:
            # Log an error message indicating that the update check failed
            bot_logger.error(f"Cant get update info: {e}")
            return {}

    @staticmethod
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
        Compile the message to be sent to the bot.

        This function checks if the bot is in development mode or not.
        If it is in development mode, it returns a message indicating that the bot is using the development version.
        If it is not in development mode, it checks for updates and returns a message accordingly.

        Args:
            self: The BotUpdatesHandler instance.

        Returns:
            tuple[str, bool]: A tuple containing the bot answer and a flag indicating if inline messages are needed.
        """

        # Check if the bot is in development mode
        is_development_mode = self._is_bot_development(__version__)

        if is_development_mode:
            # Return a message indicating that the bot is using the development version
            message = self._render_development_message()
            return message, False
        else:
            # Check for updates
            update_context = self.__check_bot_update()

            if not update_context:
                # Return a message indicating that there were difficulties checking for updates
                message = self._render_update_difficulties_message()
                return message, False
            else:
                if update_context['tag_name'] > __version__:
                    # Return a message indicating that there is a new update available
                    message = self._render_new_update_message(update_context)
                    return message, True
                elif update_context['tag_name'] == __version__:
                    # Return a message indicating that there is no update available
                    message = self._render_no_update_message()
                    return message, False
                elif update_context['tag_name'] < __version__:
                    # Return a message indicating that the bot is living in the future
                    message = self._render_future_message(update_context)
                    return message, False

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
            'thought_balloon': self.get_emoji('thought_balloon'),
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
            'thought_balloon': self.get_emoji('thought_balloon'),
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
            'thought_balloon': self.get_emoji('thought_balloon'),
            'spouting_whale': self.get_emoji('spouting_whale'),
            'calendar': self.get_emoji('calendar'),
            'cooking': self.get_emoji('cooking'),
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
            'thought_balloon': self.get_emoji('thought_balloon'),
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
            'thought_balloon': self.get_emoji('thought_balloon'),
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
            PyTeleMonBotTemplateError: If there is a TemplateError while rendering the template.
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
                    inline_button = self.keyboard.build_inline_keyboard(
                        "How update the bot's image?",
                        "update_info"
                    )
                    HandlerConstructor._send_bot_answer(
                        self,
                        message.chat.id,
                        text=bot_answer,
                        parse_mode='HTML',
                        reply_markup=inline_button
                    )
                else:
                    HandlerConstructor._send_bot_answer(
                        self,
                        message.chat.id,
                        text=bot_answer,
                        parse_mode='HTML',
                    )

            except ValueError:
                # Raise error if there is a ValueError while rendering the template
                error_msg = self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                raise self.exceptions.PyTeleMonBotHandlerError(error_msg)
            except self.TemplateError:
                # Raise error if there is a TemplateError while rendering the template
                error_msg = self.bot_msg_tpl.TPL_ERR_TEMPLATE
                raise self.exceptions.PyTeleMonBotTemplateError(error_msg)
