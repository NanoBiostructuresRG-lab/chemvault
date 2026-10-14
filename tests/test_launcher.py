# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ui import launcher


def _unexpected_streamlit_start(*args: object, **kwargs: object) -> None:
    raise AssertionError("Streamlit must not start for this CLI operation")


@pytest.fixture(autouse=True)
def _installed_distribution_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.importlib.metadata, "version", lambda name: "0.14.7")


@pytest.mark.parametrize("option", ["--help", "-h"])
def test_help_exits_successfully_without_side_effects(
    option: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.subprocess, "run", _unexpected_streamlit_start)

    with pytest.raises(SystemExit) as exc_info:
        launcher.main([option])

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    assert "usage: chemvault [-h] [--version]" in output.out
    assert "Launch the installed CHEMVAULT Streamlit application." in output.out
    assert output.err == ""
    assert not (tmp_path / "SQL").exists()


def test_version_uses_distribution_metadata_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requested_distributions: list[str] = []

    def distribution_version(name: str) -> str:
        requested_distributions.append(name)
        return "0.14.7"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.importlib.metadata, "version", distribution_version)
    monkeypatch.setattr(launcher.subprocess, "run", _unexpected_streamlit_start)

    with pytest.raises(SystemExit) as exc_info:
        launcher.main(["--version"])

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    assert output.out == "ChemVault 0.14.7\n"
    assert output.err == ""
    assert requested_distributions == ["ChemVault"]
    assert not (tmp_path / "SQL").exists()


def test_invalid_argument_is_rejected_without_starting_streamlit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher.subprocess, "run", _unexpected_streamlit_start)

    with pytest.raises(SystemExit) as exc_info:
        launcher.main(["--unknown"])

    assert exc_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "unrecognized arguments: --unknown" in output.err
    assert not (tmp_path / "SQL").exists()


def test_no_arguments_launches_installed_app_and_propagates_exit_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", "caller-python-path")
    initial_cwd = Path.cwd()
    initial_environment = dict(os.environ)
    captured: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        assert Path.cwd() == initial_cwd
        assert dict(os.environ) == initial_environment
        return subprocess.CompletedProcess(command, 23)

    monkeypatch.setattr(launcher.subprocess, "run", run)

    result = launcher.main([])

    expected_app = Path(launcher.__file__).resolve().parent.parent / "app.py"
    assert expected_app.is_file()
    assert captured == {
        "command": [sys.executable, "-m", "streamlit", "run", str(expected_app)],
        "kwargs": {"check": False},
    }
    assert result == 23
    assert Path.cwd() == initial_cwd
    assert dict(os.environ) == initial_environment
    assert not (tmp_path / "SQL").exists()


def test_missing_installed_app_returns_failure_without_starting_streamlit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_app = tmp_path / "site-packages" / "app.py"
    monkeypatch.setattr(launcher, "_resolve_app_path", lambda: missing_app)
    monkeypatch.setattr(launcher.subprocess, "run", _unexpected_streamlit_start)

    assert launcher.main([]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"chemvault: application file not found: {missing_app}\n"
