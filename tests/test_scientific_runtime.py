# SPDX-License-Identifier: LGPL-3.0-or-later
import os
from pathlib import Path

import pytest

from application import scientific_runtime
from application.job_contracts import (
    JobStatusContract,
    RecoveredJobContract,
)
from services.job_models import JobStatus
from services.job_models import JobType


def _recovered(database_id, job_id):
    return RecoveredJobContract(
        job=JobStatusContract(
            job_id=job_id,
            job_type=JobType.HARMONSMILE.value,
            status=JobStatus.PENDING,
            database_id=database_id,
            stage="recovery_queued",
            progress=0.4,
            message="Interrupted HARMONSMILE job queued for recovery",
            created_at="2026-07-03T10:00:00+00:00",
            started_at=None,
            finished_at=None,
            error=None,
            cancellable=True,
        ),
        table_name="main",
    )


def test_runtime_activates_each_database_independently_only_once(monkeypatch):
    scientific_runtime._reset_scientific_runtime_for_tests()
    recovery_calls = []
    launch_calls = []
    monkeypatch.setattr(
        scientific_runtime,
        "recover_orphaned_harmonsmile_jobs",
        lambda database_id, **kwargs: recovery_calls.append(
            (database_id, kwargs)
        ) or [_recovered(database_id, f"job-{database_id}")],
    )
    monkeypatch.setattr(
        scientific_runtime,
        "resolve_database_path",
        lambda database_id, **_: Path(f"C:/{database_id}.db"),
    )
    monkeypatch.setattr(
        scientific_runtime,
        "start_scientific_job_executor",
        lambda *args, **kwargs: launch_calls.append((args, kwargs)),
    )

    first = scientific_runtime.activate_scientific_runtime("a", db_dir="SQL")
    repeated = scientific_runtime.activate_scientific_runtime("a", db_dir="SQL")
    second = scientific_runtime.activate_scientific_runtime("b", db_dir="SQL")

    assert repeated is first
    assert first[0].job.job_id == "job-a"
    assert second[0].job.job_id == "job-b"
    assert [call[0] for call in recovery_calls] == ["a", "b"]
    assert launch_calls == [
        (
            ("a", JobType.HARMONSMILE, "job-a"),
            {"name": "chemvault-harmonsmile-recovery"},
        ),
        (
            ("b", JobType.HARMONSMILE, "job-b"),
            {"name": "chemvault-harmonsmile-recovery"},
        ),
    ]
    scientific_runtime._reset_scientific_runtime_for_tests()


def test_runtime_recognizes_its_own_process_as_live():
    assert scientific_runtime.process_is_alive(os.getpid()) is True


def test_runtime_recognizes_missing_process_as_orphaned():
    assert scientific_runtime.process_is_alive(2147483647) is False


def test_runtime_startup_retries_after_recovered_executor_launch_fails(
    monkeypatch,
):
    scientific_runtime._reset_scientific_runtime_for_tests()
    recovery_calls = []
    launch_calls = []
    monkeypatch.setattr(
        scientific_runtime,
        "recover_orphaned_harmonsmile_jobs",
        lambda database_id, **kwargs: recovery_calls.append(
            (database_id, kwargs)
        ) or [_recovered(database_id, "job-1")],
    )
    monkeypatch.setattr(
        scientific_runtime,
        "resolve_database_path",
        lambda database_id, **_: Path(f"C:/{database_id}.db"),
    )

    def launch(*args, **kwargs):
        launch_calls.append((args, kwargs))
        if len(launch_calls) == 1:
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(
        scientific_runtime,
        "start_scientific_job_executor",
        launch,
    )

    with pytest.raises(RuntimeError, match="thread start failed"):
        scientific_runtime.activate_scientific_runtime("db", db_dir="SQL")

    recovered = scientific_runtime.activate_scientific_runtime(
        "db", db_dir="SQL"
    )
    assert recovered[0].job.job_id == "job-1"
    assert scientific_runtime.activate_scientific_runtime(
        "db", db_dir="SQL"
    ) is recovered
    assert len(recovery_calls) == 2
    assert len(launch_calls) == 2
    scientific_runtime._reset_scientific_runtime_for_tests()


def test_streamlit_startup_does_not_import_or_call_scientific_recovery():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )

    assert "scientific_runtime" not in source
    assert "recover_orphaned" not in source
