from __future__ import annotations

from datetime import datetime, timedelta
from time import time_ns

import pytest

import pytmbot.middleware.session_manager as session_manager_module


def _create_manager(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cleanup_interval: int = 600,
    session_timeout: int = 10,
    max_totp_attempts: int = 5,
    block_duration: int = 10,
) -> session_manager_module.SessionManager:
    monkeypatch.setattr(
        session_manager_module.SessionManager,
        "_start_cleanup_thread",
        lambda self: None,
    )
    manager = session_manager_module.SessionManager(instance_name=f"test-{time_ns()}")
    manager.cleanup_interval = cleanup_interval
    manager.session_timeout = session_timeout
    manager.max_totp_attempts = max_totp_attempts
    manager.block_duration = block_duration
    manager._shutdown_event.clear()
    manager._user_sessions.clear()
    return manager


def test_auth_state_and_totp_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _create_manager(
        monkeypatch,
        max_totp_attempts=2,
        block_duration=1,
    )

    user_id = 101
    manager.set_auth_state(user_id, manager.state_fabric.PROCESSING)
    assert manager.get_auth_state(user_id) == manager.state_fabric.PROCESSING

    with pytest.raises(ValueError):
        manager.set_auth_state(user_id, "invalid-state")

    assert manager.increment_totp_attempts(user_id) == 1
    assert manager.increment_totp_attempts(user_id) == 2
    assert manager.get_auth_state(user_id) == manager.state_fabric.BLOCKED
    assert manager.is_blocked(user_id) is True
    assert manager.get_blocked_time(user_id) is not None

    manager.reset_totp_attempts(user_id)
    assert manager.get_totp_attempts(user_id) == 0


def test_session_sweep_keeps_pending_2fa_and_active_lockouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _create_manager(monkeypatch, max_totp_attempts=5, block_duration=10)
    pending_user, blocked_user = 101, 202
    manager.set_auth_state(pending_user, manager.state_fabric.PROCESSING)
    manager.set_referer_data(pending_user, "callback_query", "__manage__:abc:101")
    for _ in range(5):
        manager.increment_totp_attempts(blocked_user)

    # Health checks call get_session_stats every 60-120 s.
    stats = manager.get_session_stats()
    manager.clear_expired_sessions()

    assert stats["evicted_sessions"] == 0
    assert stats["processing_sessions"] == 1
    assert stats["blocked_sessions"] == 1
    assert manager.get_auth_state(pending_user) == manager.state_fabric.PROCESSING
    assert manager.get_referer_uri(pending_user) == "__manage__:abc:101"
    assert manager.is_blocked(blocked_user) is True
    assert manager.get_totp_attempts(blocked_user) == 5


def test_pending_sessions_expire_after_their_own_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _create_manager(monkeypatch)
    manager.pending_timeout = 10
    user_id = 303
    manager.set_auth_state(user_id, manager.state_fabric.PROCESSING)

    manager._user_sessions[user_id].updated_at = datetime.now() - timedelta(minutes=9)
    manager.clear_expired_sessions()
    assert user_id in manager._user_sessions

    manager._user_sessions[user_id].updated_at = datetime.now() - timedelta(minutes=11)
    manager.clear_expired_sessions()
    assert user_id not in manager._user_sessions


def test_blocked_sessions_live_until_the_block_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _create_manager(monkeypatch)
    user_id = 404
    manager.set_blocked_time(user_id, duration_minutes=10)
    session = manager._user_sessions[user_id]
    session.updated_at = datetime.now() - timedelta(hours=1)

    assert manager.get_session_stats()["evicted_sessions"] == 0
    assert manager.is_blocked(user_id) is True

    session.blocked_time = datetime.now() - timedelta(seconds=1)
    assert manager.get_session_stats()["evicted_sessions"] == 1
    assert user_id not in manager._user_sessions


def test_authenticated_sessions_expire_by_login_time_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _create_manager(monkeypatch, session_timeout=10)
    user_id = 505
    manager.set_auth_state(user_id, manager.state_fabric.AUTHENTICATED)
    manager.set_login_time(user_id)
    session = manager._user_sessions[user_id]
    session.updated_at = datetime.now() - timedelta(hours=1)

    assert manager.is_authenticated(user_id) is True
    manager.clear_expired_sessions()
    assert user_id in manager._user_sessions

    session.login_time = datetime.now() - timedelta(minutes=11)
    assert manager.is_authenticated(user_id) is False
    manager.clear_expired_sessions()
    assert user_id not in manager._user_sessions


def test_finished_lockout_starts_a_fresh_attempt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _create_manager(monkeypatch, max_totp_attempts=5)
    user_id = 606
    for _ in range(5):
        manager.increment_totp_attempts(user_id)
    manager._user_sessions[user_id].blocked_time = datetime.now() - timedelta(seconds=1)

    assert manager.is_blocked(user_id) is False
    assert manager.get_totp_attempts(user_id) == 0
    assert manager.get_auth_state(user_id) == manager.state_fabric.UNAUTHENTICATED
