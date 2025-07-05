import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cli import parse_cli_args
    from .data_processing import (
        round_up_tuple,
        find_in_args,
        find_in_kwargs,
        set_naturalsize,
        set_naturaltime,
        split_string_into_octets,
    )
    from .emoji import EmojiConverter
    from .environment import (
        is_running_in_docker,
        get_environment_state,
    )
    from .security import (
        sanitize_exception,
        generate_secret_token,
        mask_token_in_message,
        mask_username,
        mask_user_id,
    )
    from .telegram_utils import (
        get_message_full_info,
        get_inline_message_full_info,
        sanitize_logs,
    )
    from .validation import (
        is_new_name_valid,
        is_valid_totp_code,
        is_bot_development,
    )


def __getattr__(name: str):
    if name == "parse_cli_args":
        from .cli import parse_cli_args

        return parse_cli_args

    if name in {
        "round_up_tuple",
        "find_in_args",
        "find_in_kwargs",
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
        "mask_token_in_message",
        "mask_username",
        "mask_user_id",
    }:
        module = importlib.import_module(".security", __name__)
        return getattr(module, name)

    if name in {
        "get_message_full_info",
        "get_inline_message_full_info",
        "sanitize_logs",
    }:
        module = importlib.import_module(".telegram_utils", __name__)
        return getattr(module, name)

    if name in {
        "is_new_name_valid",
        "is_valid_totp_code",
        "is_bot_development",
    }:
        module = importlib.import_module(".validation", __name__)
        return getattr(module, name)

    raise AttributeError(f"Module {__name__} has no attribute {name}")


__all__ = [
    "parse_cli_args",
    "round_up_tuple",
    "find_in_args",
    "find_in_kwargs",
    "set_naturalsize",
    "set_naturaltime",
    "split_string_into_octets",
    "EmojiConverter",
    "is_running_in_docker",
    "get_environment_state",
    "sanitize_exception",
    "generate_secret_token",
    "mask_token_in_message",
    "get_message_full_info",
    "get_inline_message_full_info",
    "sanitize_logs",
    "is_new_name_valid",
    "is_valid_totp_code",
    "is_bot_development",
]
