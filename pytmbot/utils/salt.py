import base64
import secrets


def generate_random_auth_salt(length=32) -> str:
    """
    Generates a random authentication salt for the bot.

    Args:
        length (int, optional): The length of the salt in bytes. Defaults to 32.

    Returns:
        str: The generated authentication salt.
    """
    # Ensure length is a positive integer
    if not isinstance(length, int) or length <= 0:
        raise ValueError("Length must be a positive integer")

    # Generate random bytes and encode them as base32
    random_bytes = secrets.token_bytes(length)
    salt = base64.b32encode(random_bytes).decode('utf-8')
    return salt


if __name__ == "__main__":
    # Ensure that the module is executed directly and not imported
    print("========================================================")
    print("Generating random authentication salt...")
    print(generate_random_auth_salt())
