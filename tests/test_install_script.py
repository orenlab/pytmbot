from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "tools" / "install.sh"


def _run_bash(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _source_cmd() -> str:
    return f"source {shlex.quote(str(INSTALL_SCRIPT))}"


def test_install_script_is_source_safe() -> None:
    result = _run_bash(f"{_source_cmd()}; echo sourced_ok")
    assert result.returncode == 0
    assert result.stdout.strip() == "sourced_ok"


def test_parse_cli_args_sets_runtime_flags() -> None:
    command = (
        f"{_source_cmd()}; "
        "parse_cli_args "
        "--non-interactive --yes --test-mode "
        "--confirm-integrity YES --action docker --docker-method source; "
        'printf "%s|%s|%s|%s|%s|%s" '
        '"$RUNTIME_NON_INTERACTIVE" '
        '"$RUNTIME_ASSUME_YES" '
        '"$RUNTIME_TEST_MODE" '
        '"$RUNTIME_CONFIRM_INTEGRITY" '
        '"$RUNTIME_INSTALL_ACTION" '
        '"$RUNTIME_DOCKER_INSTALL_METHOD"'
    )
    result = _run_bash(command)
    assert result.returncode == 0
    assert result.stdout.strip() == "1|1|1|YES|docker|source"


def test_parse_cli_args_unknown_option_fails() -> None:
    result = _run_bash(f"{_source_cmd()}; parse_cli_args --does-not-exist")
    assert result.returncode == 2
    assert "Unknown option" in result.stdout


def test_confirm_prompt_non_interactive_honors_default() -> None:
    deny = _run_bash(
        f"{_source_cmd()}; RUNTIME_NON_INTERACTIVE=1; "
        'confirm_prompt "Continue? [y/N]: " "N"',
    )
    assert deny.returncode == 1

    allow = _run_bash(
        f"{_source_cmd()}; RUNTIME_NON_INTERACTIVE=1; "
        'confirm_prompt "Continue? [Y/n]: " "Y"',
    )
    assert allow.returncode == 0


def test_read_prompt_value_required_fails_non_interactive_when_missing() -> None:
    result = _run_bash(
        f"{_source_cmd()}; RUNTIME_NON_INTERACTIVE=1; "
        'read_prompt_value out "Prompt" "PYTMBOT_UNSET_VALUE" "" 1 0',
    )
    assert result.returncode == 1
    assert "Missing required value: PYTMBOT_UNSET_VALUE" in result.stdout


def test_run_selected_action_rejects_menu_in_non_interactive_mode() -> None:
    result = _run_bash(
        f"{_source_cmd()}; RUNTIME_NON_INTERACTIVE=1; "
        "RUNTIME_INSTALL_ACTION=menu; run_selected_action",
    )
    assert result.returncode == 2
    assert "Non-interactive mode requires --action" in result.stdout


def test_run_selected_action_dispatches_without_running_real_installers() -> None:
    result = _run_bash(
        f"{_source_cmd()}; "
        'install_bot_in_docker(){ echo "docker_called"; }; '
        "RUNTIME_INSTALL_ACTION=docker; run_selected_action",
    )
    assert result.returncode == 0
    assert "docker_called" in result.stdout


def test_run_docker_compose_safe_returns_success_in_test_mode() -> None:
    result = _run_bash(
        f"{_source_cmd()}; RUNTIME_TEST_MODE=1; run_docker_compose_safe up -d",
    )
    assert result.returncode == 0


def test_install_script_help_works_without_root_or_integrity_confirmation() -> None:
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--non-interactive" in result.stdout
