#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import CallbackQuery

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.default_handlers.containers_handler import ContainersHandler
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_inline_handler_session
from app.utilities.utilities import set_naturalsize


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
            container_name = call.data.split("__get_full__")[1].lower()

            # Retrieve full container details
            container_details = DockerAdapter().get_full_container_details(
                container_name.lower()
            )

            # Extract container stats and attributes
            container_stats = container_details.stats(decode=None, stream=False)
            container_attrs = container_details.attrs

            # Parse container stats
            container_memory_stats = parse_container_memory_stats(container_stats)
            container_cpu_stats = parse_container_cpu_stats(container_stats)
            container_network_stats = parse_container_network_stats(container_stats)
            container_attrs = parse_container_attrs(container_attrs)

            # Define emojis for rendering
            emojis = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                'luggage': self.emojis.get_emoji('pushpin'),
                'minus': self.emojis.get_emoji('minus'),
                'backhand_index_pointing_down': self.emojis.get_emoji('backhand_index_pointing_down'),
                'banjo': self.emojis.get_emoji('banjo'),
                'basket': self.emojis.get_emoji('basket'),
            }

            # Render the template with container information
            context = self.jinja.render_templates(
                'containers_full_info.jinja2',
                **emojis,
                container_name=container_name,
                container_memory_stats=container_memory_stats,
                container_cpu_stats=container_cpu_stats,
                container_network_stats=container_network_stats,
                container_attrs=container_attrs
            )

            # Build the back button for navigation
            back_keyboard = self.keyboard.build_inline_keyboard(
                'Back to all containers...',
                callback_data='back_to_containers'
            )

            # Edit the message text with container information and back button
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=back_keyboard,
                parse_mode="Markdown"
            )

        def parse_container_memory_stats(container_stats):
            """
            Parse the memory statistics of a container.

            Args:
                container_stats (Dict): The dictionary containing memory statistics of a container.

            Returns:
                Dict: A dictionary with keys for 'mem_usage', 'mem_limit', and 'mem_percent'.
            """
            return {
                'mem_usage': set_naturalsize(container_stats['memory_stats']['usage']),  # Memory usage
                'mem_limit': set_naturalsize(container_stats['memory_stats']['limit']),  # Memory limit
                'mem_percent': round(
                    container_stats['memory_stats']['usage'] / container_stats['memory_stats']['limit'], 2),
                # Memory percentage
            }

        def parse_container_cpu_stats(container_stats):
            """
            Parse the CPU statistics of a container.

            Args:
                container_stats (Dict): The dictionary containing CPU statistics of a container.

            Returns:
                Dict: A dictionary with keys for 'periods', 'throttled_periods', and 'throttling_data'.
            """
            return {
                # Number of periods of CPU throttling
                'periods': container_stats['precpu_stats']['throttling_data']['periods'],
                # Number of periods when CPU throttling occurred
                'throttled_periods': container_stats['precpu_stats']['throttling_data']['throttled_periods'],
                # Total time spent in CPU throttling
                'throttling_data': container_stats['precpu_stats']['throttling_data']['throttled_time'],
            }

        def parse_container_network_stats(container_stats):
            """
            Parse the network statistics of a container.

            Args:
                container_stats (Dict): The dictionary containing network statistics of a container.

            Returns:
                Dict: A dictionary with keys for 'rx_bytes', 'tx_bytes', 'rx_dropped', 'tx_dropped', 'rx_errors', and .
                'tx_errors'.
            """
            return {
                'rx_bytes': set_naturalsize(container_stats['networks']['eth0']['rx_bytes']),  # Received bytes
                'tx_bytes': set_naturalsize(container_stats['networks']['eth0']['tx_bytes']),  # Transmitted bytes
                'rx_dropped': container_stats['networks']['eth0']['rx_dropped'],  # Received dropped packets
                'tx_dropped': container_stats['networks']['eth0']['tx_dropped'],  # Transmitted dropped packets
                'rx_errors': container_stats['networks']['eth0']['rx_errors'],  # Received errors
                'tx_errors': container_stats['networks']['eth0']['tx_errors'],  # Transmitted errors
            }

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
