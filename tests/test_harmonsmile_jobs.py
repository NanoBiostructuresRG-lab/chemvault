# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3
from pathlib import Path
from threading import Event, Thread

import pandas as pd
import pytest

from application.harmonsmile_jobs import (
    create_harmonsmile_job,
    execute_harmonsmile_job,
    get_harmonsmile_job_status,
    launch_harmonsmile_job,
    recover_orphaned_harmonsmile_jobs,
)
from services.harmonsmile_cache import (
    merge_harmonsmile_cache_to_table,
    upsert_harmonsmile_cache,
)
from services.job_models import JobStatus
from services.job_store import JobStore


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


def test_duplicate_submission_returns_existing_active_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SQL").mkdir()
    connection = sqlite3.connect(tmp_path / "SQL" / "test_db.db")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.execute('INSERT INTO "main" VALUES ("1")')
    connection.commit()
    connection.close()

    first = create_harmonsmile_job("test_db", "main", "CID")
    duplicate = create_harmonsmile_job("test_db", "main", "CID")

    assert duplicate == first
    connection = sqlite3.connect(tmp_path / "SQL" / "test_db.db")
    assert connection.execute(
        "SELECT COUNT(*) FROM _chemvault_jobs WHERE job_type = 'harmonsmile'"
    ).fetchone()[0] == 1


def test_interrupted_job_recovers_same_id_and_reuses_committed_chunks(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    sql_dir = tmp_path / "SQL"
    sql_dir.mkdir()
    db_path = sql_dir / "test_db.db"
    connection = sqlite3.connect(db_path)
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany(
        'INSERT INTO "main" VALUES (?)',
        [(str(cid),) for cid in range(1, 6)],
    )
    connection.commit()
    connection.close()

    created = create_harmonsmile_job("test_db", "main", "CID")
    connection = sqlite3.connect(db_path)
    store = JobStore(connection)
    store.claim_pending_scientific_job(created.job_id, 424242)
    store.start_job(created.job_id)
    store.update_progress(
        created.job_id,
        "running",
        0.4,
        "HARMONSMILE chunk 2/3",
    )
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame(
            {
                "PubChem_CID": ["1", "2"],
                "SMILES": ["cached-1", "cached-2"],
            }
        ),
    )
    connection.close()

    recovered = recover_orphaned_harmonsmile_jobs(
        "test_db",
        db_dir=sql_dir,
        executor_is_alive=lambda *_: False,
        process_is_alive=lambda *_: False,
        current_pid=123,
    )
    requested = []

    def runner(frame):
        requested.extend(frame["CID"].tolist())
        return pd.DataFrame(
            {
                "PubChem_CID": frame["CID"],
                "SMILES": [f"new-{cid}" for cid in frame["CID"]],
            }
        )

    completed = execute_harmonsmile_job(
        "test_db",
        created.job_id,
        runner=runner,
    )

    assert [snapshot.job.job_id for snapshot in recovered] == [created.job_id]
    assert recovered[0].table_name == "main"
    assert recovered[0].job.status == JobStatus.PENDING
    assert completed.job_id == created.job_id
    assert completed.status == JobStatus.COMPLETED
    assert requested == ["3", "4", "5"]
    connection = sqlite3.connect(db_path)
    assert connection.execute(
        'SELECT CID, SMILES FROM "main" ORDER BY CAST(CID AS INTEGER)'
    ).fetchall() == [
        ("1", "cached-1"),
        ("2", "cached-2"),
        ("3", "new-3"),
        ("4", "new-4"),
        ("5", "new-5"),
    ]


@pytest.mark.parametrize(
    ("executor_alive", "worker_process_alive"),
    [(True, False), (False, True)],
)
def test_recovery_does_not_reclaim_live_executor(
    tmp_path,
    monkeypatch,
    executor_alive,
    worker_process_alive,
):
    monkeypatch.chdir(tmp_path)
    sql_dir = tmp_path / "SQL"
    sql_dir.mkdir()
    connection = sqlite3.connect(sql_dir / "test_db.db")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.execute('INSERT INTO "main" VALUES ("1")')
    connection.commit()
    connection.close()
    created = create_harmonsmile_job("test_db", "main", "CID")
    connection = sqlite3.connect(sql_dir / "test_db.db")
    store = JobStore(connection)
    store.claim_pending_scientific_job(created.job_id, 424242)
    store.start_job(created.job_id)
    connection.close()

    recovered = recover_orphaned_harmonsmile_jobs(
        "test_db",
        db_dir=sql_dir,
        executor_is_alive=lambda *_: executor_alive,
        process_is_alive=lambda *_: worker_process_alive,
        current_pid=123,
    )

    assert recovered == []
    assert get_harmonsmile_job_status(
        "test_db", created.job_id
    ).status == JobStatus.RUNNING


def test_recovery_repeats_already_committed_final_merge_safely(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    sql_dir = tmp_path / "SQL"
    sql_dir.mkdir()
    db_path = sql_dir / "test_db.db"
    connection = sqlite3.connect(db_path)
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany('INSERT INTO "main" VALUES (?)', [("1",), ("2",)])
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame(
            {"PubChem_CID": ["1", "2"], "SMILES": ["CCO", "CCC"]}
        ),
    )
    assert merge_harmonsmile_cache_to_table(
        connection, "main", "CID", cids=["1", "2"]
    ) == 2
    connection.close()
    created = create_harmonsmile_job("test_db", "main", "CID")
    connection = sqlite3.connect(db_path)
    store = JobStore(connection)
    store.claim_pending_scientific_job(created.job_id, 424242)
    store.start_job(created.job_id)
    connection.close()

    recover_orphaned_harmonsmile_jobs(
        "test_db",
        db_dir=sql_dir,
        executor_is_alive=lambda *_: False,
        process_is_alive=lambda *_: False,
        current_pid=123,
    )

    completed = execute_harmonsmile_job(
        "test_db",
        created.job_id,
        runner=lambda _frame: pytest.fail("fully cached CIDs must not rerun"),
    )

    assert completed.job_id == created.job_id
    assert completed.status == JobStatus.COMPLETED
    connection = sqlite3.connect(db_path)
    assert connection.execute(
        'SELECT CID, SMILES FROM "main" ORDER BY CID'
    ).fetchall() == [("1", "CCO"), ("2", "CCC")]


def test_recovery_opens_only_the_explicitly_activated_database(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    sql_dir = tmp_path / "SQL"
    sql_dir.mkdir()
    for database_id in ("database_a", "database_b"):
        connection = sqlite3.connect(sql_dir / f"{database_id}.db")
        connection.execute('CREATE TABLE "main" (CID TEXT)')
        connection.execute('INSERT INTO "main" VALUES ("1")')
        connection.commit()
        connection.close()
        created = create_harmonsmile_job(database_id, "main", "CID")
        connection = sqlite3.connect(sql_dir / f"{database_id}.db")
        store = JobStore(connection)
        store.claim_pending_scientific_job(created.job_id, 424242)
        store.start_job(created.job_id)
        connection.close()

    real_connect = sqlite3.connect
    opened_paths = []

    def tracking_connect(path, *args, **kwargs):
        opened_paths.append(Path(path).resolve())
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(
        "application.harmonsmile_jobs.sqlite3.connect",
        tracking_connect,
    )
    recovered = recover_orphaned_harmonsmile_jobs(
        "database_a",
        db_dir=sql_dir,
        executor_is_alive=lambda *_: False,
        process_is_alive=lambda *_: False,
        current_pid=123,
    )

    assert opened_paths == [(sql_dir / "database_a.db").resolve()]
    assert len(recovered) == 1
    assert recovered[0].job.database_id == "database_a"
    connection = real_connect(sql_dir / "database_b.db")
    assert JobStore(connection).get_job(
        connection.execute(
            "SELECT job_id FROM _chemvault_jobs"
        ).fetchone()[0]
    ).status == JobStatus.RUNNING.value
    connection.close()
