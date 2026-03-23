from __future__ import annotations

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
