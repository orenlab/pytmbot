#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class ProcessHandler(HandlerConstructor):

    def _get_data(self) -> tuple:
        """
        Get process counts using psutil.

        This function uses the psutil_adapter to gather data on the number of running, sleeping, and idle processes.
        It returns a tuple containing the counts of running, sleeping, idle, and total processes.

        Returns:
            tuple: A tuple containing the counts of running, sleeping, idle, and total processes.
        """
        # Use the psutil_adapter to get process counts
        data = self.psutil_adapter.get_process_counts()

        return data

    def _compile_message(self) -> tuple:
        """
        Compile the message to be sent to the bot.

        This function uses psutil to gather data on the memory load. It returns a tuple containing memory data.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.

        Returns:
            tuple: The compiled message to send to the bot.
        """
        try:
            # Use psutil to gather memory data
            context = self._get_data()
            return context
        except (AttributeError, ValueError) as err:
            # Raise an exception if there is a ValueError while rendering the templates
            raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")

    def _get_answer(self) -> str:
        """
        Parses the answer to a template.

        This function compiles the message to be sent to the bot using the _compile_message method.
        It then renders the 'process.jinja2' template with the compiled message.
        If there is a TemplateError during rendering, it raises a PyTeleMonBotTemplateError.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotTemplateError: If there is a TemplateError during rendering.
        """
        try:
            # Compile the message to be sent to the bot
            context = self._compile_message()

            # Define the template name for rendering
            template_name = 'process.jinja2'

            # Prepare the context for the template rendering
            emojis = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                'horizontal_traffic_light': self.emojis.get_emoji('horizontal_traffic_light'),

            }

            # Render the 'process.jinja2' template with the compiled message
            bot_answer = self.jinja.render_templates(template_name, context=context, **emojis)

            # Return the compiled message
            return bot_answer
        except self.template_error as err:
            # Raise a PyTeleMonBotTemplateError if there is a TemplateError during rendering
            raise self.exceptions.PyTeleMonBotTemplateError(f"Error parsing template: {err}")

    def handle(self):
        """
        Set up a message handler for the 'Process' regexp.
        When a message with 'Process' is received, it will trigger the
        'get_process' function.
        """

        @self.bot.message_handler(regexp="Process")
        @logged_handler_session
        def get_process(message: Message) -> None:
            """
            Handle the 'Process' message.

            Args:
                message (telegram.Message): The received message.

            Raises:
                self.exceptions.PyTeleMonBotHandlerError: If there's a connection error.
            """
            try:
                # Send typing action to indicate that the bot is processing the request
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Get the answer and send it as a bot message
                bot_answer = self._get_answer()
                self.bot.send_message(
                    message.chat.id,
                    text=bot_answer,
                    parse_mode="HTML"
                )
            except (AttributeError, ValueError) as err:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")
