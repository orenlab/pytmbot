def is_new_name_valid(new_name: str) -> bool:
    if len(new_name) not in (1, 64):
        return False
    if new_name.isspace():
        return False
    return True


def is_valid_totp_code(totp_code: str) -> bool:
    return len(totp_code) == 6 and totp_code.isdigit()


def is_bot_development(app_version: str) -> bool:
    return len(app_version) > 6
