#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from functools import lru_cache

from telebot.types import CallbackQuery

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.default_handlers.containers_handler import ContainersHandler
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_inline_handler_session, bot_logger
from app.utilities.utilities import set_naturalsize, extract_container_name


class InlineContainerFullInfoHandler(HandlerConstructor):
    """
    The InlineContainerFullInfoHandler class is a subclass of the HandlerConstructor class.
    It is used to handle the 'containers_full_info' data in an inline query.
    """

    @staticmethod
    def __get_container_full_details(container_name):
        """
        Retrieve the full details of a container.

        Args:
            container_name (str): The name of the container.

        Returns:
            dict: The full details of the container.
        """
        # Retrieve full container details
        try:
            container_details = DockerAdapter().get_full_container_details(
                container_name.lower()
            )
            return container_details
        except Exception as e:
            # Log an error message if an exception occurs
            bot_logger.exception(f"Failed at @{__name__} - exception: {e}")
            return None

    @lru_cache(maxsize=128)
    def __get_emojis(self):
        """
        Return a dictionary of emojis with keys representing emoji names and values as emoji characters.
        """
        return {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
            'luggage': self.emojis.get_emoji('pushpin'),
            'minus': self.emojis.get_emoji('minus'),
            'backhand_index_pointing_down': self.emojis.get_emoji('backhand_index_pointing_down'),
            'banjo': self.emojis.get_emoji('banjo'),
            'basket': self.emojis.get_emoji('basket'),
            'flag_in_hole': self.emojis.get_emoji('flag_in_hole'),
            'railway_car': self.emojis.get_emoji('railway_car'),
            'radio': self.emojis.get_emoji('radio'),
            'puzzle_piece': self.emojis.get_emoji('puzzle_piece'),
            'radioactive': self.emojis.get_emoji('radioactive'),
            'safety_pin': self.emojis.get_emoji('safety_pin'),
            'sandwich': self.emojis.get_emoji('sandwich'),
        }

    @staticmethod
    def __get_logs(container_name):
        """
        Retrieve the logs of a container.

        Returns:
            str: The logs of the container.
        """
        return DockerAdapter().fetch_container_logs(container_name)

    @staticmethod
    def __parse_container_memory_stats(container_stats):
        """
        Parse the memory statistics of a container.

        Args:
            container_stats (Dict): The dictionary containing memory statistics of a container.

        Returns:
            Dict: A dictionary with keys for 'mem_usage', 'mem_limit', and 'mem_percent'.
        """
        memory_stats = container_stats.get('memory_stats', {})
        return {
            'mem_usage': set_naturalsize(memory_stats.get('usage', 0)),
            'mem_limit': set_naturalsize(memory_stats.get('limit', 0)),
            'mem_percent': round(memory_stats.get('usage', 0) / memory_stats.get('limit', 1) * 100, 2)
            if 'limit' in memory_stats else 0,
        }

    @staticmethod
    def __parse_container_cpu_stats(container_stats):
        """
        Parse the CPU statistics of a container.

        Args:
            container_stats (Dict): The dictionary containing CPU statistics of a container.

        Returns:
            Dict: A dictionary with keys for 'periods', 'throttled_periods', and 'throttling_data'.
        """
        precpu_stats = container_stats.get('precpu_stats', {})
        throttling_data = precpu_stats.get('throttling_data', {})

        return {
            'periods': throttling_data.get('periods', 0),
            'throttled_periods': throttling_data.get('throttled_periods', 0),
            'throttling_data': throttling_data.get('throttled_time', 0),
        }

    @staticmethod
    def __parse_container_network_stats(container_stats):
        """
        Parse the network statistics of a container.

        Args:
            container_stats (Dict): The dictionary containing network statistics of a container.

        Returns:
            Dict: A dictionary with keys for 'rx_bytes', 'tx_bytes', 'rx_dropped', 'tx_dropped', 'rx_errors', and
            'tx_errors'.
        """
        network_data = container_stats.get('networks', {}).get('eth0', {})

        return {
            'rx_bytes': set_naturalsize(network_data.get('rx_bytes', 0)),
            'tx_bytes': set_naturalsize(network_data.get('tx_bytes', 0)),
            'rx_dropped': network_data.get('rx_dropped', 0),
            'tx_dropped': network_data.get('tx_dropped', 0),
            'rx_errors': network_data.get('rx_errors', 0),
            'tx_errors': network_data.get('tx_errors', 0),
        }

    @staticmethod
    def __parse_container_attrs(container_attrs):
        """
        This function parses container attributes and returns a dictionary with specific keys.

        Args:
            container_attrs (Dict): The dictionary containing container attributes.

        Returns:
            Dict: A dictionary with keys for 'running', 'paused', 'restarting', 'restarting_count', 'dead',
                  'exit_code', 'env', 'command', and 'args'.
        """
        # Extract running state and configuration attributes
        running_state = container_attrs['State']
        config_attrs = container_attrs['Config']

        # Create and return a dictionary with specific keys
        return {
            'running': running_state.get('Running', False),
            'paused': running_state.get('Paused', False),
            'restarting': running_state.get('Restarting', False),
            'restarting_count': container_attrs.get('RestartCount', 0),
            'dead': running_state.get('Dead', False),
            'exit_code': running_state.get('ExitCode', None),
            'env': config_attrs.get('Env', []),
            'command': config_attrs.get('Cmd', ''),
            'args': container_attrs.get('Args', ''),
        }

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
            Handle the callback query for detailed container information.

            Args:
                call (telebot.types.CallbackQuery): The callback query object.
            """

            # Extract the container name from the callback data
            container_name = extract_container_name(call.data, prefix='__get_full__')

            # Retrieve the full container details
            container_details = self.__get_container_full_details(container_name)

            if not container_details:
                return handle_container_not_found(call, text=f"{container_name}: Container not found")

            container_stats = container_details.stats(decode=None, stream=False)
            container_attrs = container_details.attrs

            emojis = self.__get_emojis()

            try:
                context = self.jinja.render_templates(
                    'containers_full_info.jinja2',
                    **emojis,
                    container_name=container_name,
                    container_memory_stats=self.__parse_container_memory_stats(container_stats),
                    container_cpu_stats=self.__parse_container_cpu_stats(container_stats),
                    container_network_stats=self.__parse_container_network_stats(container_stats),
                    container_attrs=self.__parse_container_attrs(container_attrs)
                )
            except Exception as e:
                bot_logger.exception(f"Failed at @{self.__class__.__name__} - exception: {e}")
                return handle_container_not_found(call, text=f"{container_name}: Error getting container details")

            _inline_keyboard = self.keyboard.build_logs_inline_keyboard(container_name)

            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=_inline_keyboard,
                parse_mode="Markdown"
            )

        # Instantiate ContainersHandler object
        containers_handler = ContainersHandler(self.bot)

        @self.bot.callback_query_handler(func=lambda call: call.data == 'back_to_containers')
        @logged_inline_handler_session
        def handle_back_to_containers(call: CallbackQuery):
            """
            Handles the callback query for the 'back_to_containers' data.
            It retrieves the list of containers again and sends a message with the updated list.

            Args:
                call (CallbackQuery): The callback query object.
            """

            # Get the updated list of containers and buttons
            context, buttons = containers_handler.get_list_of_containers_again()

            bot_logger.debug(f"Updated list of containers: {buttons}")

            # Build a custom inline keyboard
            inline_keyboard = self.keyboard.build_container_inline_keyboard(buttons)

            # Edit the message text with the updated container list and keyboard
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=inline_keyboard,
                parse_mode="Markdown"
            )

        def handle_container_not_found(call, text: str):
            """
            Handles the case when a container is not found.

            Args:
                call (CallbackQuery): The callback query object.
                text (str): The text to display in the alert.

            Returns:
                None
            """
            return self.bot.answer_callback_query(
                callback_query_id=call.id,
                text=text,
                show_alert=True
            )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('__get_logs__'))
        @logged_inline_handler_session
        def handle_get_logs(call: CallbackQuery):
            """
            Handles the callback for getting logs of a container.

            Args:
                call (CallbackQuery): The callback query object.

            Returns:
                None
            """
            # Extract container name from the callback data
            container_name = extract_container_name(call.data, prefix='__get_logs__')

            # Get logs for the specified container
            logs = self.__get_logs(container_name)

            if not logs:
                return handle_container_not_found(call, text=f"{container_name}: Error getting logs")

            # Define emojis for rendering
            emojis: dict = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
            }

            # Render the logs template
            context = self.jinja.render_templates(
                'logs.jinja2',
                emojis=emojis,
                logs=logs
            )

            # Build a custom inline keyboard for navigation
            inline_keyboard = self.keyboard.build_inline_keyboard('Back to all containers...',
                                                                  callback_data='back_to_containers')

            # Edit the message with the rendered logs and inline keyboard
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=inline_keyboard,
                parse_mode="Markdown"
            )
