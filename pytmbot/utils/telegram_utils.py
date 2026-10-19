#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import re
from typing import Final

from telebot.types import CallbackQuery

type OptionalStr = str | None
type OptionalInt = int | None
type OptionalBool = bool | None
type SanitizedLogInput = str | bytes | int | float | bool | None

# Terminal escape sequences, compiled once. Order matters: string sequences
# (OSC/DCS/SOS/PM/APC) are consumed whole before the generic two-byte forms.
_TERMINAL_ESCAPE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    \x1B\][^\x07\x1B]*(?:\x07|\x1B\\)?      # OSC ... BEL | ST (window titles, links)
    | \x1B[PX^_][^\x1B]*(?:\x1B\\)?         # DCS / SOS / PM / APC ... ST
    | (?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~]      # CSI (colors, cursor movement)
    | \x1B[ -/]*[0-~]                       # nF / Fp / Fe / Fs escape sequences
    | \x1B                                  # stray ESC
    """,
    re.VERBOSE,
)
# C0/C1 control characters except tab, line feed and carriage return.
_CONTROL_CHARACTERS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\x80-\x9F]"
)
# Telegram bot tokens look like "<bot id>:<35-char secret>".
_MIN_TOKEN_SECRET_LENGTH: Final[int] = 20


def strip_terminal_sequences(text: str) -> str:
    """Remove terminal escape sequences and control characters from text."""
    without_sequences = _TERMINAL_ESCAPE_PATTERN.sub("", text)
    return _CONTROL_CHARACTERS_PATTERN.sub("", without_sequences)


def _secret_values(token: str) -> set[str]:
    """Collect secret fragments worth masking (the token and its secret half)."""
    values = {token}
    _, separator, token_secret = token.partition(":")
    if separator and len(token_secret) >= _MIN_TOKEN_SECRET_LENGTH:
        values.add(token_secret)
    return {value for value in values if value}


def sanitize_logs(
    container_logs: SanitizedLogInput,
    callback_query: CallbackQuery | None,
    token: str,
) -> str:
    """
    Make container logs safe to show in Telegram.

    Removes terminal escape sequences (CSI, OSC, DCS and other ESC forms) and
    control characters, and masks the bot token (also when only its secret
    half appears). Ordinary words are never masked: names of the user who
    pressed the button are not secrets and masking them corrupted unrelated
    log lines.

    Args:
        container_logs: Container logs (string or any object with __str__)
        callback_query: Kept for call-site compatibility; not used for masking
        token: Bot token to mask

    Returns:
        str: Sanitized logs
    """
    del callback_query
    if container_logs is None:
        return ""
    if isinstance(container_logs, bytes):
        text = container_logs.decode("utf-8", errors="replace")
    else:
        text = str(container_logs)

    text = strip_terminal_sequences(text)

    secrets = {value for value in _secret_values(token) if value in text}
    if not secrets:
        return text

    # Replace all secrets in a single pass, longest first, to avoid N copies.
    pattern = re.compile(
        "|".join(re.escape(value) for value in sorted(secrets, key=len, reverse=True))
    )
    return pattern.sub(lambda match: "*" * len(match.group(0)), text)


def callback_query_id(callback_query: CallbackQuery) -> str:
    """Return the callback query id passed to ``TeleBot.answer_callback_query``."""
    return str(callback_query.id)
