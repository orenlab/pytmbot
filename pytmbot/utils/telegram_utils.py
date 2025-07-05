import re
from typing import Union, Tuple, Any, Optional

from telebot.types import CallbackQuery, Message

from pytmbot.utils.data_processing import find_in_args, find_in_kwargs

OptionalStr = Optional[str]
OptionalInt = Optional[int]
OptionalBool = Optional[bool]
MessageInfo = Tuple[OptionalStr, OptionalInt, OptionalStr, OptionalBool, OptionalStr]
InlineMessageInfo = Tuple[OptionalStr, OptionalInt, OptionalBool]


def get_message_full_info(*args: Any, **kwargs: Any) -> MessageInfo:
    message = find_in_args(args, Message) or find_in_kwargs(kwargs, Message)
    if message:
        user = message.from_user
        return user.username, user.id, user.language_code, user.is_bot, message.text
    return None, None, None, None, None


def get_inline_message_full_info(*args: Any, **kwargs: Any) -> InlineMessageInfo:
    message = find_in_args(args, CallbackQuery) or find_in_kwargs(kwargs, CallbackQuery)
    if message:
        user = message.message.from_user
        return user.username, user.id, user.is_bot
    return None, None, None


def sanitize_logs(
    container_logs: Union[str, Any], callback_query: CallbackQuery, token: str
) -> str:
    ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    container_logs = ansi_escape.sub("", container_logs)
    user_info = [
        callback_query.from_user.username or "",
        callback_query.from_user.first_name or "",
        callback_query.from_user.last_name or "",
        str(callback_query.message.from_user.id),
        token,
    ]
    for value in user_info:
        container_logs = container_logs.replace(value, "*" * len(value))
    return container_logs
