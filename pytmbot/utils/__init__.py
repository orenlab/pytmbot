#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cli import parse_cli_args
    from .conversion import as_object_dict, to_float, to_float_strict, to_int
    from .data_processing import (
        round_up_tuple,
        set_naturalsize,
        set_naturaltime,
        split_string_into_octets,
    )
    from .emoji import EmojiConverter
    from .environment import (
        get_environment_state,
        is_running_in_docker,
    )
    from .message_deletion import deletion_manager
    from .security import (
        generate_secret_token,
        mask_chat_id,
        mask_ip_address,
        mask_token_in_message,
        mask_user_id,
        mask_username,
        mask_webhook_path,
        sanitize_exception,
    )
    from .telegram_utils import sanitize_logs
    from .validation import (
        is_bot_development,
        is_new_name_valid,
        is_valid_totp_code,
    )


def __getattr__(name: str) -> object:
    if name == "parse_cli_args":
        from .cli import parse_cli_args

        return parse_cli_args

    if name in {
        "as_object_dict",
        "to_float",
        "to_float_strict",
        "to_int",
    }:
        module = importlib.import_module(".conversion", __name__)
        return getattr(module, name)

    if name in {
        "round_up_tuple",
        "set_naturalsize",
        "set_naturaltime",
        "split_string_into_octets",
    }:
        module = importlib.import_module(".data_processing", __name__)
        return getattr(module, name)

    if name == "EmojiConverter":
        from .emoji import EmojiConverter

        return EmojiConverter

    if name in {"is_running_in_docker", "get_environment_state"}:
        module = importlib.import_module(".environment", __name__)
        return getattr(module, name)

    if name in {
        "sanitize_exception",
        "generate_secret_token",
        "mask_ip_address",
        "mask_token_in_message",
        "mask_webhook_path",
        "mask_chat_id",
        "mask_username",
        "mask_user_id",
    }:
        module = importlib.import_module(".security", __name__)
        return getattr(module, name)

    if name == "sanitize_logs":
        module = importlib.import_module(".telegram_utils", __name__)
        return getattr(module, name)

    if name in {
        "is_new_name_valid",
        "is_valid_totp_code",
        "is_bot_development",
    }:
        module = importlib.import_module(".validation", __name__)
        return getattr(module, name)

    if name == "deletion_manager":
        from .message_deletion import deletion_manager

        return deletion_manager

    raise AttributeError(f"Module {__name__} has no attribute {name}")


__all__ = [
    "parse_cli_args",
    "as_object_dict",
    "to_float",
    "to_float_strict",
    "to_int",
    "round_up_tuple",
    "set_naturalsize",
    "set_naturaltime",
    "split_string_into_octets",
    "EmojiConverter",
    "is_running_in_docker",
    "get_environment_state",
    "sanitize_exception",
    "generate_secret_token",
    "mask_ip_address",
    "mask_token_in_message",
    "mask_webhook_path",
    "mask_chat_id",
    "mask_username",
    "mask_user_id",
    "sanitize_logs",
    "deletion_manager",
    "is_new_name_valid",
    "is_valid_totp_code",
    "is_bot_development",
]
