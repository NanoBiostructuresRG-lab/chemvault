# SPDX-License-Identifier: LGPL-3.0-or-later
import os
import sqlite3
import sys

import pytest

from services import job_launcher
from services.job_launcher import (
    build_pubchem_worker_command,
    create_and_launch_pubchem_job,
    launch_pubchem_worker,
    resolve_database_path,
)
from services.job_store import JobStore


def test_relative_database_path_resolves_against_caller_working_directory(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    assert resolve_database_path("SQL/test.db") == (
        tmp_path / "SQL" / "test.db"
    ).resolve()


def test_absolute_database_path_remains_associated_with_same_file(tmp_path):
    db_path = (tmp_path / "SQL" / "test.db").resolve()

    assert resolve_database_path(db_path) == db_path


def test_database_resolution_is_independent_of_launcher_module_location(
    tmp_path,
    monkeypatch,
):
    caller_directory = tmp_path / "caller"
    caller_directory.mkdir()
    installed_directory = tmp_path / "site-packages"
    monkeypatch.setattr(
        job_launcher,
        "__file__",
        str(installed_directory / "services" / "job_launcher.py"),
    )
    monkeypatch.chdir(caller_directory)

    resolved = resolve_database_path("SQL/test.db")

    assert resolved == (caller_directory / "SQL" / "test.db").resolve()
    assert not (installed_directory / "SQL").exists()


def test_worker_command_uses_current_python_and_absolute_caller_database(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    command = build_pubchem_worker_command("SQL/test.db", "job-123")

    assert command == [
        sys.executable,
        "-m",
        "services.job_worker",
        "run-pubchem-protein-search",
        "--db-path",
        str((tmp_path / "SQL" / "test.db").resolve()),
        "--job-id",
        "job-123",
    ]
    assert "proteins" not in " ".join(command).lower()


def test_launcher_inherits_caller_cwd_and_environment(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", "existing-path")
    monkeypatch.setenv("CHEMVAULT_TEST_SETTING", "preserved")
    monkeypatch.setattr(
        job_launcher.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )
    expected_environment = dict(os.environ)

    def fake_popen(command, **kwargs):
        assert os.getcwd() == str(tmp_path)
        assert dict(os.environ) == expected_environment
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    launch_pubchem_worker(
        "SQL/test.db",
        "job-123",
        popen=fake_popen,
    )

    assert captured["command"][0] == sys.executable
    assert captured["command"][-4:-2] == [
        "--db-path",
        str((tmp_path / "SQL" / "test.db").resolve()),
    ]
    assert captured["command"][-2:] == ["--job-id", "job-123"]
    assert captured["kwargs"] == {
        "shell": False,
        "creationflags": 0x08000000,
    }
    assert os.environ["PYTHONPATH"] == "existing-path"
    assert os.environ["CHEMVAULT_TEST_SETTING"] == "preserved"


def test_create_and_launch_job_persists_proteins_before_launch(tmp_path):
    db_path = tmp_path / "test.db"
    connection = sqlite3.connect(db_path)
    observed = {}

    class FakeProcess:
        pid = 12345

    def fake_launcher(received_db_path, job_id):
        observed["db_path"] = received_db_path
        with sqlite3.connect(received_db_path) as worker_connection:
            observed["job"] = JobStore(worker_connection).get_job(job_id)
        return FakeProcess()

    created = create_and_launch_pubchem_job(
        connection,
        db_path,
        ["P32245"],
        database_id="test",
        launcher=fake_launcher,
    )

    assert observed["db_path"] == db_path
    assert observed["job"].job_id == created.job_id
    assert observed["job"].metadata == {"proteins": ["P32245"]}
    assert created.worker_pid == 12345
    assert JobStore(connection).get_job(created.job_id).worker_pid == 12345
    connection.close()


def test_create_and_launch_job_marks_launch_failure(tmp_path):
    connection = sqlite3.connect(tmp_path / "test.db")

    def failing_launcher(db_path, job_id):
        raise OSError("process launch failed")

    with pytest.raises(OSError, match="process launch failed"):
        create_and_launch_pubchem_job(
            connection,
            tmp_path / "test.db",
            ["P32245"],
            launcher=failing_launcher,
        )

    failed = JobStore(connection).list_jobs(limit=1)[0]
    assert failed.status == "failed"
    assert failed.error_message == "process launch failed"
    connection.close()
