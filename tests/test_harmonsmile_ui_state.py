# SPDX-License-Identifier: LGPL-3.0-or-later
import inspect

from application.job_contracts import JobStatusContract
from clients.backend_gateway import BackendGatewayError
from services.job_models import JobStatus
from ui import sidebar
from ui.harmonsmile_state import (
    execute_harmonsmile_command,
    sync_harmonsmile_runtime,
)


def _job(status=JobStatus.COMPLETED, error=None, progress=1.0, message=None):
    return JobStatusContract(
        job_id="job-1",
        job_type="harmonsmile",
        status=status,
        database_id="test_db",
        stage=status.value,
        progress=progress,
        message=message,
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

        def find_active_harmonsmile_job(self, *args):
            return None

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
    assert state["harmonsmile_feedback_message"] == (
        "Molecular structure processing job completed. Updated table 'main'; "
        "processed 3 CIDs and merged 2 rows."
    )
    assert refresh_calls == [state]


def test_harmonsmile_backend_failure_clears_running_and_surfaces_error():
    state = {}

    class Gateway:
        mode = "local"

        def find_active_harmonsmile_job(self, *args):
            return None

        def launch_harmonsmile_job(self, *args):
            return _job(
                JobStatus.FAILED,
                "PubChem unavailable",
                message="Backend status message",
            )

    execute_harmonsmile_command(
        state, Gateway(), "test_db", "main", "CID", lambda *_: None
    )

    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_kind"] == "error"
    assert state["harmonsmile_feedback_message"] == "PubChem unavailable"


def test_cancelled_job_uses_molecular_structure_processing_fallback():
    state = {"harmonsmile_running": True, "harmonsmile_job_id": "job-1"}

    class Gateway:
        def get_job_status(self, *args):
            return _job(JobStatus.CANCELLED)

    sync_harmonsmile_runtime(
        state,
        Gateway(),
        "test_db",
        "main",
        lambda *_: None,
    )

    assert state["harmonsmile_feedback_kind"] == "warning"
    assert state["harmonsmile_feedback_message"] == (
        "Molecular structure processing job was cancelled."
    )


def test_cancelled_job_preserves_backend_status_message():
    state = {"harmonsmile_running": True, "harmonsmile_job_id": "job-1"}

    class Gateway:
        def get_job_status(self, *args):
            return _job(
                JobStatus.CANCELLED,
                message="Cancelled by the backend operator.",
            )

    sync_harmonsmile_runtime(
        state,
        Gateway(),
        "test_db",
        "main",
        lambda *_: None,
    )

    assert state["harmonsmile_feedback_message"] == (
        "Cancelled by the backend operator."
    )


def test_failed_job_uses_molecular_structure_processing_fallback():
    state = {"harmonsmile_running": True, "harmonsmile_job_id": "job-1"}

    class Gateway:
        def get_job_status(self, *args):
            return _job(JobStatus.FAILED)

    sync_harmonsmile_runtime(
        state,
        Gateway(),
        "test_db",
        "main",
        lambda *_: None,
    )

    assert state["harmonsmile_feedback_kind"] == "error"
    assert state["harmonsmile_feedback_message"] == (
        "Molecular structure processing job failed."
    )


def test_failed_job_preserves_backend_status_message_when_error_is_absent():
    state = {"harmonsmile_running": True, "harmonsmile_job_id": "job-1"}

    class Gateway:
        def get_job_status(self, *args):
            return _job(
                JobStatus.FAILED,
                message="Backend-reported processing failure.",
            )

    sync_harmonsmile_runtime(
        state,
        Gateway(),
        "test_db",
        "main",
        lambda *_: None,
    )

    assert state["harmonsmile_feedback_message"] == (
        "Backend-reported processing failure."
    )


def test_api_connection_failure_has_no_fallback_and_clears_running_state():
    state = {}
    calls = []

    class Gateway:
        mode = "http"

        def find_active_harmonsmile_job(self, *args):
            return None

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


def test_local_launch_failure_uses_molecular_structure_processing_wording():
    state = {}

    class Gateway:
        mode = "local"

        def find_active_harmonsmile_job(self, *args):
            return None

        def launch_harmonsmile_job(self, *args):
            raise RuntimeError("local worker unavailable")

    execute_harmonsmile_command(
        state,
        Gateway(),
        "test_db",
        "main",
        "CID",
        lambda *_: None,
    )

    assert state["harmonsmile_feedback_kind"] == "error"
    assert state["harmonsmile_feedback_message"] == (
        "Molecular structure processing job could not be completed: "
        "local worker unavailable"
    )


def test_sync_monitoring_failure_uses_molecular_structure_processing_wording():
    state = {"harmonsmile_running": True, "harmonsmile_job_id": "job-1"}

    class Gateway:
        def get_job_status(self, *args):
            raise RuntimeError("status timeout")

    status = sync_harmonsmile_runtime(
        state,
        Gateway(),
        "test_db",
        "main",
        lambda *_: None,
    )

    assert status is None
    assert state["harmonsmile_running"] is True
    assert state["harmonsmile_job_id"] == "job-1"
    assert state["harmonsmile_feedback_kind"] == "warning"
    assert state["harmonsmile_feedback_message"] == (
        "Monitoring molecular structure processing is temporarily unavailable: "
        "status timeout"
    )


def test_command_monitoring_failure_preserves_possible_backend_execution():
    state = {"harmonsmile_running": True, "harmonsmile_job_id": "job-1"}

    class Gateway:
        def get_job_status(self, *args):
            raise RuntimeError("status timeout")

    status = execute_harmonsmile_command(
        state,
        Gateway(),
        "test_db",
        "main",
        "CID",
        lambda *_: None,
    )

    assert status is None
    assert state["harmonsmile_running"] is True
    assert state["harmonsmile_feedback_kind"] == "warning"
    assert state["harmonsmile_feedback_message"] == (
        "Monitoring molecular structure processing is temporarily unavailable; "
        "the backend job may still be running: status timeout"
    )


def test_run_command_returns_after_submission_without_polling():
    state = {}
    calls = []

    class Gateway:
        mode = "local"

        def find_active_harmonsmile_job(self, *args):
            calls.append(("find", args))
            return None

        def launch_harmonsmile_job(self, *args):
            calls.append(("launch", args))
            return _job(JobStatus.PENDING, progress=0.0)

        def get_job_status(self, *args):
            calls.append(("status", args))
            raise AssertionError("submission must not poll")

    result = execute_harmonsmile_command(
        state,
        Gateway(),
        "test_db",
        "main",
        "CID",
        lambda *_: None,
    )

    assert result.status == JobStatus.PENDING
    assert [call[0] for call in calls] == ["find", "launch"]
    assert state["harmonsmile_running"] is True
    assert state["harmonsmile_job_id"] == "job-1"
    assert state["harmonsmile_feedback_kind"] == ""


def test_run_command_reattaches_to_session_job_and_returns_immediately():
    state = {
        "harmonsmile_running": True,
        "harmonsmile_job_id": "job-1",
    }
    calls = []

    class Gateway:
        def get_job_status(self, *args):
            calls.append(args)
            return _job(JobStatus.RUNNING, progress=0.4)

        def find_active_harmonsmile_job(self, *args):
            raise AssertionError("known jobs must be read by ID")

        def launch_harmonsmile_job(self, *args):
            raise AssertionError("reattachment must not resubmit")

    result = execute_harmonsmile_command(
        state,
        Gateway(),
        "test_db",
        "main",
        "CID",
        lambda *_: None,
    )

    assert result.status == JobStatus.RUNNING
    assert calls == [("test_db", "job-1")]
    assert state["harmonsmile_running"] is True
    assert state["harmonsmile_job_id"] == "job-1"


def test_periodic_refresh_reads_status_once_and_never_resubmits(monkeypatch):
    state = {
        "harmonsmile_running": True,
        "harmonsmile_job_id": "job-1",
    }
    calls = []
    progress = []
    captions = []
    monkeypatch.setattr(sidebar.st, "session_state", state)
    monkeypatch.setattr(sidebar.st, "progress", progress.append)
    monkeypatch.setattr(sidebar.st, "caption", captions.append)

    class Gateway:
        def get_job_status(self, *args):
            calls.append(("status", args))
            return _job(JobStatus.RUNNING, progress=0.4)

        def launch_harmonsmile_job(self, *args):
            calls.append(("launch", args))
            raise AssertionError("periodic refresh must not submit")

    result = sidebar.refresh_harmonsmile_status_once(
        "test_db",
        "main",
        gateway=Gateway(),
    )

    assert result.status == JobStatus.RUNNING
    assert calls == [("status", ("test_db", "job-1"))]
    assert progress == [0.4]
    assert captions == [
        "Molecular structure processing is running in the backend."
    ]


def test_running_status_preserves_backend_message(monkeypatch):
    state = {
        "harmonsmile_running": True,
        "harmonsmile_job_id": "job-1",
    }
    captions = []
    monkeypatch.setattr(sidebar.st, "session_state", state)
    monkeypatch.setattr(sidebar.st, "progress", lambda *_: None)
    monkeypatch.setattr(sidebar.st, "caption", captions.append)

    class Gateway:
        def get_job_status(self, *args):
            return _job(
                JobStatus.RUNNING,
                progress=0.4,
                message="Backend processing phase 2.",
            )

    sidebar.refresh_harmonsmile_status_once(
        "test_db",
        "main",
        gateway=Gateway(),
    )

    assert captions == ["Backend processing phase 2."]


def test_periodic_unavailable_status_uses_molecular_structure_wording(monkeypatch):
    state = {
        "harmonsmile_running": True,
        "harmonsmile_job_id": "job-1",
    }
    captions = []
    monkeypatch.setattr(sidebar.st, "session_state", state)
    monkeypatch.setattr(sidebar.st, "caption", captions.append)

    class Gateway:
        def get_job_status(self, *args):
            raise RuntimeError("status timeout")

    status = sidebar.refresh_harmonsmile_status_once(
        "test_db",
        "main",
        gateway=Gateway(),
    )

    assert status is None
    assert captions == [
        "Status for molecular structure processing is temporarily unavailable; "
        "retrying."
    ]


def test_curate_launch_spinner_uses_molecular_structure_processing_wording():
    source = inspect.getsource(sidebar.render_curate_card)

    assert "Starting molecular structure processing through the backend..." in source
    assert "Starting SMILES calculations through the backend..." not in source


def test_periodic_terminal_status_stops_monitoring(monkeypatch):
    state = {
        "harmonsmile_running": True,
        "harmonsmile_job_id": "job-1",
    }
    refresh_calls = []
    rerun_calls = []
    gateway_calls = []
    monkeypatch.setattr(sidebar.st, "session_state", state)
    monkeypatch.setattr(
        sidebar,
        "refresh_database_state",
        lambda current: refresh_calls.append(current),
    )

    class Gateway:
        def get_job_status(self, *args):
            gateway_calls.append(args)
            return _job(JobStatus.COMPLETED)

    status = sidebar.refresh_harmonsmile_status_once(
        "test_db",
        "main",
        gateway=Gateway(),
    )

    assert status.status == JobStatus.COMPLETED
    assert gateway_calls == [("test_db", "job-1")]
    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_kind"] == "success"
    assert refresh_calls == [state]

    monkeypatch.setattr(
        sidebar,
        "refresh_harmonsmile_status_once",
        lambda *_: status,
    )
    monkeypatch.setattr(sidebar.st, "rerun", lambda: rerun_calls.append(True))
    sidebar.render_harmonsmile_job_status.__wrapped__("test_db", "main")
    assert rerun_calls == [True]


def test_session_state_loss_reattaches_to_equivalent_active_job():
    state = {"harmonsmile_running": False, "harmonsmile_job_id": ""}
    active = _job(JobStatus.RUNNING, progress=0.4)

    class Gateway:
        def find_active_harmonsmile_job(self, *args):
            assert args == ("test_db", "main")
            return active

    status = sync_harmonsmile_runtime(
        state,
        Gateway(),
        "test_db",
        "main",
        lambda *_: None,
    )

    assert status is active
    assert state["harmonsmile_running"] is True
    assert state["harmonsmile_job_id"] == "job-1"


def test_refresh_consumes_terminal_status_for_attached_job():
    state = {"harmonsmile_running": True, "harmonsmile_job_id": "job-1"}
    refreshed = []

    class Gateway:
        def get_job_status(self, *args):
            assert args == ("test_db", "job-1")
            return _job(JobStatus.COMPLETED)

    status = sync_harmonsmile_runtime(
        state,
        Gateway(),
        "test_db",
        "main",
        lambda current: refreshed.append(current),
    )

    assert status.status == JobStatus.COMPLETED
    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_kind"] == "success"
    assert refreshed == [state]


def test_curate_selection_reset_clears_stale_harmonsmile_display(monkeypatch):
    state = {
        "selecting_harmonsmile": True,
        "harmonsmile_running": True,
        "harmonsmile_job_id": "stale-job",
        "harmonsmile_feedback_kind": "error",
        "harmonsmile_feedback_message": "stale message",
    }
    monkeypatch.setattr(sidebar.st, "session_state", state)

    sidebar._set_curados_false()

    assert state["selecting_harmonsmile"] is False
    assert state["harmonsmile_running"] is False
    assert state["harmonsmile_job_id"] == ""
    assert state["harmonsmile_feedback_message"] == ""
