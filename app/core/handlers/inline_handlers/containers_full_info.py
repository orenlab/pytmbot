#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from telebot.types import CallbackQuery

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_inline_handler_session


class InlineContainerFullInfoHandler(HandlerConstructor):

    def handle(self):
        """
        This function sets up a callback query handler for the 'containers_full_info' data.
        When the callback query is received, it retrieves the container ID from the callback data,
        edits the message text with the container ID, and removes the reply markup.
        """

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('__get_full__'))
        @logged_inline_handler_session
        def handle_containers_full_info(call: CallbackQuery):
            """
            This function handles the callback query for the 'containers_full_info' data.
            It retrieves the container ID from the callback data, edits the message text with the container ID,
            and removes the reply markup.

            Args:
                call (CallbackQuery): The callback query object.
            """

            # Extract the container ID from the callback data
            container_name = call.data.split("__get_full__")[1]

            container_details = DockerAdapter().get_full_container_details(container_name.lower())
            print(container_details)

            # Edit the message text with the container ID
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Some details about: {container_name}\n\n{container_details}",
                reply_markup=None
            )
