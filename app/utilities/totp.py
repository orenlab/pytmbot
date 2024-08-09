#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import base64
import hashlib
import io

import pyotp
import qrcode

from app import bot_logger


class TwoFactorAuthenticator:
    def __init__(self, user_id, username):
        self.user_id = user_id
        self.username = username
        self.salt = b"12345678901234567890"

    def __generate_secret(self) -> str:
        message = self.user_id.encode() + self.username.encode()
        h = hashlib.sha256(message)
        return base64.b32encode(h.digest()).decode()

    def __generate_totp_auth_uri(self) -> str:
        # Generate TOTP object using the secret key
        totp = pyotp.TOTP(self.__generate_secret())

        # Generate the URI using the TOTP object and account name
        uri = totp.provisioning_uri(name=self.username, issuer_name="pyTMbot TOTP")

        # Return the generated TOTP authentication URI
        return uri

    def generate_totp_qr_code(self, ) -> bytes:
        bot_logger.debug(f'Start generating TOTP QR code for user {self.username}...')
        # Generate the TOTP authentication URI
        auth_uri = self.__generate_totp_auth_uri()

        # Create a QR code from the authentication URI
        qr_code = qrcode.make(auth_uri)

        # Save the QR code as bytes in a BytesIO object
        with io.BytesIO() as img_bytes:
            qr_code.save(img_bytes)

            bot_logger.debug(f'TOTP QR code for user {self.username} generated.')
            # Return the bytes of the QR code
            return img_bytes.getvalue()

    def verify_totp_code(self, code: str) -> bool:
        # Generate TOTP object using the secret key
        totp = pyotp.TOTP(self.__generate_secret())
        print(code)
        bot_logger.debug(f'Verifying TOTP code for user {self.username}...')
        # Verify the TOTP code
        print(totp.verify(code))
        if totp.verify(code):
            bot_logger.debug(f'TOTP code for user {self.username} verified.')
            return True

        return False
