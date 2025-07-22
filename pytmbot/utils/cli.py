#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import argparse
import logging
from enum import StrEnum
from functools import lru_cache
from typing import Final


class BotMode(StrEnum):
    """Bot operation modes."""

    DEV = "dev"
    PROD = "prod"


class LogLevel(StrEnum):
    """Available log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    ERROR = "ERROR"


class CLIError(Exception):
    """Custom exception for CLI-related errors."""

    pass


class CLIDefaults:
    """Default values for CLI arguments."""

    MODE: Final[BotMode] = BotMode.PROD
    LOG_LEVEL: Final[LogLevel] = LogLevel.INFO
    COLORIZE_LOGS: Final[bool] = True
    WEBHOOK: Final[bool] = False
    SOCKET_HOST: Final[str] = "127.0.0.1"
    PLUGINS: Final[list[str]] = []
    HEALTH_CHECK: Final[bool] = True


def _str_to_bool(value: str) -> bool:
    """Convert string representation to boolean.

    Args:
        value: String value to convert

    Returns:
        bool: Converted boolean value

    Raises:
        CLIError: If value cannot be converted to boolean
    """
    if value.lower() in ("true", "1", "yes", "on"):
        return True
    elif value.lower() in ("false", "0", "no", "off"):
        return False
    else:
        raise CLIError(f"Invalid boolean value: {value}")


def _validate_socket_host(host: str) -> str:
    """Validate socket host format.

    Args:
        host: Host string to validate

    Returns:
        str: Validated host string

    Raises:
        CLIError: If host format is invalid
    """
    if not host or not isinstance(host, str):
        raise CLIError("Socket host must be a non-empty string")

    # Basic validation for common cases
    if not (
            host.replace(".", "").replace(":", "").replace("-", "").isalnum()
            or host in ("localhost", "0.0.0.0")
    ):
        raise CLIError(f"Invalid socket host format: {host}")

    return host


def _validate_plugins(plugins: list[str]) -> list[str]:
    """Validate plugins list.

    Args:
        plugins: List of plugin names

    Returns:
        list[str]: Validated plugins list

    Raises:
        CLIError: If plugins format is invalid
    """
    if not isinstance(plugins, list):
        raise CLIError("Plugins must be a list")

    # Filter out empty strings and validate plugin names
    valid_plugins = []
    for plugin in plugins:
        if not isinstance(plugin, str):
            raise CLIError(f"Plugin name must be a string, got: {type(plugin)}")

        plugin = plugin.strip()
        if plugin:  # Only add non-empty plugins
            if not plugin.replace("_", "").replace("-", "").isalnum():
                raise CLIError(f"Invalid plugin name format: {plugin}")
            valid_plugins.append(plugin)

    return valid_plugins


@lru_cache(maxsize=1)  # Only cache one result since CLI args are parsed once
def parse_cli_args() -> argparse.Namespace:
    """Parse command line arguments using argparse.

    Returns:
        argparse.Namespace: The parsed and validated command line arguments

    Raises:
        CLIError: If argument validation fails
    """
    parser = argparse.ArgumentParser(
        description="PyTMBot - Telegram bot for Docker container management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --mode dev --log-level DEBUG
  %(prog)s --webhook --socket_host 0.0.0.0
  %(prog)s --plugins docker system --health_check
        """,
    )

    # Bot mode
    parser.add_argument(
        "--mode",
        type=BotMode,
        choices=list(BotMode),
        default=CLIDefaults.MODE,
        help=f"Bot operation mode (default: {CLIDefaults.MODE})",
    )

    # Logging configuration
    parser.add_argument(
        "--log-level",
        type=LogLevel,
        choices=list(LogLevel),
        default=CLIDefaults.LOG_LEVEL,
        help=f"Logging level (default: {CLIDefaults.LOG_LEVEL})",
    )

    parser.add_argument(
        "--colorize_logs",
        type=_str_to_bool,
        default=CLIDefaults.COLORIZE_LOGS,
        metavar="BOOL",
        help=f"Enable colorized log output (default: {CLIDefaults.COLORIZE_LOGS})",
    )

    # Webhook configuration
    parser.add_argument(
        "--webhook",
        type=_str_to_bool,
        default=CLIDefaults.WEBHOOK,
        metavar="BOOL",
        help=f"Start in webhook mode (default: {CLIDefaults.WEBHOOK})",
    )

    parser.add_argument(
        "--socket_host",
        type=_validate_socket_host,
        default=CLIDefaults.SOCKET_HOST,
        metavar="HOST",
        help=f"Socket host for webhook mode (default: {CLIDefaults.SOCKET_HOST})",
    )

    # Plugin configuration
    parser.add_argument(
        "--plugins",
        nargs="*",
        default=CLIDefaults.PLUGINS,
        metavar="PLUGIN",
        help="List of plugins to load (default: none)",
    )

    # Health check
    parser.add_argument(
        "--health_check",
        type=_str_to_bool,
        action="store_true",
        help=f"Enable health check endpoint (default: {CLIDefaults.HEALTH_CHECK})",
    )

    # Debug flag for development
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (equivalent to --mode dev --log-level DEBUG)",
    )

    try:
        args = parser.parse_args()

        # Post-process arguments
        if args.debug:
            args.mode = BotMode.DEV
            args.log_level = LogLevel.DEBUG

        # Validate plugins
        args.plugins = _validate_plugins(args.plugins)

        return args

    except (ValueError, TypeError) as e:
        raise CLIError(f"Invalid command line arguments: {e}") from e


def get_log_level() -> int:
    """Get the numeric log level for the logging module.

    Returns:
        int: Numeric log level
    """
    args = parse_cli_args()
    return getattr(logging, args.log_level.value)
