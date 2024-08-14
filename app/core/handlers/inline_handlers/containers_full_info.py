#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from functools import lru_cache
from typing import Dict, Any, Union

from telebot.types import CallbackQuery

from app import session_manager
from app.core.adapters.docker_adapter import DockerAdapter
from app.core.auth_processing.auth_wrapper import two_factor_auth_required
from app.core.handlers.default_handlers.containers_handler import ContainersHandler
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_inline_handler_session, bot_logger
from app.utilities.utilities import set_naturalsize, split_string_into_octets, sanitize_logs


class InlineContainerFullInfoHandler(HandlerConstructor):
    """
    The InlineContainerFullInfoHandler class is a subclass of the HandlerConstructor class.
    It is used to handle the 'containers_full_info' data in an inline query.
    """

    docker_adapter = DockerAdapter()

    def __get_container_full_details(self, container_name: str) -> dict:
        """
        Retrieve the full details of a container.

        Args:
            container_name (str): The name of the container.

        Returns:
            dict: The full details of the container.
        """

        # Use a local variable to store the lowercased container name
        lower_container_name = container_name.lower()

        container_details = self.docker_adapter.fetch_full_container_details(lower_container_name)

        return container_details

    @lru_cache(maxsize=128)
    def __get_emojis(self):
        """
        Return a dictionary of emojis with keys representing emoji names and values as emoji characters.
        """
        emoji_names = [
            'thought_balloon', 'luggage', 'minus', 'backhand_index_pointing_down',
            'banjo', 'basket', 'flag_in_hole', 'railway_car',
            'radio', 'puzzle_piece', 'radioactive', 'safety_pin', 'sandwich'
        ]
        return {emoji_name: self.emojis.get_emoji(emoji_name) for emoji_name in emoji_names}

    def __get_sanitized_logs(self, container_name: str, call: CallbackQuery, token: str) -> str:
        """
        Retrieve sanitized logs for a specific container.

        Args:
            container_name (str): The name of the container.
            call (CallbackQuery): The callback query object.
            token (str): The bot token.

        Returns:
            str: Sanitized logs for the container.
        """
        # Fetch raw logs for the container
        raw_logs = self.docker_adapter.fetch_container_logs(container_name)

        # Sanitize the logs for privacy
        sanitized_logs = sanitize_logs(raw_logs, call, token)

        return sanitized_logs

    @staticmethod
    def __parse_container_memory_stats(container_stats: Dict[str, Any]) -> Dict[str, Union[str, float]]:
        """
        Parse the memory statistics of a container.

        Args:
            container_stats (Dict): The dictionary containing memory statistics of a container.

        Returns:
            Dict: A dictionary with keys for 'mem_usage', 'mem_limit', and 'mem_percent'.
                  'mem_usage' is the memory usage of the container in a human-readable format.
                  'mem_limit' is the memory limit of the container in a human-readable format.
                  'mem_percent' is the percentage of memory used by the container.
        """
        # Retrieve the memory statistics from the container_stats dictionary
        memory_stats = container_stats.get('memory_stats', {})

        # Calculate the memory usage and limit in a human-readable format
        mem_usage = set_naturalsize(memory_stats.get('usage', 0))
        mem_limit = set_naturalsize(memory_stats.get('limit', 0))

        # Calculate the percentage of memory used by the container
        mem_percent = round(memory_stats.get('usage', 0) / memory_stats.get('limit', 1) * 100,
                            2) if 'limit' in memory_stats else 0

        # Return a dictionary with the memory usage, limit, and percentage
        return {
            'mem_usage': mem_usage,
            'mem_limit': mem_limit,
            'mem_percent': mem_percent
        }

    @staticmethod
    def __parse_container_cpu_stats(container_stats) -> Dict[str, Union[int, float]]:
        """
        Parse the CPU statistics of a container.

        Args:
            container_stats (Dict[str, Dict[str, Union[Dict[str, Union[int, float]], int]]]): The dictionary containing
            CPU statistics of a container.

        Returns:
            Dict[str, Union[int, float]]: A dictionary with keys for 'periods', 'throttled_periods', and
            'throttling_data'.
        """
        precpu_stats = container_stats.get('precpu_stats', {})
        throttling_data = precpu_stats.get('throttling_data', {})

        return {
            'periods': throttling_data.get('periods', 0),
            'throttled_periods': throttling_data.get('throttled_periods', 0),
            'throttling_data': throttling_data.get('throttled_time', 0),
        }

    @staticmethod
    def __parse_container_network_stats(container_stats: Dict) -> Dict:
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
    def __parse_container_attrs(container_attrs: Dict) -> Dict:
        """
        Parse the container attributes and return a dictionary with specific keys.

        Args:
            container_attrs (Dict): The dictionary containing container attributes.

        Returns:
            Dict: A dictionary with keys for 'running', 'paused', 'restarting', 'restarting_count', 'dead',
                  'exit_code', 'env', 'command', and 'args'.
        """
        running_state = container_attrs.get('State', {})
        config_attrs = container_attrs.get('Config', {})

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
        @bot_logger.catch()
        def handle_containers_full_info(call: CallbackQuery):
            """
            Handle the callback query for detailed container information.

            Args:
                call (telebot.types.CallbackQuery): The callback query object.
            """

            container_name = split_string_into_octets(call.data)
            called_user_id = split_string_into_octets(call.data, octet_index=2)
            container_details = self.__get_container_full_details(container_name)

            if not container_details:
                return show_handler_info(call, text=f"{container_name}: Container not found")

            container_stats = container_details.stats(decode=None, stream=False)
            container_attrs = container_details.attrs

            emojis = self.__get_emojis()

            try:
                context = self.jinja.render_templates(
                    'd_containers_full_info.jinja2',
                    **emojis,
                    container_name=container_name,
                    container_memory_stats=self.__parse_container_memory_stats(container_stats),
                    container_cpu_stats=self.__parse_container_cpu_stats(container_stats),
                    container_network_stats=self.__parse_container_network_stats(container_stats),
                    container_attrs=self.__parse_container_attrs(container_attrs)
                )
            except Exception as e:
                bot_logger.exception(f"Failed at @{self.__class__.__name__} - exception: {e}")
                return show_handler_info(call, text=f"{container_name}: Error getting container details")

            keyboard_buttons = [
                self.keyboard.ButtonData(text="Get logs",
                                         callback_data=f"__get_logs__:{container_name}:{call.from_user.id}"),
                self.keyboard.ButtonData(text="Back to all containers", callback_data="back_to_containers"),
            ]

            if call.from_user.id in self.config.allowed_admins_ids and int(call.from_user.id) == int(called_user_id):
                bot_logger.debug(f"User {call.from_user.id} is an admin. Added '__manage__' button")
                keyboard_buttons.insert(
                    1,
                    self.keyboard.ButtonData(text="Manage",
                                             callback_data=f"__manage__:{container_name}:{call.from_user.id}"))

            inline_keyboard = self.keyboard.build_inline_keyboard(keyboard_buttons)

            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=inline_keyboard,
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

            keyboard_buttons = [
                self.keyboard.ButtonData(text=button.upper(),
                                         callback_data=f"__get_full__:{button}:{call.from_user.id}")
                for button in buttons
            ]

            # Build a custom inline keyboard
            inline_keyboard = self.keyboard.build_inline_keyboard(keyboard_buttons)

            # Edit the message text with the updated container list and keyboard
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=inline_keyboard,
                parse_mode="HTML"
            )

        def show_handler_info(call, text: str):
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
            container_name = split_string_into_octets(call.data)

            # Get logs for the specified container
            logs = self.__get_sanitized_logs(container_name, call, self.bot.token)

            if not logs:
                return show_handler_info(call, text=f"{container_name}: Error getting logs")

            # Define emojis for rendering
            emojis: dict = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
            }

            # Render the logs template
            context = self.jinja.render_templates(
                'd_logs.jinja2',
                emojis=emojis,
                logs=logs,
                container_name=container_name
            )

            keyboard_buttons = self.keyboard.ButtonData(text='Back to all containers',
                                                        callback_data='back_to_containers')

            # Build a custom inline keyboard for navigation
            inline_keyboard = self.keyboard.build_inline_keyboard(keyboard_buttons)

            # Edit the message with the rendered logs and inline keyboard
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=inline_keyboard,
                parse_mode="HTML"
            )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('__manage__'))
        @two_factor_auth_required
        @logged_inline_handler_session
        def manage_container_index(call: CallbackQuery):
            """
            Handles the callback for managing a container.

            Args:
                call (CallbackQuery): The callback query object.

            Returns:
                None
            """
            # Extract container name and called user ID from the callback data
            container_name = split_string_into_octets(call.data)
            called_user_id = split_string_into_octets(call.data, octet_index=2)

            # Check if the user is an admin
            if int(call.from_user.id) != int(called_user_id):
                bot_logger.log("DENIED", f"User {call.from_user.id} NOT is an admin. Denied '__manage__' function")
                return show_handler_info(call=call, text=f"Managing {container_name}: Access denied")

            is_authenticated = session_manager.is_authenticated(call.from_user.id)
            bot_logger.debug(f"User {call.from_user.id} authenticated status: {is_authenticated}")

            if not is_authenticated:
                bot_logger.log("DENIED",
                               f"User {call.from_user.id} NOT authenticated. "
                               f"Denied '__manage__' function for container {container_name}")
                return show_handler_info(call=call, text=f"Managing {container_name}: Not authenticated user")

            # Create the keyboard buttons
            keyboard_buttons = [
                self.keyboard.ButtonData(text="Start",
                                         callback_data=f'__start__:{container_name}:{call.from_user.id}'),
                self.keyboard.ButtonData(text="Stop",
                                         callback_data=f'__stop__:{container_name}:{call.from_user.id}'),
                self.keyboard.ButtonData(text="Restart",
                                         callback_data=f'__restart__:{container_name}:{call.from_user.id}'),
                self.keyboard.ButtonData(text="Rename",
                                         callback_data=f'__rename__:{container_name}:{call.from_user.id}'),
            ]

            # Build the inline keyboard
            inline_keyboard = self.keyboard.build_inline_keyboard(keyboard_buttons)

            # Define the emojis dictionary
            emojis: dict = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
            }

            # Render the template with the container name and emojis
            context = self.jinja.render_templates(
                'd_managing_containers.jinja2',
                container_name=container_name,
                emojis=emojis
            )

            # Edit the message with the new text and inline keyboard
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=context,
                reply_markup=inline_keyboard
            )

        def __managing_action_fabric(call: CallbackQuery):
            """
            Checks if a callback query data starts with a specific action.

            Args:
                call (CallbackQuery): The callback query object.

            Returns:
                bool: True if the callback query data starts with '__start__', '__stop__', or '__restart__',
                False otherwise.
            """
            action = [
                '__start__',
                '__stop__',
                '__restart__',
            ]
            return any(call.data.startswith(callback_data) for callback_data in action)

        @self.bot.callback_query_handler(func=lambda call: __managing_action_fabric(call))
        @two_factor_auth_required
        @logged_inline_handler_session
        def manage_container_action(call: CallbackQuery):
            container_name, called_user_id = split_string_into_octets(call.data), split_string_into_octets(call.data,
                                                                                                           octet_index=2)
            """
            Handles the callback query for managing a container.

            Args:
                call (CallbackQuery): The callback query object.

            Returns:
                None
            """
            if int(call.from_user.id) != int(called_user_id):
                bot_logger.log("DENIED", f"User {call.from_user.id}: Denied '__manage__' function")
                return show_handler_info(call=call, text=f"Starting {container_name}: Access denied")

            if not session_manager.is_authenticated(call.from_user.id):
                bot_logger.log("DENIED", f"User {call.from_user.id}: Not authenticated. Denied '__start__' function")
                return show_handler_info(call=call, text=f"Managing {container_name}: Not authenticated user")

            managing_actions = {
                '__start__': __start_container,
                '__stop__': __stop_container,
                '__restart__': __restart_container,
            }
            managing_action = split_string_into_octets(call.data, octet_index=0)

            if managing_action in managing_actions:
                managing_actions[managing_action](call=call, container_name=container_name)
            else:
                bot_logger.log("ERROR",
                               f"Error occurred while managing {container_name}: Unknown action {managing_action}")

        def __start_container(call: CallbackQuery, container_name: str):
            """
            Starts a Docker container based on the provided container name and user ID.

            Args:
                call (CallbackQuery): The callback query object containing user information.
                container_name (str): The name of the Docker container to start.

            Returns:
                None
            """
            try:
                if self.docker_adapter.managing_container(call.from_user.id, container_name, action="start") is None:
                    return show_handler_info(call=call, text=f"Starting {container_name}: Success")
                else:
                    return show_handler_info(call=call, text=f"Starting {container_name}: Error occurred. See logs")
            except Exception as e:
                bot_logger.log("ERROR", f"Error occurred while starting {container_name}: {e}")
                return

        def __stop_container(call: CallbackQuery, container_name: str):
            """
            Stops a Docker container based on the provided container name and user ID.

            Args:
                call (CallbackQuery): The callback query object containing user information.
                container_name (str): The name of the Docker container to stop.

            Returns:
                None
            """
            try:

                if self.docker_adapter.managing_container(call.from_user.id, container_name, action="stop") is None:
                    return show_handler_info(call=call, text=f"Stopping {container_name}: Success")
                else:
                    return show_handler_info(call=call, text=f"Stopping {container_name}: Error occurred. See logs")
            except Exception as e:
                bot_logger.log("ERROR", f"Error occurred while stopping {container_name}: {e}")
                return

        def __restart_container(call: CallbackQuery, container_name: str):
            """
            Restarts a Docker container based on the provided container name and user ID.

            Args:
                call (CallbackQuery): The callback query object containing user information.
                container_name (str): The name of the Docker container to restart.

            Returns:
                None
            """
            try:
                if self.docker_adapter.managing_container(call.from_user.id, container_name, action="restart") is None:
                    return show_handler_info(call=call, text=f"Restarting {container_name}: Success")
                else:
                    return show_handler_info(call=call, text=f"Restarting {container_name}: Error occurred. See logs")
            except Exception as e:
                bot_logger.log("ERROR", f"Error occurred while restarting {container_name}: {e}")
                return

        def __rename_container(call: CallbackQuery, container_name: str, new_container_name: str):
            """
            Renames a Docker container based on the provided parameters.

            Args:
                call (CallbackQuery): The callback query object containing user information.
                container_name (str): The name of the Docker container to rename.
                new_container_name (str): The new name for the container.

            Returns:
                None
            """
            if self.docker_adapter.is_new_name_valid(new_container_name):
                try:
                    if self.docker_adapter.managing_container(call.from_user.id, container_name, action="rename",
                                                              new_container_name=new_container_name):
                        return show_handler_info(call=call, text=f"Renaming {container_name}: Success")
                    else:
                        return show_handler_info(call=call, text=f"Renaming {container_name}: Error occurred. See logs")
                except Exception as e:
                    bot_logger.log("ERROR", f"Error occurred while renaming {container_name}: {e}")
                    return
            else:
                return show_handler_info(call=call, text=f"Renaming {container_name}: Invalid new name")
