#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import importlib
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .cli import parse_cli_args as parse_cli_args
    from .conversion import (
        as_object_dict as as_object_dict,
    )
    from .conversion import (
        to_float as to_float,
    )
    from .conversion import (
        to_float_strict as to_float_strict,
    )
    from .conversion import (
        to_int as to_int,
    )
    from .data_processing import (
        round_up_tuple as round_up_tuple,
    )
    from .data_processing import (
        set_naturalsize as set_naturalsize,
    )
    from .data_processing import (
        set_naturaltime as set_naturaltime,
    )
    from .data_processing import (
        split_string_into_octets as split_string_into_octets,
    )
    from .emoji import EmojiConverter as EmojiConverter
    from .environment import (
        get_environment_state as get_environment_state,
    )
    from .environment import (
        is_running_in_docker as is_running_in_docker,
    )
    from .message_deletion import deletion_manager as deletion_manager
    from .security import (
        generate_secret_token as generate_secret_token,
    )
    from .security import (
        mask_chat_id as mask_chat_id,
    )
    from .security import (
        mask_ip_address as mask_ip_address,
    )
    from .security import (
        mask_token_in_message as mask_token_in_message,
    )
    from .security import (
        mask_user_id as mask_user_id,
    )
    from .security import (
        mask_username as mask_username,
    )
    from .security import (
        mask_webhook_path as mask_webhook_path,
    )
    from .security import (
        sanitize_exception as sanitize_exception,
    )
    from .telegram_utils import sanitize_logs as sanitize_logs
    from .validation import (
        is_bot_development as is_bot_development,
    )
    from .validation import (
        is_new_name_valid as is_new_name_valid,
    )
    from .validation import (
        is_valid_totp_code as is_valid_totp_code,
    )

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


_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "parse_cli_args": (".cli", "parse_cli_args"),
    "as_object_dict": (".conversion", "as_object_dict"),
    "to_float": (".conversion", "to_float"),
    "to_float_strict": (".conversion", "to_float_strict"),
    "to_int": (".conversion", "to_int"),
    "round_up_tuple": (".data_processing", "round_up_tuple"),
    "set_naturalsize": (".data_processing", "set_naturalsize"),
    "set_naturaltime": (".data_processing", "set_naturaltime"),
    "split_string_into_octets": (".data_processing", "split_string_into_octets"),
    "EmojiConverter": (".emoji", "EmojiConverter"),
    "is_running_in_docker": (".environment", "is_running_in_docker"),
    "get_environment_state": (".environment", "get_environment_state"),
    "sanitize_exception": (".security", "sanitize_exception"),
    "generate_secret_token": (".security", "generate_secret_token"),
    "mask_ip_address": (".security", "mask_ip_address"),
    "mask_token_in_message": (".security", "mask_token_in_message"),
    "mask_webhook_path": (".security", "mask_webhook_path"),
    "mask_chat_id": (".security", "mask_chat_id"),
    "mask_username": (".security", "mask_username"),
    "mask_user_id": (".security", "mask_user_id"),
    "sanitize_logs": (".telegram_utils", "sanitize_logs"),
    "deletion_manager": (".message_deletion", "deletion_manager"),
    "is_new_name_valid": (".validation", "is_new_name_valid"),
    "is_valid_totp_code": (".validation", "is_valid_totp_code"),
    "is_bot_development": (".validation", "is_bot_development"),
}


_RESOLVED_CACHE: dict[str, object] = {}


def __getattr__(name: str) -> object:
    if name in _RESOLVED_CACHE:
        return _RESOLVED_CACHE[name]

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"Module {__name__!r} has no attribute {name!r}")

    module_path, attr_name = target

    if not module_path.startswith("."):
        raise AttributeError(
            f"Unsafe module path {module_path!r} for attribute {name!r}: "
            "only relative imports are permitted in _LAZY_EXPORTS"
        )

    try:
        module = importlib.import_module(module_path, __name__)
    except ImportError as exc:
        raise ImportError(
            f"Cannot import module {module_path!r} while resolving {__name__}.{name}"
        ) from exc

    try:
        obj = getattr(module, attr_name)
    except AttributeError as exc:
        raise AttributeError(
            f"Module {module_path!r} has no attribute {attr_name!r} "
            f"(requested as {__name__}.{name})"
        ) from exc

    _RESOLVED_CACHE[name] = obj
    return obj
