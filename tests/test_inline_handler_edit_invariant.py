from __future__ import annotations

from pathlib import Path


def test_inline_handlers_delegate_message_editing_to_shared_helper() -> None:
    handlers_root = Path(__file__).resolve().parents[1] / "pytmbot" / "handlers"
    inline_modules = sorted(handlers_root.rglob("inline/*.py"))
    allowed_direct_edit_calls = {
        handlers_root / "server_handlers" / "inline" / "common.py",
    }

    offenders: list[str] = []
    for module_path in inline_modules:
        if module_path in allowed_direct_edit_calls:
            continue

        module_source = module_path.read_text(encoding="utf-8")
        if "bot.edit_message_text(" in module_source:
            offenders.append(str(module_path))

    assert offenders == [], (
        "Inline handlers must route edit_message_text through shared helper. "
        f"Found direct calls in: {offenders}"
    )
