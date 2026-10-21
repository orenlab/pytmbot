#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
from datetime import UTC, datetime
from enum import StrEnum, auto
from pathlib import Path
from typing import ClassVar, Final

import pyotp
import qrcode
from qrcode.image.pure import PyPNGImage

from pytmbot.exceptions import ErrorContext, QRCodeError, TOTPError
from pytmbot.globals import settings
from pytmbot.logs import BaseComponent
from pytmbot.utils.state_paths import ensure_private_directory, get_state_root_path


class TOTPVerificationResult(StrEnum):
    """Outcome of checking a TOTP code."""

    VALID = auto()
    INVALID = auto()
    # The code was already used; counts as a failed attempt.
    REPLAYED = auto()
    # The code may have been used before a restart that lost the replay state.
    # The user only has to wait for the next code; not a failed attempt.
    ISSUED_BEFORE_RESTART = auto()


def _build_secret_key_material() -> str:
    salt = settings.access_control.auth_salt[0].get_secret_value()
    prod_token_values = settings.bot_token.prod_token or []
    dev_token_values = settings.bot_token.dev_bot_token or []
    prod_token = prod_token_values[0].get_secret_value() if prod_token_values else ""
    dev_token = dev_token_values[0].get_secret_value() if dev_token_values else ""
    return "|".join(segment for segment in (salt, prod_token, dev_token) if segment)


def _totp_secret_message(*, user_id: int, username: str) -> str:
    """
    Return the per-user message the TOTP secret is derived from.

    Users with a Telegram username keep the original ``"<id>:<username>"``
    derivation byte for byte, so existing authenticator enrollments stay
    valid. Users without a username get ``"<id>:"``, which no username-based
    message can produce (usernames are never empty).
    """
    if username:
        return f"{user_id}:{username.lower()}"
    return f"{user_id}:"


def _derive_totp_secret(
    *,
    user_id: int,
    username: str,
    secret_key_material: str,
    hash_digest_size: int,
) -> str:
    message = _totp_secret_message(user_id=user_id, username=username).encode()
    key_material = hashlib.blake2b(
        secret_key_material.encode(),
        digest_size=32,
    ).digest()
    hash_obj = hashlib.blake2b(
        message,
        key=key_material,
        digest_size=hash_digest_size,
    )
    return base64.b32encode(hash_obj.digest()).decode("ascii")


def _build_totp_auth_uri(
    *,
    secret: str,
    username: str,
    issuer_name: str,
    digits: int,
    interval: int,
) -> str:
    totp = pyotp.TOTP(secret, digits=digits, interval=interval)
    return totp.provisioning_uri(name=username, issuer_name=issuer_name)


def _generate_qr_code_bytes(auth_uri: str) -> bytes:
    qr_code = qrcode.make(auth_uri, image_factory=PyPNGImage)
    with io.BytesIO() as img_bytes:
        qr_code.save(img_bytes)
        return img_bytes.getvalue()


def _resolve_matching_step(
    *, totp: pyotp.TOTP, code: str, current_step: int, interval: int
) -> int | None:
    for step in range(current_step - 1, current_step + 2):
        step_time = datetime.fromtimestamp(step * interval, tz=UTC)
        if totp.verify(code, for_time=step_time, valid_window=0):
            return step
    return None


def _read_replay_state_locked(
    auth_cls: type[TwoFactorAuthenticator], *, min_step: int
) -> bool:
    """Load persisted replay markers; return True when the state file is trusted."""
    state_file = auth_cls._REPLAY_STATE_FILE
    try:
        payload_raw = state_file.read_text(encoding="utf-8")
        payload = json.loads(payload_raw)
    except (OSError, ValueError):
        return False

    if not isinstance(payload, dict):
        return False
    replay_state = payload.get("replay")
    if not isinstance(replay_state, dict):
        return False

    loaded_entries: dict[int, set[tuple[str, int]]] = {}
    for raw_user_id, markers in replay_state.items():
        if not (
            isinstance(raw_user_id, str)
            and raw_user_id.isdigit()
            and isinstance(markers, list)
        ):
            continue

        user_id = int(raw_user_id)
        user_markers: set[tuple[str, int]] = set()
        for marker in markers:
            if (
                isinstance(marker, list)
                and len(marker) == 2
                and isinstance(marker[0], str)
                and isinstance(marker[1], int)
                and marker[1] >= min_step
            ):
                user_markers.add((marker[0], marker[1]))

        if user_markers:
            loaded_entries[user_id] = user_markers

    if loaded_entries:
        auth_cls._used_totp_codes.update(loaded_entries)
    return True


def _load_replay_state_locked(auth: TwoFactorAuthenticator, *, min_step: int) -> None:
    """
    Load the replay state once per process and set the restart barrier.

    Without a trusted state file (missing, e.g. wiped tmpfs, unreadable or
    corrupt) a code accepted shortly before a restart could be accepted again.
    Every step that was still valid when this process started is rejected
    instead; the user waits for the next code, at most about a minute.
    """
    auth_cls = type(auth)
    if auth_cls._replay_state_loaded:
        return
    auth_cls._replay_state_loaded = True

    if _read_replay_state_locked(auth_cls, min_step=min_step):
        auth_cls._replay_floor_step = None
        return

    # +1 covers the clock-skew window: before the restart, codes of the step
    # after the current one were accepted too.
    floor_step = int(auth_cls._PROCESS_STARTED_AT // auth_cls.TOTP_INTERVAL) + 1
    auth_cls._replay_floor_step = floor_step
    with auth.log_context(action="load_replay_state", floor_step=floor_step) as log:
        log.info("bot.utils.totp.replay.state.barrier.info")


def _write_replay_state(state_file: Path, payload: dict[str, object]) -> None:
    """Atomically replace the replay state file; raise OSError on failure."""
    parent_dir = ensure_private_directory(state_file.parent)
    file_descriptor, temp_path = tempfile.mkstemp(
        prefix=".totp_replay_",
        suffix=".json",
        dir=str(parent_dir),
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
            json.dump(payload, temp_file, separators=(",", ":"), sort_keys=True)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, state_file)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise


def _handle_replay_persist_failure(
    auth: TwoFactorAuthenticator, error: OSError
) -> None:
    """
    Remove the outdated state file and report the first failure in a row.

    An outdated file would be trusted after a restart and miss the codes used
    since; without it the restart barrier rejects them instead.
    """
    auth_cls = type(auth)
    try:
        auth_cls._REPLAY_STATE_FILE.unlink(missing_ok=True)
        stale_state_removed = True
    except OSError:
        stale_state_removed = False

    if auth_cls._replay_persist_failed:
        return
    auth_cls._replay_persist_failed = True
    with auth.log_context(
        action="persist_replay_state",
        error=str(error),
        stale_state_removed=stale_state_removed,
    ) as log:
        log.error("bot.utils.totp.replay.state.persist.fail")


def _persist_replay_state_locked(
    auth: TwoFactorAuthenticator, *, min_step: int
) -> None:
    auth_cls = type(auth)
    pruned_entries: dict[int, set[tuple[str, int]]] = {}
    for user_id, markers in auth_cls._used_totp_codes.items():
        active_markers = {
            marker
            for marker in markers
            if isinstance(marker[0], str)
            and isinstance(marker[1], int)
            and marker[1] >= min_step
        }
        if active_markers:
            pruned_entries[user_id] = active_markers

    auth_cls._used_totp_codes = pruned_entries

    payload: dict[str, object] = {
        "replay": {
            str(user_id): [[code, step] for code, step in sorted(markers)]
            for user_id, markers in pruned_entries.items()
        }
    }

    try:
        _write_replay_state(auth_cls._REPLAY_STATE_FILE, payload)
    except OSError as error:
        _handle_replay_persist_failure(auth, error)
        return

    if auth_cls._replay_persist_failed:
        auth_cls._replay_persist_failed = False
        with auth.log_context(action="persist_replay_state") as log:
            log.info("bot.utils.totp.replay.state.persist.recovered.ok")


def _register_code_usage(
    auth: TwoFactorAuthenticator,
    *,
    code: str,
    matched_step: int,
    current_step: int,
) -> TOTPVerificationResult:
    min_step = current_step - auth._REPLAY_WINDOW_STEPS
    code_marker = (code, matched_step)

    with auth._used_totp_codes_lock:
        _load_replay_state_locked(auth, min_step=min_step)
        floor_step = auth._replay_floor_step
        if floor_step is not None and matched_step <= floor_step:
            return TOTPVerificationResult.ISSUED_BEFORE_RESTART

        user_entries = {
            marker
            for marker in auth._used_totp_codes.get(auth.user_id, set())
            if marker[1] >= min_step
        }
        if code_marker in user_entries:
            auth._used_totp_codes[auth.user_id] = user_entries
            _persist_replay_state_locked(auth, min_step=min_step)
            return TOTPVerificationResult.REPLAYED

        user_entries.add(code_marker)
        if len(user_entries) > auth._MAX_TRACKED_CODES_PER_USER:
            sorted_entries = sorted(user_entries, key=lambda marker: marker[1])
            user_entries = set(sorted_entries[-auth._MAX_TRACKED_CODES_PER_USER :])
        auth._used_totp_codes[auth.user_id] = user_entries
        _persist_replay_state_locked(auth, min_step=min_step)
        return TOTPVerificationResult.VALID


class TwoFactorAuthenticator(BaseComponent):
    """Two-factor authentication handler using TOTP (Time-based One-Time Password)."""

    # Constants
    TOTP_CODE_LENGTH: Final[int] = 6
    TOTP_DIGITS: Final[int] = 6
    TOTP_INTERVAL: Final[int] = 30
    HASH_DIGEST_SIZE: Final[int] = 64
    ISSUER_NAME: Final[str] = "pyTMbot TOTP"
    QR_CODE_FORMAT: Final[str] = "PNG"

    # Regex pattern for validating TOTP codes (6 digits)
    TOTP_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{6}$")
    _REPLAY_WINDOW_STEPS: ClassVar[int] = 4
    _MAX_TRACKED_CODES_PER_USER: ClassVar[int] = 64
    _REPLAY_STATE_FILE: ClassVar[Path] = (
        get_state_root_path() / "totp_replay_state.json"
    )
    _used_totp_codes: ClassVar[dict[int, set[tuple[str, int]]]] = {}
    _backup_code_hashes: ClassVar[dict[int, set[str]]] = {}
    _used_totp_codes_lock: ClassVar[threading.RLock] = threading.RLock()
    _replay_state_loaded: ClassVar[bool] = False
    # Restart barrier: without a trusted replay state file, steps up to
    # _replay_floor_step (derived from the process start) are rejected.
    _PROCESS_STARTED_AT: ClassVar[float] = time.time()
    _replay_floor_step: ClassVar[int | None] = None
    # True from a failed state write until the next successful one.
    _replay_persist_failed: ClassVar[bool] = False

    __slots__ = (
        "user_id",
        "username",
        "account_name",
        "_salt",
        "_secret_cache",
        "_secret_key_material",
    )

    def __init__(self, user_id: int, username: str | None = None) -> None:
        """Initialize the TwoFactorAuthenticator with user ID and username.

        Args:
            user_id: The unique identifier for the user
            username: The Telegram username; empty or ``None`` when the user
                has none, in which case the secret is derived from the user
                id and the bot's key material only

        Raises:
            TOTPError: If user_id or username is invalid
        """
        super().__init__("TwoFactorAuth")

        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise TOTPError(f"Invalid user_id: {user_id}. Must be a positive integer.")

        if username is not None and not isinstance(username, str):
            raise TOTPError("Invalid username: must be a string or None.")

        self.user_id: int = user_id
        self.username: str = (username or "").strip()
        self.account_name: str = self.username or str(user_id)
        self._salt: str = settings.access_control.auth_salt[0].get_secret_value()
        self._secret_key_material = _build_secret_key_material()
        if not self._secret_key_material:
            raise TOTPError("Missing TOTP key material")
        self._secret_cache: str | None = None  # Cache for secret to avoid regeneration

    def _generate_secret(self) -> str:
        """Generate a secret key for TOTP authentication.

        The secret key is generated by hashing the concatenation of the user ID,
        salt, and username using blake2b for enhanced security.

        Returns:
            str: The base32 encoded secret key

        Raises:
            TOTPError: If secret generation fails
        """
        if self._secret_cache is not None:
            return self._secret_cache

        try:
            self._secret_cache = _derive_totp_secret(
                user_id=self.user_id,
                username=self.username,
                secret_key_material=self._secret_key_material,
                hash_digest_size=self.HASH_DIGEST_SIZE,
            )

            with self.log_context(user_id=self.user_id, username=self.username) as log:
                log.debug("bot.utils.totp.secret.generated.debug")

            return self._secret_cache

        except Exception as e:
            with self.log_context(user_id=self.user_id, username=self.username) as log:
                log.error("bot.utils.totp.secret.generation.fail")
            raise TOTPError(
                f"Failed to generate secret for user {self.account_name}: {e}"
            ) from e

    def _generate_totp_auth_uri(self) -> str:
        """Generate a TOTP authentication URI using the secret key and account information.

        Returns:
            str: The generated TOTP authentication URI

        Raises:
            TOTPError: If URI generation fails
        """
        try:
            uri = _build_totp_auth_uri(
                secret=self._generate_secret(),
                username=self.account_name,
                issuer_name=self.ISSUER_NAME,
                digits=self.TOTP_DIGITS,
                interval=self.TOTP_INTERVAL,
            )

            with self.log_context(user_id=self.user_id, username=self.username) as log:
                log.debug("bot.utils.totp.uri.generated.debug")

            return uri

        except Exception as e:
            with self.log_context(user_id=self.user_id, username=self.username) as log:
                log.error("bot.utils.totp.uri.generation.fail")
            raise TOTPError(
                f"Failed to generate TOTP URI for user {self.account_name}: {e}"
            ) from e

    def generate_totp_qr_code(self) -> bytes:
        """Generate a QR code for two-factor authentication.

        Returns:
            bytes: The generated QR code as bytes

        Raises:
            QRCodeError: If QR code generation fails
        """
        with self.log_context(
            user_id=self.user_id, username=self.username, operation="qr_generation"
        ) as log:
            log.debug("bot.utils.totp.qr.code.start")

            try:
                auth_uri = self._generate_totp_auth_uri()
                qr_data = _generate_qr_code_bytes(auth_uri)

                log.info("bot.utils.totp.qr.code.info", qr_size=len(qr_data))
                return qr_data

            except TOTPError as error:
                log.error("bot.utils.totp.qr.code.fail")
                raise QRCodeError(
                    ErrorContext(
                        message="QR code generation failed due to TOTP error.",
                        error_code="QR_CODE_TOTP_ERROR",
                        metadata={"username": self.username, "user_id": self.user_id},
                    )
                ) from error
            except Exception as e:
                log.error("bot.utils.totp.qr.code.fail")
                raise QRCodeError(
                    ErrorContext(
                        message="QR code generation failed.",
                        error_code="QR_CODE_GENERATION_ERROR",
                        metadata={
                            "username": self.username,
                            "user_id": self.user_id,
                            "original_error": str(e),
                        },
                    )
                ) from e

    def verify_totp_code(self, code: str) -> bool:
        """Verify the TOTP code for the user.

        Args:
            code: The TOTP code to be verified

        Returns:
            bool: True if the TOTP code is verified, False otherwise

        Raises:
            TOTPError: If verification process fails critically
        """
        return self.check_totp_code(code) is TOTPVerificationResult.VALID

    def check_totp_code(self, code: str) -> TOTPVerificationResult:
        """Check the TOTP code for the user and tell why it was rejected.

        Args:
            code: The TOTP code to be checked

        Returns:
            TOTPVerificationResult: ``VALID`` when the code is accepted (it is
            then registered as used); otherwise the reason for the rejection

        Raises:
            TOTPError: If verification process fails critically
        """
        with self.log_context(
            user_id=self.user_id, username=self.username, operation="totp_verification"
        ) as log:
            # Input validation
            if not isinstance(code, str):
                log.debug("bot.utils.totp.invalid.code.debug")
                return TOTPVerificationResult.INVALID

            # Clean and validate code format
            cleaned_code = code.strip()
            if not self.TOTP_CODE_PATTERN.match(cleaned_code):
                log.debug("bot.utils.totp.invalid.code.debug")
                return TOTPVerificationResult.INVALID

            try:
                totp = pyotp.TOTP(
                    self._generate_secret(),
                    digits=self.TOTP_DIGITS,
                    interval=self.TOTP_INTERVAL,
                )

                log.debug("bot.utils.totp.verification.start")

                current_step = int(time.time()) // self.TOTP_INTERVAL
                matched_step = _resolve_matching_step(
                    totp=totp,
                    code=cleaned_code,
                    current_step=current_step,
                    interval=self.TOTP_INTERVAL,
                )

                if matched_step is None:
                    log.warning(
                        "bot.utils.totp.verification.fail",
                        code_length=len(cleaned_code),
                    )
                    return TOTPVerificationResult.INVALID

                result = _register_code_usage(
                    self,
                    code=cleaned_code,
                    matched_step=matched_step,
                    current_step=current_step,
                )
                if result is TOTPVerificationResult.REPLAYED:
                    log.warning("bot.utils.totp.verification.replay.fail")
                elif result is TOTPVerificationResult.ISSUED_BEFORE_RESTART:
                    log.warning("bot.utils.totp.verification.before.restart.warn")
                else:
                    log.info("bot.utils.totp.verification.ok")
                return result

            except Exception as e:
                log.error("bot.utils.totp.critical.verification.fail")
                raise TOTPError(
                    f"TOTP verification failed for user {self.account_name}: {e}"
                ) from e
