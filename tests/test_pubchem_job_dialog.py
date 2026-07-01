# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.job_store import JOBS_TABLE, STALE_JOB_ERROR_MESSAGE, JobStore
from ui import dialogs, main_page


def test_pubchem_job_status_renderer_is_owned_by_protein_dialog():
    assert callable(dialogs.render_pubchem_job_status)
    assert not hasattr(main_page, "render_pubchem_job_status")


def test_clear_pubchem_job_state_resets_dialog_tracking(monkeypatch):
    session_state = {
        "pubchem_job_id": "job-1",
        "pubchem_job_db_path": "SQL/test.db",
        "pubchem_job_completion_handled": True,
        "selected_proteins": ["P34971"],
    }
    monkeypatch.setattr(dialogs.st, "session_state", session_state)

    dialogs._clear_pubchem_job_state()

    assert session_state == {
        "pubchem_job_id": "",
        "pubchem_job_db_path": "",
        "pubchem_job_completion_handled": False,
        "selected_proteins": [],
    }


def test_database_locked_errors_are_detected_as_transient():
    assert dialogs._is_database_locked_error(sqlite3.OperationalError("database is locked"))
    assert dialogs._is_database_locked_error(sqlite3.OperationalError("database table is locked"))
    assert not dialogs._is_database_locked_error(sqlite3.OperationalError("no such table: main"))


def test_dialog_query_lazily_marks_stale_job_failed(tmp_path):
    db_path = tmp_path / "stale.db"
    connection = sqlite3.connect(db_path)
    store = JobStore(connection)
    store.create_job(job_id="job-1")
    store.start_job("job-1")
    connection.execute(
        f"UPDATE {JOBS_TABLE} SET last_heartbeat_at = ? WHERE job_id = ?",
        ("2000-01-01T00:00:00+00:00", "job-1"),
    )
    connection.commit()
    connection.close()

    failed = dialogs._load_pubchem_job(db_path, "job-1")

    assert failed.status == "failed"
    assert failed.error_message == STALE_JOB_ERROR_MESSAGE
