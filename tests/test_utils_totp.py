from __future__ import annotations

import re

import pyotp
import pytest

from pytmbot.exceptions import TOTPError
from pytmbot.utils.totp import TwoFactorAuthenticator


def test_totp_authenticator_rejects_invalid_inputs() -> None:
    with pytest.raises(TOTPError):
        TwoFactorAuthenticator(user_id=0, username="den")
    with pytest.raises(TOTPError):
        TwoFactorAuthenticator(user_id=1, username=" ")


def test_totp_secret_generation_is_deterministic_per_instance() -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    secret_1 = auth._generate_secret()
    secret_2 = auth._generate_secret()
    assert secret_1 == secret_2
    assert len(secret_1) > 10


def test_totp_verification_accepts_valid_code_and_rejects_invalid() -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    totp = pyotp.TOTP(
        auth._generate_secret(),
        digits=auth.TOTP_DIGITS,
        interval=auth.TOTP_INTERVAL,
    )
    valid_code = totp.now()
    assert auth.verify_totp_code(valid_code) is True
    assert auth.verify_totp_code("12a456") is False
    assert auth.verify_totp_code("12345") is False


def test_generate_qr_code_returns_png_bytes() -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    qr_data = auth.generate_totp_qr_code()
    assert isinstance(qr_data, bytes)
    assert qr_data.startswith(b"\x89PNG")
    assert len(qr_data) > 100


def test_backup_codes_have_expected_format() -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    codes = auth.get_backup_codes(count=5)
    assert len(codes) == 5
    for code in codes:
        assert re.fullmatch(r"[A-Z2-7=]{4}-[A-Z2-7=]{4}", code) is not None


def test_backup_codes_reject_invalid_count() -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    with pytest.raises(TOTPError):
        auth.get_backup_codes(0)
