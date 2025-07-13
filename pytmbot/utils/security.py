#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import re
import secrets
from typing import Dict, Optional, Set

from pytmbot.settings import settings


def sanitize_exception(exception: Exception) -> str:
    """
    Sanitizes exception messages by replacing sensitive information with placeholders.

    Args:
        exception: The exception to sanitize

    Returns:
        str: Sanitized exception string with sensitive data masked
    """
    exception_str = str(exception)

    # Build secret map with safe access to secret values
    secret_map: Dict[str, str] = {}

    # Safely extract secrets with error handling
    try:
        secrets_to_mask = [
            settings.bot_token.prod_token[0],
            settings.bot_token.dev_bot_token[0],
            settings.plugins_config.outline.api_url[0],
            settings.plugins_config.outline.cert[0],
        ]

        for secret in secrets_to_mask:
            if secret and hasattr(secret, "get_secret_value"):
                secret_value = secret.get_secret_value()
                if secret_value and len(secret_value.strip()) > 0:
                    secret_map[secret_value] = "*" * len(secret_value)
    except (AttributeError, IndexError, TypeError):
        # If settings structure is different, continue with empty secret_map
        pass

    # Sort secrets by length (longest first) to avoid partial replacements
    sorted_secrets = sorted(secret_map.items(), key=lambda x: len(x[0]), reverse=True)

    # Replace all occurrences of each secret
    for secret_value, placeholder in sorted_secrets:
        exception_str = exception_str.replace(secret_value, placeholder)

    return exception_str


def generate_secret_token(secret_length: int = 32) -> str:
    """
    Generates a cryptographically secure URL-safe token.

    Args:
        secret_length: Length of the token to generate (default: 32)

    Returns:
        str: URL-safe token

    Raises:
        ValueError: If secret_length is not positive
    """
    if secret_length <= 0:
        raise ValueError("Secret length must be positive")

    return secrets.token_urlsafe(secret_length)


def mask_token_in_message(message: str, token: str, visible_chars: int = 4) -> str:
    """
    Masks token in message while preserving readability.

    Args:
        message: The message containing the token
        token: The token to mask
        visible_chars: Number of characters to keep visible at start and end

    Returns:
        str: Message with token masked
    """
    if not token or not message:
        return message

    # Validate visible_chars parameter
    if visible_chars < 0:
        visible_chars = 0

    # For very short tokens, mask completely
    min_mask_length = 8  # Internal constant for security
    if len(token) < min_mask_length:
        return message.replace(token, "*" * len(token))

    # For tokens where visible chars would show too much, mask completely
    if len(token) <= visible_chars * 2:
        return message.replace(token, "*" * len(token))

    # Create masked token
    masked_token = (
        f"{token[:visible_chars]}"
        f"{'*' * (len(token) - visible_chars * 2)}"
        f"{token[-visible_chars:]}"
    )

    return message.replace(token, masked_token)


def mask_username(username: Optional[str], visible: int = 3) -> str:
    """
    Masks Telegram username while keeping some characters visible for identification.

    Args:
        username: The username to mask (can be None)
        visible: Number of characters to keep visible at start and end

    Returns:
        str: Masked username or "unknown" if username is None/empty
    """
    if not username or not username.strip():
        return "unknown"

    username = username.strip()

    # Validate visible parameter
    if visible < 0:
        visible = 0

    # For very short usernames, mask completely
    if len(username) <= 6:
        return "*" * len(username)

    # Ensure we don't show too much of the username
    if len(username) <= visible * 2:
        return "*" * len(username)

    # For backward compatibility, use original logic but with safety checks
    safe_visible = min(
        visible, (len(username) - 3) // 2
    )  # Ensure at least 3 chars are masked

    if safe_visible <= 0:
        return "*" * len(username)

    return (
        f"{username[:safe_visible]}"
        f"{'*' * (len(username) - safe_visible * 2)}"
        f"{username[-safe_visible:]}"
    )


def mask_user_id(user_id: Optional[int], visible: int = 3) -> str:
    """
    Masks user ID while preserving some digits for identification.

    Args:
        user_id: The user ID to mask (can be None)
        visible: Number of digits to keep visible at start and end

    Returns:
        str: Masked user ID or "unknown" if user_id is None
    """
    if user_id is None:
        return "unknown"

    user_id_str = str(abs(user_id))  # Handle negative IDs

    # Validate visible parameter
    if visible < 0:
        visible = 0

    # For very short IDs, mask completely
    if len(user_id_str) <= 6:
        return "*" * len(user_id_str)

    # Ensure we don't show too much of the ID
    if len(user_id_str) <= visible * 2:
        return "*" * len(user_id_str)

    # For backward compatibility, use original logic but with safety checks
    safe_visible = min(
        visible, (len(user_id_str) - 4) // 2
    )  # Ensure at least 4 chars are masked

    if safe_visible <= 0:
        return "*" * len(user_id_str)

    return (
        f"{user_id_str[:safe_visible]}"
        f"{'*' * (len(user_id_str) - safe_visible * 2)}"
        f"{user_id_str[-safe_visible:]}"
    )


def sanitize_sensitive_data(
    text: str,
    tokens: Optional[Set[str]] = None,
    usernames: Optional[Set[str]] = None,
    user_ids: Optional[Set[int]] = None,
) -> str:
    """
    Comprehensive sanitization of sensitive data in text.

    Args:
        text: Text to sanitize
        tokens: Set of tokens to mask
        usernames: Set of usernames to mask
        user_ids: Set of user IDs to mask

    Returns:
        str: Sanitized text with sensitive data masked
    """
    if not text:
        return text

    sanitized_text = text

    # Mask tokens
    if tokens:
        for token in tokens:
            if token:
                sanitized_text = mask_token_in_message(sanitized_text, token)

    # Mask usernames
    if usernames:
        for username in usernames:
            if username:
                masked_username = mask_username(username)
                sanitized_text = sanitized_text.replace(username, masked_username)

    # Mask user IDs
    if user_ids:
        for user_id in user_ids:
            if user_id is not None:
                user_id_str = str(user_id)
                masked_user_id = mask_user_id(user_id)
                sanitized_text = sanitized_text.replace(user_id_str, masked_user_id)

    # Additional security: mask potential API keys, tokens, and secrets
    # Pattern for common secret formats
    secret_patterns = [
        r"\b[A-Za-z0-9]{32,}\b",  # Long alphanumeric strings (potential tokens)
        r"\b[A-Za-z0-9+/]{20,}={0,2}\b",  # Base64-like strings
        r"\bbot[0-9]{8,10}:[A-Za-z0-9_-]{35}\b",  # Telegram bot tokens
        r"\b[0-9]{8,12}:[A-Za-z0-9_-]{35}\b",  # Alternative bot token format
    ]

    for pattern in secret_patterns:
        sanitized_text = re.sub(
            pattern,
            lambda m: "*" * len(m.group(0)),
            sanitized_text,
            flags=re.IGNORECASE,
        )

    return sanitized_text
