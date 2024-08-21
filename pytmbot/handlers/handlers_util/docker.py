#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from functools import lru_cache
from typing import Dict, Any, Union

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.containers_info import fetch_container_logs, fetch_full_container_details
from pytmbot.globals import em
from pytmbot.utils.utilities import set_naturalsize, sanitize_logs


def show_handler_info(call, text: str, bot: TeleBot):
    """
    Handles the case when a container is not found.

    Args:
        call (CallbackQuery): The callback query object.
        text (str): The text to display in the alert.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    return bot.answer_callback_query(
        callback_query_id=call.id,
        text=text,
        show_alert=True
    )


def get_container_full_details(container_name: str) -> dict:
    """
    Retrieve the full details of a container.

    Args:
        container_name (str): The name of the container.

    Returns:
        dict: The full details of the container.
    """

    # Use a local variable to store the lowercased container name
    lower_container_name = container_name.lower()

    container_details = fetch_full_container_details(lower_container_name)

    return container_details


@lru_cache(maxsize=128)
def get_emojis():
    """
    Return a dictionary of emojis with keys representing emoji names and values as emoji characters.
    """
    emoji_names = [
        'thought_balloon', 'luggage', 'minus', 'backhand_index_pointing_down',
        'banjo', 'basket', 'flag_in_hole', 'railway_car',
        'radio', 'puzzle_piece', 'radioactive', 'safety_pin', 'sandwich'
    ]
    return {emoji_name: em.get_emoji(emoji_name) for emoji_name in emoji_names}


def get_sanitized_logs(container_name: str, call: CallbackQuery, token: str) -> str:
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
    raw_logs = fetch_container_logs(container_name)

    # Sanitize the logs for privacy
    sanitized_logs = sanitize_logs(raw_logs, call, token)

    return sanitized_logs


def parse_container_memory_stats(container_stats: Dict[str, Any]) -> Dict[str, Union[str, float]]:
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


def parse_container_cpu_stats(container_stats) -> Dict[str, Union[int, float]]:
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


def parse_container_network_stats(container_stats: Dict) -> Dict:
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


def parse_container_attrs(container_attrs: Dict) -> Dict:
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
