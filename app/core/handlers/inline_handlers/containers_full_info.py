#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from telebot.types import CallbackQuery

from app.core.adapters.containers_base_data import ContainerData, ContainersFactory
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_inline_handler_session


class InlineContainerFullInfoHandler(HandlerConstructor, ContainerData):

    def handle(self):
        """
        This function sets up a callback query handler for the 'containers_full_info' data.
        When the callback query is received, it retrieves the container ID from the callback data,
        edits the message text with the container ID, and removes the reply markup.
        """

        containers_factory = ContainersFactory().containers_factory

        @self.bot.callback_query_handler(func=None, config=containers_factory.filter())
        @logged_inline_handler_session
        def handle_containers_full_info(call: CallbackQuery):
            """
            This function handles the callback query for the 'containers_full_info' data.
            It retrieves the container ID from the callback data, edits the message text with the container ID,
            and removes the reply markup.

            Args:
                call (CallbackQuery): The callback query object.
            """
            # Retrieve the container ID from the callback data
            container_id = containers_factory.parse(callback_data=call.data).get('container_id', '')

            # Edit the message text with the container ID
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=container_id,
                reply_markup=None
            )
