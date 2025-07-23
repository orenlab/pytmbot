#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Enhanced Docker utilities with comprehensive container data parsing.
"""

import re
from datetime import datetime
from functools import lru_cache
from typing import Dict, Any, Union, List, Optional

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.containers_info import (
    fetch_container_logs,
    fetch_full_container_details,
)
from pytmbot.globals import em
from pytmbot.logs import Logger
from pytmbot.utils import set_naturalsize, sanitize_logs, set_naturaltime

logger = Logger()


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
        callback_query_id=call.id, text=text, show_alert=True
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
        "thought_balloon",
        "luggage",
        "minus",
        "backhand_index_pointing_down",
        "banjo",
        "basket",
        "flag_in_hole",
        "railway_car",
        "radio",
        "puzzle_piece",
        "radioactive",
        "safety_pin",
        "sandwich",
        "package",
        "gear",
        "chart_increasing",
        "globe_with_meridians",
        "herb",
        "spiral_calendar",
        "bullseye",
        "BACK_arrow",
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


def sanitize_environment_variables(env_list: List[str]) -> List[str]:
    """
    Filter out sensitive environment variables for display.

    Args:
        env_list: List of environment variables in "KEY=VALUE" format

    Returns:
        List[str]: Filtered environment variables
    """
    if not env_list:
        return []

    # Patterns for sensitive variables (case insensitive)
    sensitive_patterns = [
        r".*password.*",
        r".*secret.*",
        r".*key.*",
        r".*token.*",
        r".*auth.*",
        r".*credential.*",
        r".*api.*key.*",
        r".*database.*url.*",
        r".*db.*password.*",
        r".*private.*",
        r".*ssl.*cert.*",
        r".*ssl.*key.*",
        r".*jwt.*",
    ]

    # Compile patterns for efficiency
    compiled_patterns = [
        re.compile(pattern, re.IGNORECASE) for pattern in sensitive_patterns
    ]

    filtered_vars = []
    for var in env_list:
        var_name = var.split("=", 1)[0] if "=" in var else var

        # Check if variable name matches any sensitive pattern
        is_sensitive = any(pattern.match(var_name) for pattern in compiled_patterns)

        if is_sensitive:
            filtered_vars.append(f"{var_name}=<HIDDEN>")
        else:
            # Limit value length for display
            if "=" in var:
                key, value = var.split("=", 1)
                if len(value) > 100:
                    value = value[:97] + "..."
                filtered_vars.append(f"{key}={value}")
            else:
                filtered_vars.append(var)

    return filtered_vars[:20]  # Limit to first 20 variables


def parse_container_basic_info(container_details) -> Dict[str, Any]:
    """
    Extract basic container information from container details.

    Args:
        container_details: Container object or dictionary

    Returns:
        Dict with basic container info
    """
    try:
        # Handle both Container object and dictionary formats
        if hasattr(container_details, "attrs"):
            # It's a Container object
            attrs = container_details.attrs
        elif isinstance(container_details, dict) and "attrs" in container_details:
            # It's a dictionary with attrs key
            attrs = container_details["attrs"]
        else:
            # It might be the attrs dictionary directly
            attrs = container_details

        config = attrs.get("Config", {})
        state = attrs.get("State", {})

        # Image info (safe to display)
        image_info = config.get("Image", "unknown")
        image_parts = image_info.split(":")
        image_name = image_parts[0] if image_parts else "unknown"
        image_tag = image_parts[1] if len(image_parts) > 1 else "latest"

        # Calculate uptime
        started_at = state.get("StartedAt", "")
        uptime = (
            set_naturaltime(datetime.fromisoformat(started_at)) if started_at else "N/A"
        )

        return {
            "id": attrs.get("Id", "")[:12],  # Short ID
            "name": attrs.get("Name", "").lstrip("/"),
            "image_name": image_name,
            "image_tag": image_tag,
            "status": state.get("Status", "unknown"),
            "running": state.get("Running", False),
            "paused": state.get("Paused", False),
            "restarting": state.get("Restarting", False),
            "restart_count": state.get("RestartCount", 0),
            "exit_code": state.get("ExitCode", 0),
            "created": attrs.get("Created", ""),
            "started_at": started_at,
            "uptime": uptime,
        }
    except Exception as e:
        logger.error(f"Error parsing container basic info: {e}")
        return {}


def parse_container_resources(container_details) -> Dict[str, Any]:
    """
    Extract container resource configuration and limits.

    Args:
        container_details: Container object or dictionary

    Returns:
        Dict with resource information
    """
    try:
        # Handle both Container object and dictionary formats
        if hasattr(container_details, "attrs"):
            # It's a Container object
            attrs = container_details.attrs
        elif isinstance(container_details, dict) and "attrs" in container_details:
            # It's a dictionary with attrs key
            attrs = container_details["attrs"]
        else:
            # It might be the attrs dictionary directly
            attrs = container_details

        host_config = attrs.get("HostConfig", {})

        # Memory limits
        memory_limit = host_config.get("Memory", 0)
        memory_swap = host_config.get("MemorySwap", 0)

        # CPU limits
        cpu_shares = host_config.get("CpuShares", 0)
        cpu_quota = host_config.get("CpuQuota", 0)
        cpu_period = host_config.get("CpuPeriod", 0)
        cpuset_cpus = host_config.get("CpusetCpus", "")

        return {
            "memory_limit": set_naturalsize(memory_limit)
            if memory_limit > 0
            else "No limit",
            "memory_swap": set_naturalsize(memory_swap)
            if memory_swap > 0
            else "No limit",
            "cpu_shares": cpu_shares if cpu_shares > 0 else "Default (1024)",
            "cpu_quota": f"{cpu_quota}/{cpu_period}"
            if cpu_quota > 0 and cpu_period > 0
            else "No limit",
            "cpuset_cpus": cpuset_cpus if cpuset_cpus else "All CPUs",
            "restart_policy": host_config.get("RestartPolicy", {}).get("Name", "no"),
            "max_restart_count": host_config.get("RestartPolicy", {}).get(
                "MaximumRetryCount", 0
            ),
        }
    except Exception as e:
        logger.error(f"Error parsing container resources: {e}")
        return {}


def parse_container_network_info(container_details) -> Dict[str, Any]:
    """
    Extract container network configuration (safe subset).

    Args:
        container_details: Container object or dictionary

    Returns:
        Dict with network information
    """
    try:
        # Handle both Container object and dictionary formats
        if hasattr(container_details, "attrs"):
            # It's a Container object
            attrs = container_details.attrs
        elif isinstance(container_details, dict) and "attrs" in container_details:
            # It's a dictionary with attrs key
            attrs = container_details["attrs"]
        else:
            # It might be the attrs dictionary directly
            attrs = container_details

        network_settings = attrs.get("NetworkSettings", {})
        host_config = attrs.get("HostConfig", {})

        # Port mappings (public info)
        port_bindings = host_config.get("PortBindings", {})
        ports = []
        for container_port, host_bindings in port_bindings.items():
            if host_bindings:
                for binding in host_bindings:
                    host_port = binding.get("HostPort", "auto")
                    ports.append(f"{host_port}:{container_port}")
            else:
                ports.append(container_port)

        # Network mode
        network_mode = host_config.get("NetworkMode", "default")

        # Connected networks (names only, not IPs for security)
        networks = list(network_settings.get("Networks", {}).keys())

        return {
            "network_mode": network_mode,
            "ports": ports[:10],  # Limit display
            "networks": networks[:5],  # Limit display
            "published_ports": len(ports),
        }
    except Exception as e:
        logger.error(f"Error parsing container network info: {e}")
        return {}


def parse_container_environment(container_details) -> Dict[str, Any]:
    """
    Extract and sanitize container environment information.

    Args:
        container_details: Container object or dictionary

    Returns:
        Dict with environment information
    """
    try:
        # Handle both Container object and dictionary formats
        if hasattr(container_details, "attrs"):
            # It's a Container object
            attrs = container_details.attrs
        elif isinstance(container_details, dict) and "attrs" in container_details:
            # It's a dictionary with attrs key
            attrs = container_details["attrs"]
        else:
            # It might be the attrs dictionary directly
            attrs = container_details

        config = attrs.get("Config", {})

        # Environment variables (sanitized)
        env_vars = config.get("Env", [])
        safe_env_vars = sanitize_environment_variables(env_vars)

        # Working directory
        working_dir = config.get("WorkingDir", "/")

        # User
        user = config.get("User", "root")

        # Command and args (safe to display)
        cmd = config.get("Cmd", [])
        entrypoint = config.get("Entrypoint", [])

        return {
            "environment_vars": safe_env_vars,
            "working_dir": working_dir,
            "user": user,
            "command": " ".join(cmd) if cmd else "N/A",
            "entrypoint": " ".join(entrypoint) if entrypoint else "N/A",
            "env_count": len(env_vars),
        }
    except Exception as e:
        logger.error(f"Error parsing container environment: {e}")
        return {}


def parse_container_attrs(container_attrs) -> Dict:
    """
    Parse the container attributes with enhanced environment variable handling.

    Args:
        container_attrs: Container object or dictionary containing container attributes.

    Returns:
        Dict: A dictionary with enhanced container attributes.
    """
    try:
        # Handle both Container object and dictionary formats
        if hasattr(container_attrs, "attrs"):
            # It's a Container object
            attrs = container_attrs.attrs
        elif isinstance(container_attrs, dict) and "State" in container_attrs:
            # It's already the attrs dictionary
            attrs = container_attrs
        else:
            # Fallback - assume it's a dictionary with attrs key
            attrs = container_attrs.get("attrs", container_attrs)

        running_state = attrs.get("State", {})
        config_attrs = attrs.get("Config", {})

        # Sanitize environment variables
        raw_env = config_attrs.get("Env", [])
        safe_env = sanitize_environment_variables(raw_env)

        return {
            "running": running_state.get("Running", False),
            "paused": running_state.get("Paused", False),
            "restarting": running_state.get("Restarting", False),
            "restarting_count": attrs.get("RestartCount", 0),
            "dead": running_state.get("Dead", False),
            "exit_code": running_state.get("ExitCode", None),
            "env": safe_env,  # Use sanitized environment variables
            "env_count": len(raw_env),  # Original count
            "command": config_attrs.get("Cmd", ""),
            "args": attrs.get("Args", ""),
        }
    except Exception as e:
        logger.error(f"Error parsing container attributes: {e}")
        return {}


def get_comprehensive_container_details(
    container_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Get comprehensive container details with enhanced parsing and security.

    Args:
        container_name: Name of the container

    Returns:
        Dict with all container details or None if container not found
    """
    try:
        # Get raw container details
        container_details = get_container_full_details(container_name)

        if not container_details:
            return None

        # Parse different aspects of container data
        basic_info = parse_container_basic_info(container_details)
        resources = parse_container_resources(container_details)
        network_info = parse_container_network_info(container_details)
        environment = parse_container_environment(container_details)

        # Initialize empty stats
        stats = {}

        # Handle stats differently based on container details type
        if hasattr(container_details, "stats"):
            # For Container object, stats() returns a generator
            try:
                stats_gen = container_details.stats(
                    stream=False
                )  # Get single stats reading
                if isinstance(stats_gen, dict):
                    stats = stats_gen
                else:
                    # Handle case where it's actually a generator
                    stats = next(stats_gen, {})
            except Exception as e:
                logger.warning(f"Couldn't get container stats: {e}")
        elif isinstance(container_details, dict):
            stats = container_details.get("stats", {})

        # Parse stats if available
        memory_stats = parse_container_memory_stats(stats) if stats else {}
        cpu_stats = parse_container_cpu_stats(stats) if stats else {}
        network_stats = parse_container_network_stats(stats) if stats else {}

        # Combine all data
        comprehensive_details = {
            **basic_info,
            "resources": resources,
            "network": network_info,
            "environment": environment,
            "stats": {
                "memory": memory_stats,
                "cpu": cpu_stats,
                "network": network_stats,
            },
        }

        return comprehensive_details

    except Exception as e:
        logger.error(
            f"Error getting comprehensive container details for {container_name}: {e}"
        )
        return None


def parse_container_memory_stats(
    container_stats: Dict[str, Any],
) -> Dict[str, Union[str, float]]:
    """
    Parse the memory statistics of a container with enhanced formatting.

    Args:
        container_stats (Dict): The dictionary containing memory statistics of a container.

    Returns:
        Dict: A dictionary with keys for 'mem_usage', 'mem_limit', and 'mem_percent'.
    """
    # Retrieve the memory statistics from the container_stats dictionary
    memory_stats = container_stats.get("memory_stats", {})

    # Calculate the memory usage and limit
    usage = memory_stats.get("usage", 0)
    limit = memory_stats.get("limit", 0)

    # Use enhanced formatting for better readability
    mem_usage = set_naturalsize(usage)
    mem_limit = set_naturalsize(limit)

    # Calculate the percentage of memory used by the container
    mem_percent = round(usage / limit * 100, 2) if limit > 0 else 0

    return {"mem_usage": mem_usage, "mem_limit": mem_limit, "mem_percent": mem_percent}


def parse_container_cpu_stats(container_stats) -> Dict[str, Union[int, float]]:
    """
    Parse the CPU statistics of a container with enhanced calculations.

    Args:
        container_stats: The dictionary containing CPU statistics of a container.

    Returns:
        Dict: A dictionary with CPU usage statistics.
    """
    try:
        cpu_stats = container_stats.get("cpu_stats", {})
        precpu_stats = container_stats.get("precpu_stats", {})

        # Get throttling data
        throttling_data = cpu_stats.get("throttling_data", {})

        # Calculate CPU percentage
        cpu_usage = cpu_stats.get("cpu_usage", {})
        precpu_usage = precpu_stats.get("cpu_usage", {})

        cpu_total = cpu_usage.get("total_usage", 0)
        precpu_total = precpu_usage.get("total_usage", 0)

        system_cpu = cpu_stats.get("system_cpu_usage", 0)
        pre_system_cpu = precpu_stats.get("system_cpu_usage", 0)

        cpu_percent = 0.0
        if system_cpu > pre_system_cpu and cpu_total > precpu_total:
            cpu_delta = cpu_total - precpu_total
            system_delta = system_cpu - pre_system_cpu
            num_cpus = len(cpu_usage.get("percpu_usage", [1]))
            cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0

        return {
            "periods": throttling_data.get("periods", 0),
            "throttled_periods": throttling_data.get("throttled_periods", 0),
            "throttling_data": throttling_data.get("throttled_time", 0),
            "cpu_percent": round(cpu_percent, 2),
        }
    except Exception as e:
        logger.error(f"Error parsing CPU stats: {e}")
        return {
            "periods": 0,
            "throttled_periods": 0,
            "throttling_data": 0,
            "cpu_percent": 0.0,
        }


def parse_container_network_stats(container_stats: Dict) -> Dict:
    """
    Parse the network statistics of a container with enhanced formatting.

    Args:
        container_stats (Dict): The dictionary containing network statistics of a container.

    Returns:
        Dict: A dictionary with network statistics.
    """
    try:
        networks = container_stats.get("networks", {})

        # Sum all network interfaces
        total_rx_bytes = sum(net.get("rx_bytes", 0) for net in networks.values())
        total_tx_bytes = sum(net.get("tx_bytes", 0) for net in networks.values())
        total_rx_dropped = sum(net.get("rx_dropped", 0) for net in networks.values())
        total_tx_dropped = sum(net.get("tx_dropped", 0) for net in networks.values())
        total_rx_errors = sum(net.get("rx_errors", 0) for net in networks.values())
        total_tx_errors = sum(net.get("tx_errors", 0) for net in networks.values())

        return {
            "rx_bytes": set_naturalsize(total_rx_bytes),
            "tx_bytes": set_naturalsize(total_tx_bytes),
            "rx_dropped": total_rx_dropped,
            "tx_dropped": total_tx_dropped,
            "rx_errors": total_rx_errors,
            "tx_errors": total_tx_errors,
        }
    except Exception as e:
        logger.error(f"Error parsing network stats: {e}")
        return {
            "rx_bytes": "0 B",
            "tx_bytes": "0 B",
            "rx_dropped": 0,
            "tx_dropped": 0,
            "rx_errors": 0,
            "tx_errors": 0,
        }
