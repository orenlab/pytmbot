#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import base64
import io

import pyotp
import qrcode


class TOTPGenerator:
    """
    Class for generating Time-based One-time Password (TOTP) authentication URIs and QR codes.

    Attributes:
        user_id (str): The user ID for which the TOTP is being generated.
        account_name (str): The account name associated with the TOTP.
        salt (str): A predefined salt value for generating the secret key.

    Methods:
        __init__(self, user_id: str, account_name: str)
        __exit__(self, exc_type, exc_val, exc_tb)
        __enter__(self)
        __generate_totp_secret(self)
        __generate_totp_auth_uri(self)
        generate_totp_qr_code(self)
    """

    def __init__(self, user_id: str, account_name: str):
        """
        Initialize the TOTPGenerator with the provided user_id and account_name.

        Args:
            user_id (str): The user ID for which the TOTP is being generated.
            account_name (str): The account name associated with the TOTP.

        This function also sets a predefined salt value for generating the secret key.
        """
        self.user_id: str = user_id
        self.account_name: str = account_name.replace(' ', '_')
        self.salt: str = "j7F&2sL9@5dP#1zR*8fT5vG3"

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Clean up the TOTPGenerator instance by setting secret, account_name, and salt to None.

        Args:
            exc_type: The type of the exception.
            exc_val: The exception value.
            exc_tb: The exception traceback.

        Returns:
            None
        """
        self.user_id = None
        self.account_name = None
        self.salt = None

    def __enter__(self):
        """
        Enter the context.

        Returns:
            self: The current instance.
        """
        # Return the current instance
        return self

    def __generate_totp_secret(self) -> str:
        """
        Generate a Time-based One-time Password (TOTP) secret key.

        Returns:
            str: The TOTP secret key.
        """
        # Concatenate the user ID and salt, then encode to utf-8 and base64
        encoded_bytes = base64.urlsafe_b64encode((self.user_id + self.salt).encode('utf-8'))

        # Return the first 30 characters of the encoded string in lowercase
        return encoded_bytes[:30].decode('utf-8').lower()

    def __generate_totp_auth_uri(self) -> str:
        """
        Generate a Time-based One-time Password (TOTP) authentication URI.

        This function generates a TOTP authentication URI based on the secret key and account name.

        Returns:
            str: The TOTP authentication URI.
        """
        # Generate TOTP object using the secret key
        totp = pyotp.TOTP(self.__generate_totp_secret())

        # Generate the URI using the TOTP object and account name
        uri = totp.provisioning_uri(name=self.account_name, issuer_name="pyTMbot TOTP")

        # Return the generated TOTP authentication URI
        return uri

    def generate_totp_qr_code(self) -> bytes:
        """
        Generate a QR code for the TOTP authentication URI and return it as bytes.

        Returns:
            bytes: The QR code as bytes.
        """
        # Generate the TOTP authentication URI
        auth_uri = self.__generate_totp_auth_uri()

        # Create a QR code from the authentication URI
        qr_code = qrcode.make(auth_uri)

        # Save the QR code as bytes in a BytesIO object
        with io.BytesIO() as img_bytes:
            qr_code.save(img_bytes)

            # Return the bytes of the QR code
            return img_bytes.getvalue()
