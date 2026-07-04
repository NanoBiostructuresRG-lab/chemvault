# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3
from threading import Event, Thread

import pandas as pd

from application.harmonsmile_jobs import (
    create_harmonsmile_job,
    execute_harmonsmile_job,
    get_harmonsmile_job_status,
    launch_harmonsmile_job,
)
from services.job_models import JobStatus


def test_harmonsmile_job_runs_merges_and_remains_queryable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SQL").mkdir()
    connection = sqlite3.connect(tmp_path / "SQL" / "test_db.db")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany('INSERT INTO "main" VALUES (?)', [("1",), ("2",)])
    connection.commit()
    connection.close()

    def runner(frame):
        return pd.DataFrame({
            "PubChem CID": frame["CID"],
            "SMILES": [f"SMILES-{cid}" for cid in frame["CID"]],
        })

    launched = launch_harmonsmile_job(
        "test_db", "main", "CID", runner=runner
    )
    queried = get_harmonsmile_job_status("test_db", launched.job_id)

    assert launched.status == JobStatus.COMPLETED
    assert queried == launched
    assert launched.stage == "completed"
    assert launched.progress == 1.0
    assert launched.result["processed_cids"] == 2
    assert launched.result["merged_rows"] == 2
    assert launched.result["output_columns"] == ["SMILES"]

    connection = sqlite3.connect(tmp_path / "SQL" / "test_db.db")
    assert connection.execute(
        'SELECT CID, SMILES FROM "main" ORDER BY CID'
    ).fetchall() == [("1", "SMILES-1"), ("2", "SMILES-2")]
    operation = connection.execute(
        "SELECT operation_type, status FROM _chemvault_operation_log"
    ).fetchone()
    assert operation == ("harmonsmile_run", "success")


def test_harmonsmile_job_records_runner_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SQL").mkdir()
    connection = sqlite3.connect(tmp_path / "SQL" / "test_db.db")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.execute('INSERT INTO "main" VALUES ("1")')
    connection.commit()
    connection.close()

    def failing_runner(_frame):
        raise RuntimeError("HARMONSMILE unavailable")

    status = launch_harmonsmile_job(
        "test_db", "main", "CID", runner=failing_runner
    )

    assert status.status == JobStatus.FAILED
    assert status.error == "HARMONSMILE unavailable"
    assert status.result["failed_cids"] == 1


def test_created_job_is_queryable_while_background_execution_runs(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SQL").mkdir()
    connection = sqlite3.connect(tmp_path / "SQL" / "test_db.db")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.execute('INSERT INTO "main" VALUES ("1")')
    connection.commit()
    connection.close()
    runner_started = Event()
    release_runner = Event()

    def blocking_runner(frame):
        runner_started.set()
        release_runner.wait(timeout=2)
        return pd.DataFrame({"PubChem CID": frame["CID"], "SMILES": ["CCO"]})

    created = create_harmonsmile_job("test_db", "main", "CID")
    assert created.status == JobStatus.PENDING
    assert created.stage == "queued"

    thread = Thread(
        target=execute_harmonsmile_job,
        args=("test_db", created.job_id),
        kwargs={"runner": blocking_runner},
    )
    thread.start()
    assert runner_started.wait(timeout=1)

    running = get_harmonsmile_job_status("test_db", created.job_id)
    assert running.status == JobStatus.RUNNING
    assert running.stage in {"started", "running"}

    release_runner.set()
    thread.join(timeout=2)
    completed = get_harmonsmile_job_status("test_db", created.job_id)
    assert completed.status == JobStatus.COMPLETED
    assert completed.result["merged_rows"] == 1
