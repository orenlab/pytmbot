#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Union

from telebot.types import Message, CallbackQuery

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger


class AuthRequiredHandler(HandlerConstructor):
    """Class to handle auth required messages."""

    def _compile_message(self, name=None) -> str:
        """
        Compiles a message to send to the bot with load average data.

        This function compiles the load average data retrieved using the _get_data method,
        sets up template variables for emojis, renders the template, and returns the bot's answer.

        Args:
            self (LoadAvgHandler): Instance of the LoadAvgHandler class.

        Returns:
            str: The compiled message to send to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Setting up the template variables for emojis
            emojis: dict[str, dict | str] = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                'desktop_computer': self.emojis.get_emoji('desktop_computer'),
            }

            # Rendering the template to get the bot's answer
            bot_answer = self.jinja.render_templates('a_auth_required.jinja2', name=name, **emojis)

            # Returning the bot's answer
            return bot_answer
        except ValueError:
            # Handling error if there is an issue parsing the data
            raise self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    @logged_handler_session
    @bot_logger.catch()
    def handle_unauthorized_message(self, query: Union[Message, CallbackQuery]):
        """
        Handle unauthorized message from user.

        Args:
            query (Union[Message, CallbackQuery]): The query object.

        Raises:
            PyTeleMonBotHandlerError: If query is not an instance of Message or CallbackQuery.

        Returns:
            None
        """
        # Check if query is a valid type
        if not isinstance(query, (Message, CallbackQuery)):
            # Raise an error for unsupported query types
            raise NotImplementedError("Unsupported query type")

        # Build inline keyboard with options for QR code or entering 2FA code
        keyboard = self.keyboard.build_reply_keyboard(keyboard_type='auth_keyboard')

        # Compile message with user's first name
        bot_answer = self._compile_message(name=query.from_user.first_name)

        if isinstance(query, CallbackQuery):
            self.bot.delete_message(query.message.chat.id, query.message.message_id)
            self.bot.send_message(query.message.chat.id, text=bot_answer, reply_markup=keyboard)
        else:
            self.bot.send_message(query.chat.id, text=bot_answer, reply_markup=keyboard)


class AccessDeniedHandler(HandlerConstructor):
    """Class to handle access denied messages."""

    @logged_handler_session
    @bot_logger.catch()
    def access_denied_handle(self, query: Union[Message, CallbackQuery]):
        """
        Handle unauthorized message from the user.

        Args:
            query (Union[Message, CallbackQuery]): The query object.

        Raises:
            PyTeleMonBotHandlerError: If query is not an instance of Message or CallbackQuery.

        Returns:
            None
        """
        # Check if the query is a valid type
        if not isinstance(query, (Message, CallbackQuery)):
            # Raise an error for unsupported query types
            raise NotImplementedError("Unsupported query type")

        # Define emojis
        emojis = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
            'crying_face': self.emojis.get_emoji('crying_face'),
        }
        # Get the user's first name
        name = query.from_user.first_name

        # Build keyboard and message based on query type
        if isinstance(query, CallbackQuery):
            keyboard = self.keyboard.build_reply_keyboard(keyboard_type='back_keyboard')
            bot_answer = self.jinja.render_templates('a_access_denied.jinja2', name=name, **emojis)
            self.bot.delete_message(query.message.chat.id, query.message.message_id)
            self.bot.send_message(query.message.chat.id, text=bot_answer, reply_markup=keyboard)
        else:
            keyboard = self.keyboard.build_reply_keyboard(keyboard_type='back_keyboard')
            bot_answer = self.jinja.render_templates('a_access_denied.jinja2', name=name, **emojis)
            self.bot.send_message(query.chat.id, text=bot_answer, reply_markup=keyboard)
