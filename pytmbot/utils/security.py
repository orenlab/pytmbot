import secrets

from pytmbot.settings import settings


def sanitize_exception(exception: Exception) -> str:
    exception_str = str(exception)
    secret_map = {
        secret.get_secret_value(): "******************"
        for secret in (
            settings.bot_token.prod_token[0],
            settings.bot_token.dev_bot_token[0],
            settings.plugins_config.outline.api_url[0],
            settings.plugins_config.outline.cert[0],
        )
    }
    for secret, placeholder in secret_map.items():
        exception_str = exception_str.replace(secret, placeholder, 1)
    return exception_str


def generate_secret_token(secret_length: int = 32) -> str:
    return secrets.token_urlsafe(secret_length)


def mask_token_in_message(message: str, token: str, visible_chars: int = 4) -> str:
    if len(token) <= visible_chars * 2:
        return message.replace(token, "*" * len(token))
    return message.replace(
        token,
        f"{token[:visible_chars]}{'*' * (len(token) - visible_chars * 2)}{token[-visible_chars:]}",
    )


def mask_username(username: str, visible: int = 3) -> str:
    """Mask Telegram username, keeping first and last N characters."""
    if not username:
        return "unknown"
    if len(username) <= visible * 3:
        return "*" * len(username)
    return f"{username[:visible]}{'*' * (len(username) - visible * 3)}{username[-visible:]}"


def mask_user_id(user_id: int, visible: int = 3) -> str:
    """Mask user ID, preserving only part of it."""
    user_id_str = str(user_id)
    if len(user_id_str) <= visible * 2:
        return "*" * len(user_id_str)
    return f"{user_id_str[:visible]}{'*' * (len(user_id_str) - visible * 2)}{user_id_str[-visible:]}"
