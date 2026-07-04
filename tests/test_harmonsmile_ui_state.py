# SPDX-License-Identifier: LGPL-3.0-or-later
from application.job_contracts import JobStatusContract
from clients.backend_gateway import BackendGatewayError
from services.job_models import JobStatus
from ui import sidebar
from ui.harmonsmile_state import execute_harmonsmile_command


def _job(status=JobStatus.COMPLETED, error=None, progress=1.0):
    return JobStatusContract(
        job_id="job-1",
        job_type="harmonsmile",
        status=status,
        database_id="test_db",
        stage=status.value,
        progress=progress,
        message=None,
        created_at="2026-07-03T10:00:00+00:00",
        started_at="2026-07-03T10:00:00+00:00",
        finished_at="2026-07-03T10:01:00+00:00",
        error=error,
        cancellable=False,
        updated_at="2026-07-03T10:01:00+00:00",
        result={"processed_cids": 3, "merged_rows": 2},
    )


def test_harmonsmile_success_clears_running_state_and_refreshes():
    state = {}
    refresh_calls = []

    class Gateway:
        mode = "local"

        def launch_harmonsmile_job(self, *args):
            return _job()

    result = execute_harmonsmile_command(
        state,
        Gateway(),
        "test_db",
        "main",
        "CID",
        lambda current: refresh_calls.append(current),
    )

    assert result.status == JobStatus.COMPLETED
    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_kind"] == "success"
    assert "Updated table 'main'" in state["harmonsmile_feedback_message"]
    assert "processed 3 CIDs" in state["harmonsmile_feedback_message"]
    assert refresh_calls == [state]


def test_harmonsmile_backend_failure_clears_running_and_surfaces_error():
    state = {}

    class Gateway:
        mode = "local"

        def launch_harmonsmile_job(self, *args):
            return _job(JobStatus.FAILED, "PubChem unavailable")

    execute_harmonsmile_command(
        state, Gateway(), "test_db", "main", "CID", lambda *_: None
    )

    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_kind"] == "error"
    assert state["harmonsmile_feedback_message"] == "PubChem unavailable"


def test_api_connection_failure_has_no_fallback_and_clears_running_state():
    state = {}
    calls = []

    class Gateway:
        mode = "http"

        def launch_harmonsmile_job(self, *args):
            calls.append(args)
            raise BackendGatewayError("connection refused")

    execute_harmonsmile_command(
        state, Gateway(), "test_db", "main", "CID", lambda *_: None
    )

    assert calls == [("test_db", "main", "CID")]
    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_kind"] == "error"
    assert state["harmonsmile_feedback_message"] == (
        "CHEMVAULT backend API is not available: connection refused"
    )


def test_api_polling_connection_loss_clears_running_without_fallback():
    state = {}
    calls = []

    class Gateway:
        mode = "http"

        def launch_harmonsmile_job(self, *args):
            calls.append(("launch", args))
            return _job(JobStatus.PENDING, progress=0.0)

        def get_job_status(self, *args):
            calls.append(("status", args))
            raise BackendGatewayError("connection lost during polling")

    execute_harmonsmile_command(
        state,
        Gateway(),
        "test_db",
        "main",
        "CID",
        lambda *_: None,
        sleep_callback=lambda *_: None,
    )

    assert [call[0] for call in calls] == ["launch", "status"]
    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_kind"] == "error"
    assert "connection lost during polling" in state[
        "harmonsmile_feedback_message"
    ]


def test_api_mode_polls_until_terminal_status_and_reports_progress():
    state = {}
    statuses = iter([
        _job(JobStatus.RUNNING, progress=0.4),
        _job(JobStatus.COMPLETED, progress=1.0),
    ])
    observed = []

    class Gateway:
        mode = "http"

        def launch_harmonsmile_job(self, *args):
            return _job(JobStatus.PENDING, progress=0.0)

        def get_job_status(self, *args):
            return next(statuses)

    result = execute_harmonsmile_command(
        state,
        Gateway(),
        "test_db",
        "main",
        "CID",
        lambda *_: None,
        status_callback=lambda status: observed.append(status.status),
        sleep_callback=lambda *_: None,
    )

    assert result.status == JobStatus.COMPLETED
    assert observed == [
        JobStatus.PENDING,
        JobStatus.RUNNING,
        JobStatus.COMPLETED,
    ]
    assert state["harmonsmile_running"] is False


def test_workflow_switch_clears_stale_harmonsmile_display(monkeypatch):
    state = {
        "selecting_harmonsmile": True,
        "selecting_chamanp": False,
        "harmonsmile_running": True,
        "harmonsmile_job_id": "stale-job",
        "harmonsmile_feedback_kind": "error",
        "harmonsmile_feedback_message": "stale message",
    }
    monkeypatch.setattr(sidebar.st, "session_state", state)

    sidebar._set_curados_false()
    state["selecting_chamanp"] = True

    assert state["selecting_harmonsmile"] is False
    assert state["selecting_chamanp"] is True
    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_message"] == ""
