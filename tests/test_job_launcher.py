# SPDX-License-Identifier: LGPL-3.0-or-later
import os
import sqlite3
import sys

import pytest

from services.job_launcher import (
    build_pubchem_worker_command,
    create_and_launch_pubchem_job,
    launch_pubchem_worker,
)
from services.job_store import JobStore


def test_worker_command_uses_current_python_and_passes_no_proteins(tmp_path):
    db_path = tmp_path / "SQL" / "test.db"
    command = build_pubchem_worker_command(
        db_path,
        "job-123",
        repo_root=tmp_path,
    )

    assert command == [
        sys.executable,
        "-m",
        "services.job_worker",
        "run-pubchem-protein-search",
        "--db-path",
        str(db_path.resolve()),
        "--job-id",
        "job-123",
    ]
    assert "proteins" not in " ".join(command).lower()


def test_launcher_sets_repo_cwd_and_pythonpath(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setenv("PYTHONPATH", "existing-path")

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    launch_pubchem_worker(
        "SQL/test.db",
        "job-123",
        repo_root=tmp_path,
        popen=fake_popen,
    )

    assert captured["command"][0] == sys.executable
    assert captured["command"][-2:] == ["--job-id", "job-123"]
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())
    assert captured["kwargs"]["shell"] is False
    pythonpath = captured["kwargs"]["env"]["PYTHONPATH"].split(os.pathsep)
    assert pythonpath == [str(tmp_path.resolve()), "existing-path"]


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
