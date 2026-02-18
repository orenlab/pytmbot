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


def test_is_authenticated_expiry_and_auto_unblock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _create_manager(
        monkeypatch,
        session_timeout=1,
        block_duration=1,
    )
    user_id = 202

    manager.set_auth_state(user_id, manager.state_fabric.AUTHENTICATED)
    manager.set_login_time(user_id)
    assert manager.is_authenticated(user_id) is True

    with manager.session_context(user_id) as session:
        session.auth_state = manager.state_fabric.BLOCKED
        session.blocked_time = datetime.now() - timedelta(seconds=1)

    assert manager.is_authenticated(user_id) is False
    assert manager.get_auth_state(user_id) == manager.state_fabric.UNAUTHENTICATED

    manager.set_auth_state(user_id, manager.state_fabric.AUTHENTICATED)
    with manager.session_context(user_id) as session:
        session.login_time = datetime.now() - timedelta(minutes=5)

    assert manager.is_session_expired(user_id) is True
    assert manager.is_authenticated(user_id) is False


def test_referer_cleanup_stats_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _create_manager(monkeypatch, session_timeout=1)

    active_user = 303
    expired_user = 404

    manager.set_auth_state(active_user, manager.state_fabric.AUTHENTICATED)
    manager.set_login_time(active_user)
    manager.set_referer_data(active_user, "message", "/docker")

    assert manager.get_referer_uri(active_user) == "/docker"
    assert manager.get_handler_type(active_user) == "message"

    manager.set_auth_state(expired_user, manager.state_fabric.PROCESSING)
    with manager.session_context(expired_user) as session:
        session.login_time = datetime.now() - timedelta(minutes=10)

    stats = manager.get_session_stats()
    assert stats["total_sessions"] == 1
    assert stats["authenticated_sessions"] == 1
    assert stats["processing_sessions"] == 0
    assert stats["evicted_sessions"] == 1

    manager.reset_referer_data(active_user)
    assert manager.get_referer_uri(active_user) is None
    assert manager.get_handler_type(active_user) is None

    manager.reset_session(active_user)
    assert manager.get_active_sessions_count() == 0


def test_shutdown_clears_state(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _create_manager(monkeypatch)

    manager.set_auth_state(505, manager.state_fabric.AUTHENTICATED)
    manager.set_login_time(505)
    assert manager.get_active_sessions_count() == 1

    manager.shutdown()
    assert manager.get_active_sessions_count() == 0
    assert manager._shutdown_event.is_set() is True
