#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from typing import Any

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
    def __check_bot_update():
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
            release_info = {}

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
        """Check if the bot is in development mode."""
        return len(app_version) > 6

    def _compile_message(self) -> tuple[Any, bool] | Any:
        """
        Compile the message to be sent to the bot.

        This function checks if the bot is in development mode or not.
        If it is in development mode, it returns a message indicating that the bot is using the development version.
        If it is not in development mode, it checks for updates and returns a message accordingly.

        Returns:
            A tuple containing the bot answer and a flag indicating if inline messages are needed.
        """
        none_tpl_name = 'none.jinja2'

        # Check if the bot is in development mode
        check_system_version = self._is_bot_development(__version__)

        if check_system_version:
            # Return a message indicating that the bot is using the development version
            bot_answer = self.jinja.render_templates(
                none_tpl_name,
                thought_balloon=self.get_emoji('thought_balloon'),
                context=(f"You are using the development version: {__version__}. "
                         "We recommend upgrading to a stable release for a better experience.")
            )
            need_inline = False
            return bot_answer, need_inline
        else:
            # Check for updates
            context = self.__check_bot_update()

            if context == {} or not context:
                # Return a message indicating that there were difficulties checking for updates
                bot_answer = self.jinja.render_templates(
                    none_tpl_name,
                    thought_balloon=self.get_emoji('thought_balloon'),
                    context="There were some difficulties checking for updates. We should try again later."
                )
                need_inline = False
                return bot_answer, need_inline
            else:
                if context.get('tag_name') > __version__:
                    # Return a message indicating that there is a new update available
                    bot_answer = self.jinja.render_templates(
                        'bot_update.jinja2',
                        thought_balloon=self.get_emoji('thought_balloon'),
                        spouting_whale=self.get_emoji('spouting_whale'),
                        calendar=self.get_emoji('calendar'),
                        cooking=self.get_emoji('cooking'),
                        current_version=context.get('tag_name'),
                        release_date=context.get('published_at'),
                        release_notes=context.get('body')
                    )
                    need_inline = True
                    return bot_answer, need_inline
                elif context.get('tag_name') == __version__:
                    # Return a message indicating that there is no update available
                    bot_answer = self.jinja.render_templates(
                        none_tpl_name,
                        thought_balloon=self.get_emoji('thought_balloon'),
                        context=f"Current version: {__version__}. No update available."
                    )
                    need_inline = False
                    return bot_answer, need_inline
                elif context.get('tag_name') < __version__:
                    # Return a message indicating that the bot is living in the future
                    bot_answer = self.jinja.render_templates(
                        none_tpl_name,
                        thought_balloon=self.get_emoji('thought_balloon'),
                        context=f"Current version: {context.get('tag_name')}. Your version: {__version__}."
                                f" You are living in the future, "
                                f"and I am glad to say that I will continue to grow and evolve!"
                    )
                    need_inline = False
                    return bot_answer, need_inline

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
