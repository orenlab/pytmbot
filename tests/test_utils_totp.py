from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pyotp
import pytest

import pytmbot.utils.totp as totp_module
from pytmbot.exceptions import QRCodeError, TOTPError
from pytmbot.utils.totp import TOTPVerificationResult, TwoFactorAuthenticator

# A fixed TOTP step keeps the restart-barrier tests independent of the clock.
_STEP = 59_000_000
_INTERVAL = TwoFactorAuthenticator.TOTP_INTERVAL
_PERSIST_FAIL = ("error", "bot.utils.totp.replay.state.persist.fail")
_PERSIST_RECOVERED = ("info", "bot.utils.totp.replay.state.persist.recovered.ok")


@pytest.fixture(autouse=True)
def _reset_totp_replay_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Isolate the replay state; the process started long ago (no barrier)."""
    monkeypatch.setattr(
        TwoFactorAuthenticator,
        "_REPLAY_STATE_FILE",
        tmp_path / "state" / "totp_replay_state.json",
    )
    monkeypatch.setattr(TwoFactorAuthenticator, "_used_totp_codes", {})
    monkeypatch.setattr(TwoFactorAuthenticator, "_backup_code_hashes", {})
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_state_loaded", False)
    monkeypatch.setattr(TwoFactorAuthenticator, "_PROCESS_STARTED_AT", 0.0)
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_floor_step", None)
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_persist_failed", False)


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, timestamp: float) -> None:
    """Make the authenticator read ``timestamp`` as the current time."""
    monkeypatch.setattr(totp_module, "time", SimpleNamespace(time=lambda: timestamp))


def _restart_process(monkeypatch: pytest.MonkeyPatch, *, started_at: float) -> None:
    """Simulate a restart: in-memory replay state is lost, the state file stays."""
    monkeypatch.setattr(TwoFactorAuthenticator, "_used_totp_codes", {})
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_state_loaded", False)
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_persist_failed", False)
    monkeypatch.setattr(TwoFactorAuthenticator, "_PROCESS_STARTED_AT", started_at)


class _LogRecorder:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self._events = events

    def __getattr__(self, level: str) -> Callable[..., None]:
        def _record(message: str, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self._events.append((level, message))

        return _record


def _capture_log_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []

    @contextmanager
    def _log_context(
        self: TwoFactorAuthenticator, **kwargs: object
    ) -> Iterator[_LogRecorder]:
        del self, kwargs
        yield _LogRecorder(events)

    monkeypatch.setattr(TwoFactorAuthenticator, "log_context", _log_context)
    return events


def _authenticator() -> tuple[TwoFactorAuthenticator, pyotp.TOTP]:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    totp = pyotp.TOTP(
        auth._generate_secret(), digits=auth.TOTP_DIGITS, interval=auth.TOTP_INTERVAL
    )
    return auth, totp


def test_totp_authenticator_rejects_invalid_inputs() -> None:
    with pytest.raises(TOTPError):
        TwoFactorAuthenticator(user_id=0, username="den")
    with pytest.raises(TOTPError):
        TwoFactorAuthenticator(user_id=1, username=cast(str, 123))


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


def test_totp_replay_state_persists_between_instances(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "totp_replay_state.json"
    monkeypatch.setattr(TwoFactorAuthenticator, "_REPLAY_STATE_FILE", state_file)

    auth_one = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    totp = pyotp.TOTP(
        auth_one._generate_secret(),
        digits=auth_one.TOTP_DIGITS,
        interval=auth_one.TOTP_INTERVAL,
    )
    valid_code = totp.now()
    assert auth_one.verify_totp_code(valid_code) is True

    # Simulate process restart: in-memory state cleared, file remains.
    with TwoFactorAuthenticator._used_totp_codes_lock:
        TwoFactorAuthenticator._used_totp_codes.clear()
        TwoFactorAuthenticator._replay_state_loaded = False

    auth_two = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    assert auth_two.verify_totp_code(valid_code) is False


def test_totp_secret_generation_and_uri_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")

    monkeypatch.setattr(
        "pytmbot.utils.totp.hashlib.blake2b",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("hash error")),
    )
    with pytest.raises(TOTPError):
        auth._generate_secret()

    monkeypatch.setattr(
        TwoFactorAuthenticator,
        "_generate_secret",
        lambda self: (_ for _ in ()).throw(RuntimeError("secret error")),
    )
    with pytest.raises(TOTPError):
        auth._generate_totp_auth_uri()


def test_totp_qr_code_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")

    monkeypatch.setattr(
        TwoFactorAuthenticator,
        "_generate_totp_auth_uri",
        lambda self: (_ for _ in ()).throw(TOTPError("totp failed")),
    )
    with pytest.raises(QRCodeError):
        auth.generate_totp_qr_code()

    monkeypatch.setattr(
        TwoFactorAuthenticator,
        "_generate_totp_auth_uri",
        lambda self: "otpauth://totp/test",
    )
    monkeypatch.setattr(
        "pytmbot.utils.totp.qrcode.make",
        lambda _uri: (_ for _ in ()).throw(RuntimeError("qr failed")),
    )
    with pytest.raises(QRCodeError):
        auth.generate_totp_qr_code()


def test_totp_verify_and_backup_codes_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    assert auth.verify_totp_code(cast(str, 123456)) is False

    class _BrokenTOTP:
        def verify(self, _code: str, *_args: str, **_kwargs: str) -> bool:
            raise RuntimeError("verify failed")

    monkeypatch.setattr(
        "pytmbot.utils.totp.pyotp.TOTP",
        lambda *_args, **_kwargs: _BrokenTOTP(),
    )
    with pytest.raises(TOTPError):
        auth.verify_totp_code("123456")


# Secrets derived by the pre-0.5.1 code (username-based derivation). Existing
# authenticator enrollments depend on these staying byte-for-byte identical.
_LEGACY_SECRET_ALICE = (
    "YEXYTNKIMINIVPARVNSSPP7VRFLOMPTMJKTJUWEYSI5L7IMRIA4GBJGIE4GGEL34SKIRPZXXQ33AS"
    "TXH6FVB2EFSRO2TVU6IDKIN6EA="
)
_LEGACY_SECRET_SAMPLE_CONFIG = (
    "7645O3E42ICZOUXOXRJV3BQ5B32TU6S3A7JU6MDBBFETWWWOEITUQH2YKMLHCYEGXZOTWKEDAAK57"
    "WV2QENPVGF62JCZU2GM74B6JQA="
)


def test_totp_secret_for_users_with_username_is_unchanged() -> None:
    assert (
        totp_module._derive_totp_secret(
            user_id=123456789,
            username="Alice_Admin",
            secret_key_material="fixed-salt|1111:FAKE-TOKEN",
            hash_digest_size=64,
        )
        == _LEGACY_SECRET_ALICE
    )
    # Same through the public class with the sample configuration.
    auth = TwoFactorAuthenticator(user_id=123456789, username="test_user")
    assert auth._generate_secret() == _LEGACY_SECRET_SAMPLE_CONFIG
    assert (
        TwoFactorAuthenticator(
            user_id=123456789, username=" test_user "
        )._generate_secret()
        == _LEGACY_SECRET_SAMPLE_CONFIG
    )


def test_totp_supports_users_without_username() -> None:
    no_username = TwoFactorAuthenticator(user_id=123456789, username=None)
    empty_username = TwoFactorAuthenticator(user_id=123456789, username="")
    with_username = TwoFactorAuthenticator(user_id=123456789, username="test_user")

    secret = no_username._generate_secret()
    assert secret == empty_username._generate_secret()
    assert secret != with_username._generate_secret()
    # Different users without usernames get different secrets.
    assert secret != TwoFactorAuthenticator(user_id=987654321)._generate_secret()

    totp = pyotp.TOTP(
        secret, digits=no_username.TOTP_DIGITS, interval=no_username.TOTP_INTERVAL
    )
    assert no_username.verify_totp_code(totp.now()) is True
    assert "pyTMbot%20TOTP:123456789" in no_username._generate_totp_auth_uri()
    assert no_username.generate_totp_qr_code().startswith(b"\x89PNG")


def test_restart_barrier_rejects_codes_when_replay_state_is_not_persisted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The state directory cannot be created: its parent is a file.
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        TwoFactorAuthenticator, "_REPLAY_STATE_FILE", blocker / "replay.json"
    )
    log_events = _capture_log_events(monkeypatch)
    auth, totp = _authenticator()
    code = totp.at(_STEP * _INTERVAL)

    # Persistence fails, but 2FA does not fail closed.
    _freeze_clock(monkeypatch, _STEP * _INTERVAL + 5)
    assert auth.check_totp_code(code) is TOTPVerificationResult.VALID
    assert auth.check_totp_code(code) is TOTPVerificationResult.REPLAYED
    assert log_events.count(_PERSIST_FAIL) == 1

    # Restart in the same step: the in-memory markers are gone.
    _restart_process(monkeypatch, started_at=_STEP * _INTERVAL + 20)
    _freeze_clock(monkeypatch, _STEP * _INTERVAL + 25)
    assert auth.check_totp_code(code) is (TOTPVerificationResult.ISSUED_BEFORE_RESTART)
    assert auth.verify_totp_code(code) is False

    # Codes of the next step were accepted before the restart too (clock skew).
    next_code = totp.at((_STEP + 1) * _INTERVAL)
    _freeze_clock(monkeypatch, (_STEP + 1) * _INTERVAL + 1)
    assert auth.check_totp_code(next_code) is (
        TOTPVerificationResult.ISSUED_BEFORE_RESTART
    )

    # The first code issued after the barrier is accepted.
    _freeze_clock(monkeypatch, (_STEP + 2) * _INTERVAL + 1)
    assert auth.check_totp_code(totp.at((_STEP + 2) * _INTERVAL)) is (
        TOTPVerificationResult.VALID
    )


def test_restart_with_valid_replay_state_has_no_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth, totp = _authenticator()
    code = totp.at(_STEP * _INTERVAL)
    _freeze_clock(monkeypatch, _STEP * _INTERVAL + 5)
    assert auth.check_totp_code(code) is TOTPVerificationResult.VALID
    assert TwoFactorAuthenticator._REPLAY_STATE_FILE.exists()

    _restart_process(monkeypatch, started_at=_STEP * _INTERVAL + 20)
    _freeze_clock(monkeypatch, _STEP * _INTERVAL + 25)
    # The trusted state file catches the replay; no barrier is needed.
    assert auth.check_totp_code(code) is TOTPVerificationResult.REPLAYED
    assert TwoFactorAuthenticator._replay_floor_step is None

    _freeze_clock(monkeypatch, (_STEP + 1) * _INTERVAL + 1)
    assert auth.check_totp_code(totp.at((_STEP + 1) * _INTERVAL)) is (
        TOTPVerificationResult.VALID
    )


@pytest.mark.parametrize(
    "content",
    [b"{not json", b"[]", b'{"replay": []}', bytes([0xFF, 0xFE])],
    ids=["corrupt", "not-an-object", "wrong-structure", "not-utf8"],
)
def test_untrusted_replay_state_file_sets_the_restart_barrier(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    state_file = TwoFactorAuthenticator._REPLAY_STATE_FILE
    state_file.parent.mkdir(parents=True)
    state_file.write_bytes(content)
    monkeypatch.setattr(
        TwoFactorAuthenticator, "_PROCESS_STARTED_AT", float(_STEP * _INTERVAL + 20)
    )
    auth, totp = _authenticator()

    _freeze_clock(monkeypatch, _STEP * _INTERVAL + 25)
    assert auth.check_totp_code(totp.at(_STEP * _INTERVAL)) is (
        TOTPVerificationResult.ISSUED_BEFORE_RESTART
    )


def test_failed_state_write_removes_stale_file_and_reports_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = TwoFactorAuthenticator._REPLAY_STATE_FILE
    log_events = _capture_log_events(monkeypatch)
    auth, totp = _authenticator()

    _freeze_clock(monkeypatch, _STEP * _INTERVAL + 5)
    assert auth.check_totp_code(totp.at(_STEP * _INTERVAL)) is (
        TOTPVerificationResult.VALID
    )
    assert state_file.exists()

    def _fail_mkstemp(**kwargs: object) -> tuple[int, str]:
        del kwargs
        raise OSError("No space left on device")

    monkeypatch.setattr(totp_module, "tempfile", SimpleNamespace(mkstemp=_fail_mkstemp))
    accepted_during_failure = totp.at((_STEP + 1) * _INTERVAL)
    _freeze_clock(monkeypatch, (_STEP + 1) * _INTERVAL + 1)
    assert auth.check_totp_code(accepted_during_failure) is (
        TOTPVerificationResult.VALID
    )
    # The file no longer matches memory; it must not be trusted after a restart.
    assert not state_file.exists()
    _freeze_clock(monkeypatch, (_STEP + 2) * _INTERVAL + 1)
    assert auth.check_totp_code(totp.at((_STEP + 2) * _INTERVAL)) is (
        TOTPVerificationResult.VALID
    )
    assert log_events.count(_PERSIST_FAIL) == 1
    assert _PERSIST_RECOVERED not in log_events

    # Restart before the storage recovers: the barrier rejects the code.
    _restart_process(monkeypatch, started_at=(_STEP + 2) * _INTERVAL + 2)
    _freeze_clock(monkeypatch, (_STEP + 2) * _INTERVAL + 3)
    assert auth.check_totp_code(accepted_during_failure) is (
        TOTPVerificationResult.ISSUED_BEFORE_RESTART
    )

    # Storage is back: the next write succeeds and the recovery is reported.
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_persist_failed", True)
    monkeypatch.setattr(totp_module, "tempfile", tempfile)
    _freeze_clock(monkeypatch, (_STEP + 4) * _INTERVAL + 1)
    assert auth.check_totp_code(totp.at((_STEP + 4) * _INTERVAL)) is (
        TOTPVerificationResult.VALID
    )
    assert state_file.exists()
    assert log_events.count(_PERSIST_RECOVERED) == 1
    assert TwoFactorAuthenticator._replay_persist_failed is False


def test_failed_state_replace_leaves_no_temp_or_stale_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = TwoFactorAuthenticator._REPLAY_STATE_FILE
    auth, totp = _authenticator()
    _freeze_clock(monkeypatch, _STEP * _INTERVAL + 5)
    assert auth.check_totp_code(totp.at(_STEP * _INTERVAL)) is (
        TOTPVerificationResult.VALID
    )
    assert state_file.exists()

    def _fail_replace(src: str, dst: object) -> None:
        del src, dst
        raise OSError("Read-only file system")

    monkeypatch.setattr(
        totp_module,
        "os",
        SimpleNamespace(
            fdopen=os.fdopen, chmod=os.chmod, unlink=os.unlink, replace=_fail_replace
        ),
    )
    _freeze_clock(monkeypatch, (_STEP + 1) * _INTERVAL + 1)
    assert auth.check_totp_code(totp.at((_STEP + 1) * _INTERVAL)) is (
        TOTPVerificationResult.VALID
    )
    assert list(state_file.parent.iterdir()) == []


def test_check_totp_code_reports_invalid_codes() -> None:
    auth, _totp = _authenticator()
    assert auth.check_totp_code("12a456") is TOTPVerificationResult.INVALID
    assert auth.check_totp_code(cast(str, None)) is TOTPVerificationResult.INVALID
