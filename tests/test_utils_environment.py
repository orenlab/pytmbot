from __future__ import annotations

import io
import os

import pytest

from pytmbot.utils.environment import get_environment_state, is_running_in_docker


def test_is_running_in_docker_true_when_dockerenv_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    is_running_in_docker.cache_clear()
    monkeypatch.setattr("os.path.exists", lambda _: True)
    assert is_running_in_docker() is True


def test_is_running_in_docker_true_from_cgroup(monkeypatch: pytest.MonkeyPatch) -> None:
    is_running_in_docker.cache_clear()
    monkeypatch.setattr("os.path.exists", lambda _: False)
    monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: io.StringIO("0::/docker/x"))
    assert is_running_in_docker() is True


def test_is_running_in_docker_true_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    is_running_in_docker.cache_clear()
    monkeypatch.setattr("os.path.exists", lambda _: False)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: io.StringIO("0::/"))
    monkeypatch.setenv("DOCKER_CONTAINER", "1")
    assert is_running_in_docker() is True


def test_get_environment_state_contains_required_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_environment_state.cache_clear()
    monkeypatch.setattr("pytmbot.utils.environment.is_running_in_docker", lambda: False)
    state = get_environment_state()
    assert state["Running on"] == "Bare Metal"
    assert "Python path" in state
    assert isinstance(state["Command args"], list)
    assert isinstance(state["Module path"], list)
    assert isinstance(state["Python version"], str)
    assert os.path.basename(str(state["Python path"])) in {
        "python",
        "python3",
        "python3.13",
    }
