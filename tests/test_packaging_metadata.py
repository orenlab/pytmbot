from __future__ import annotations

import tomllib
from pathlib import Path


def test_project_console_script_points_to_main() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"] == {"pytmbot": "pytmbot.main:main"}
