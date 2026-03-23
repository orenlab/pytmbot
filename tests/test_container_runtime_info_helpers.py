from __future__ import annotations

from pytmbot.handlers.docker_handlers.inline.container_runtime_info import _safe_bool


def test_safe_bool_handles_none_and_booleanish_values() -> None:
    assert _safe_bool(None) == "N/A"
    assert _safe_bool(True) == "yes"
    assert _safe_bool(False) == "no"
    assert _safe_bool("non-empty") == "yes"
