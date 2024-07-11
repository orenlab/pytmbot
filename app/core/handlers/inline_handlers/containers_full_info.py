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
from app.utilities.utilities import set_naturalsize


class InlineContainerFullInfoHandler(HandlerConstructor):
    """
    The InlineContainerFullInfoHandler class is a subclass of the HandlerConstructor class.
    It is used to handle the 'containers_full_info' data in an inline query.
    """

    @staticmethod
    def get_container_full_details(container_name):
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
    def get_emojis(self):
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

    def build_back_button(self):
        """
        Builds the back button for the inline keyboard.

        Returns:
            InlineKeyboardMarkup: The inline keyboard with the back button.
        """
        return self.keyboard.build_inline_keyboard(
            'Back to all containers...',
            callback_data='back_to_containers'
        )

    @staticmethod
    def extract_container_name(data):
        """
        Extracts and returns the container name from the input data.

        Args:
            data (str): The input data containing the container name.

        Returns:
            str: The extracted container name in lowercase.
        """
        return data.split("__get_full__")[1].lower()

    @staticmethod
    def parse_container_memory_stats(container_stats):
        """
        Parse the memory statistics of a container.

        Args:
            container_stats (Dict): The dictionary containing memory statistics of a container.

        Returns:
            Dict: A dictionary with keys for 'mem_usage', 'mem_limit', and 'mem_percent'.
        """
        if 'memory_stats' not in container_stats:
            return {
                'mem_usage': 0,
                'mem_limit': 0,
                'mem_percent': 0,
            }
        return {
            'mem_usage': set_naturalsize(container_stats['memory_stats']['usage']),
            'mem_limit': set_naturalsize(container_stats['memory_stats']['limit']),
            'mem_percent': round(
                container_stats['memory_stats']['usage'] / container_stats['memory_stats']['limit'] * 100, 2),
        }

    @staticmethod
    def parse_container_cpu_stats(container_stats):
        """
        Parse the CPU statistics of a container.

        Args:
            container_stats (Dict): The dictionary containing CPU statistics of a container.

        Returns:
            Dict: A dictionary with keys for 'periods', 'throttled_periods', and 'throttling_data'.
        """
        precpu_stats = container_stats.get('precpu_stats', {})
        throttling_data = precpu_stats.get('throttling_data', {})

        if 'throttling_data' not in precpu_stats:
            return {
                'periods': None,
                'throttled_periods': None,
                'throttling_data': None,
            }

        return {
            'periods': throttling_data.get('periods'),
            'throttled_periods': throttling_data.get('throttled_periods'),
            'throttling_data': throttling_data.get('throttled_time'),
        }

    @staticmethod
    def parse_container_network_stats(container_stats):
        """
        Parse the network statistics of a container.

        Args:
            container_stats (Dict): The dictionary containing network statistics of a container.

        Returns:
            Dict: A dictionary with keys for 'rx_bytes', 'tx_bytes', 'rx_dropped', 'tx_dropped', 'rx_errors', and 'tx_errors'.
        """
        network_data = container_stats.get('networks', {}).get('eth0', {})

        return {
            'rx_bytes': set_naturalsize(network_data.get('rx_bytes', 0)),  # Received bytes
            'tx_bytes': set_naturalsize(network_data.get('tx_bytes', 0)),  # Transmitted bytes
            'rx_dropped': network_data.get('rx_dropped', 0),  # Received dropped packets
            'tx_dropped': network_data.get('tx_dropped', 0),  # Transmitted dropped packets
            'rx_errors': network_data.get('rx_errors', 0),  # Received errors
            'tx_errors': network_data.get('tx_errors', 0),  # Transmitted errors
        }

    @staticmethod
    def parse_container_attrs(container_attrs):
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
                call (CallbackQuery): The callback query object.

            Returns:
                None

            This function is responsible for handling the callback query when a user
            requests detailed information about a container. It retrieves the container
            details, extracts the container name from the callback data, and then
            retrieves the full container details. It then extracts the container stats
            and attributes, and parses the container stats. The parsed stats and
            attributes are then rendered into a template using the Jinja2 library.
            Finally, the rendered template is sent back to the user as an edited message
            with a back button for navigation.
            """

            # Extract the container name from the callback data
            container_name = self.extract_container_name(call.data)

            container_details = self.get_container_full_details(container_name)

            if not container_details or container_details == {}:
                return handle_container_not_found(call)

            # Extract container stats and attributes
            container_stats = container_details.stats(decode=None, stream=False)
            container_attrs = container_details.attrs

            # Define emojis for rendering
            emojis = self.get_emojis()

            try:
                context = self.jinja.render_templates(
                    'containers_full_info.jinja2',
                    **emojis,
                    container_name=container_name,
                    container_memory_stats=self.parse_container_memory_stats(container_stats),
                    container_cpu_stats=self.parse_container_cpu_stats(container_stats),
                    container_network_stats=self.parse_container_network_stats(container_stats),
                    container_attrs=self.parse_container_attrs(container_attrs)
                )
            except Exception as e:
                # Log an error if parsing fails
                bot_logger.exception(f"Failed at @{self.__class__.__name__} - exception: {e}")
                return handle_container_not_found(call)

            # Edit the message text with container information and back button
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=self.build_back_button(),
                parse_mode="Markdown"
            )

        @self.bot.callback_query_handler(func=lambda call: call.data == 'back_to_containers')
        @logged_inline_handler_session
        def back_to_containers(call: CallbackQuery):
            """
            This function handles the callback query for the 'back_to_containers' data.
            It removes the reply markup and sends a message with a list of all containers.

            Args:
                call (CallbackQuery): The callback query object.
            """

            # Get the list of containers again
            containers_data = ContainersHandler(self.bot)
            context = containers_data.get_list_of_containers_again()[0]

            # Build the custom inline keyboard
            inline_keyboard = containers_data.build_custom_inline_keyboard(
                containers_data.get_list_of_containers_again()[1]
            )

            # Edit the message with the new list of containers
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=inline_keyboard
            )

        def handle_container_not_found(call):
            """
            Handles the case when a container is not found.

            Args:
                call (telegram.CallbackQuery): The callback query object.

            Returns:
                None
            """
            return self.bot.answer_callback_query(
                callback_query_id=call.id,
                text="Container not found or exiting. Please try again later.",
                show_alert=True
            )
