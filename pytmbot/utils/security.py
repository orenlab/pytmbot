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
        return message.replace(token, '*' * len(token))
    return message.replace(token,
                           f"{token[:visible_chars]}{'*' * (len(token) - visible_chars * 2)}{token[-visible_chars:]}")
