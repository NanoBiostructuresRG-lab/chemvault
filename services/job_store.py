# SPDX-License-Identifier: LGPL-3.0-or-later
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from services.job_models import JobRecord, JobStatus, JobType
from services.runtime_config import JOB_HEARTBEAT_TIMEOUT_SECONDS

JOBS_TABLE = "_chemvault_jobs"
ACTIVE_JOB_STATUSES = (JobStatus.PENDING.value, JobStatus.RUNNING.value)
STALE_JOB_ERROR_MESSAGE = "Backend job stopped unexpectedly. Please try again."


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _enum_value(value):
    return value.value if hasattr(value, "value") else str(value)


def _metadata_json(metadata):
    return json.dumps(metadata or {}, sort_keys=True)


def _metadata_dict(value):
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _job_from_row(row):
    if row is None:
        return None
    return JobRecord(
        job_id=row["job_id"],
        job_type=row["job_type"],
        status=row["status"],
        database_id=row["database_id"] or "",
        current_stage=row["current_stage"] or "",
        progress=float(row["progress"] or 0.0),
        message=row["message"] or "",
        error_message=row["error_message"] or "",
        created_at=row["created_at"] or "",
        started_at=row["started_at"] or "",
        finished_at=row["finished_at"] or "",
        last_heartbeat_at=row["last_heartbeat_at"] or "",
        cancel_requested_at=row["cancel_requested_at"] or "",
        worker_pid=row["worker_pid"],
        metadata=_metadata_dict(row["metadata_json"]),
    )


class JobStore:
    def __init__(self, connection):
        self.connection = connection

    def ensure_jobs_table(self):
        cursor = self.connection.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {JOBS_TABLE} (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                database_id TEXT,
                current_stage TEXT,
                progress REAL NOT NULL DEFAULT 0.0,
                message TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                last_heartbeat_at TEXT,
                cancel_requested_at TEXT,
                worker_pid INTEGER,
                metadata_json TEXT
            )
        """)
        cursor.execute(f"PRAGMA table_info({JOBS_TABLE})")
        columns = {row[1] for row in cursor.fetchall()}
        for column_name, column_type in [
            ("last_heartbeat_at", "TEXT"),
            ("cancel_requested_at", "TEXT"),
            ("worker_pid", "INTEGER"),
        ]:
            if column_name not in columns:
                try:
                    cursor.execute(
                        f"ALTER TABLE {JOBS_TABLE} ADD COLUMN {column_name} {column_type}"
                    )
                except sqlite3.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise
        cursor.execute(f"""
            UPDATE {JOBS_TABLE}
            SET last_heartbeat_at = COALESCE(
                NULLIF(started_at, ''),
                created_at
            )
            WHERE last_heartbeat_at IS NULL OR last_heartbeat_at = ''
        """)
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_chemvault_jobs_created_at
            ON {JOBS_TABLE}(created_at)
        """)
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_chemvault_jobs_status
            ON {JOBS_TABLE}(status)
        """)
        self.connection.commit()

    def create_job(
        self,
        job_type=JobType.PUBCHEM_PROTEIN_SEARCH,
        database_id="",
        metadata=None,
        job_id=None,
    ):
        self.ensure_jobs_table()
        job_id = job_id or str(uuid.uuid4())
        created_at = _utc_now()
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            INSERT INTO {JOBS_TABLE} (
                job_id,
                job_type,
                status,
                database_id,
                current_stage,
                progress,
                message,
                error_message,
                created_at,
                last_heartbeat_at,
                cancel_requested_at,
                worker_pid,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                _enum_value(job_type),
                JobStatus.PENDING.value,
                database_id,
                "",
                0.0,
                "",
                "",
                created_at,
                created_at,
                "",
                None,
                _metadata_json(metadata),
            ),
        )
        self.connection.commit()
        return self.get_job(job_id)

    def start_job(self, job_id):
        self.ensure_jobs_table()
        now = _utc_now()
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET status = ?,
                started_at = COALESCE(started_at, ?),
                finished_at = NULL,
                error_message = '',
                last_heartbeat_at = ?
            WHERE job_id = ? AND status = ?
            """,
            (
                JobStatus.RUNNING.value,
                now,
                now,
                job_id,
                JobStatus.PENDING.value,
            ),
        )
        updated = cursor.rowcount == 1
        self.connection.commit()
        return self.get_job(job_id) if updated else None

    def heartbeat_job(self, job_id):
        self.ensure_jobs_table()
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET last_heartbeat_at = ?
            WHERE job_id = ? AND status IN (?, ?)
            """,
            (_utc_now(), job_id, *ACTIVE_JOB_STATUSES),
        )
        updated = cursor.rowcount == 1
        self.connection.commit()
        return self.get_job(job_id) if updated else None

    def set_worker_pid(self, job_id, worker_pid):
        self.ensure_jobs_table()
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET worker_pid = ?
            WHERE job_id = ?
            """,
            (int(worker_pid), job_id),
        )
        updated = cursor.rowcount == 1
        self.connection.commit()
        return self.get_job(job_id) if updated else None

    def cancel_job(self, job_id, message="Cancellation requested"):
        self.ensure_jobs_table()
        now = _utc_now()
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET status = ?,
                finished_at = ?,
                cancel_requested_at = ?,
                message = ?,
                last_heartbeat_at = ?
            WHERE job_id = ? AND status IN (?, ?)
            """,
            (
                JobStatus.CANCELLED.value,
                now,
                now,
                str(message),
                now,
                job_id,
                *ACTIVE_JOB_STATUSES,
            ),
        )
        updated = cursor.rowcount == 1
        self.connection.commit()
        return self.get_job(job_id) if updated else None

    def update_progress(self, job_id, stage, progress, message=None, metadata=None):
        self.ensure_jobs_table()
        cursor = self.connection.cursor()
        updates = [
            "current_stage = ?",
            "progress = ?",
            "last_heartbeat_at = ?",
        ]
        params = [stage, float(progress), _utc_now()]
        if message is not None:
            updates.append("message = ?")
            params.append(message)
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(_metadata_json(metadata))
        params.extend((job_id, *ACTIVE_JOB_STATUSES))
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET {", ".join(updates)}
            WHERE job_id = ? AND status IN (?, ?)
            """,
            params,
        )
        updated = cursor.rowcount == 1
        self.connection.commit()
        return self.get_job(job_id) if updated else None

    def complete_job(self, job_id, metadata=None):
        self.ensure_jobs_table()
        cursor = self.connection.cursor()
        updates = [
            "status = ?",
            "progress = ?",
            "finished_at = ?",
            "error_message = ''",
            "last_heartbeat_at = ?",
        ]
        now = _utc_now()
        params = [JobStatus.COMPLETED.value, 1.0, now, now]
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(_metadata_json(metadata))
        params.extend((job_id, *ACTIVE_JOB_STATUSES))
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET {", ".join(updates)}
            WHERE job_id = ? AND status IN (?, ?)
            """,
            params,
        )
        updated = cursor.rowcount == 1
        self.connection.commit()
        return self.get_job(job_id) if updated else None

    def fail_job(self, job_id, error_message, metadata=None):
        self.ensure_jobs_table()
        cursor = self.connection.cursor()
        updates = [
            "status = ?",
            "finished_at = ?",
            "error_message = ?",
        ]
        params = [JobStatus.FAILED.value, _utc_now(), str(error_message)]
        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(_metadata_json(metadata))
        params.extend((job_id, *ACTIVE_JOB_STATUSES))
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET {", ".join(updates)}
            WHERE job_id = ? AND status IN (?, ?)
            """,
            params,
        )
        updated = cursor.rowcount == 1
        self.connection.commit()
        return self.get_job(job_id) if updated else None

    def fail_stale_job(
        self,
        job_id,
        timeout_seconds=JOB_HEARTBEAT_TIMEOUT_SECONDS,
        now=None,
    ):
        self.ensure_jobs_table()
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=float(timeout_seconds))).isoformat()
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            UPDATE {JOBS_TABLE}
            SET status = ?,
                finished_at = ?,
                error_message = ?
            WHERE job_id = ?
              AND status IN (?, ?)
              AND last_heartbeat_at < ?
            """,
            (
                JobStatus.FAILED.value,
                now.isoformat(),
                STALE_JOB_ERROR_MESSAGE,
                job_id,
                *ACTIVE_JOB_STATUSES,
                cutoff,
            ),
        )
        marked_stale = cursor.rowcount == 1
        self.connection.commit()
        return marked_stale

    def get_active_job(
        self,
        job_id,
        timeout_seconds=JOB_HEARTBEAT_TIMEOUT_SECONDS,
        now=None,
    ):
        self.fail_stale_job(job_id, timeout_seconds=timeout_seconds, now=now)
        job = self.get_job(job_id)
        if job is None or job.status not in ACTIVE_JOB_STATUSES:
            return None
        return job

    def get_job(self, job_id):
        self.ensure_jobs_table()
        original_factory = self.connection.row_factory
        self.connection.row_factory = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                f"""
                SELECT
                    job_id,
                    job_type,
                    status,
                    database_id,
                    current_stage,
                    progress,
                    message,
                    error_message,
                    created_at,
                    started_at,
                    finished_at,
                    last_heartbeat_at,
                    cancel_requested_at,
                    worker_pid,
                    metadata_json
                FROM {JOBS_TABLE}
                WHERE job_id = ?
                """,
                (job_id,),
            )
            row = cursor.fetchone()
        finally:
            self.connection.row_factory = original_factory
        if row is None:
            return None
        keys = [
            "job_id",
            "job_type",
            "status",
            "database_id",
            "current_stage",
            "progress",
            "message",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
            "last_heartbeat_at",
            "cancel_requested_at",
            "worker_pid",
            "metadata_json",
        ]
        return _job_from_row(dict(zip(keys, row)))

    def list_jobs(self, limit=50):
        self.ensure_jobs_table()
        limit = max(1, int(limit))
        original_factory = self.connection.row_factory
        self.connection.row_factory = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                f"""
                SELECT
                    job_id,
                    job_type,
                    status,
                    database_id,
                    current_stage,
                    progress,
                    message,
                    error_message,
                    created_at,
                    started_at,
                    finished_at,
                    last_heartbeat_at,
                    cancel_requested_at,
                    worker_pid,
                    metadata_json
                FROM {JOBS_TABLE}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        finally:
            self.connection.row_factory = original_factory
        keys = [
            "job_id",
            "job_type",
            "status",
            "database_id",
            "current_stage",
            "progress",
            "message",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
            "last_heartbeat_at",
            "cancel_requested_at",
            "worker_pid",
            "metadata_json",
        ]
        return [_job_from_row(dict(zip(keys, row))) for row in rows]


def ensure_jobs_table(connection):
    return JobStore(connection).ensure_jobs_table()


def create_job(connection, **kwargs):
    return JobStore(connection).create_job(**kwargs)


def start_job(connection, job_id):
    return JobStore(connection).start_job(job_id)


def update_progress(connection, job_id, stage, progress, message=None, metadata=None):
    return JobStore(connection).update_progress(
        job_id,
        stage,
        progress,
        message=message,
        metadata=metadata,
    )


def heartbeat_job(connection, job_id):
    return JobStore(connection).heartbeat_job(job_id)


def set_worker_pid(connection, job_id, worker_pid):
    return JobStore(connection).set_worker_pid(job_id, worker_pid)


def cancel_job(connection, job_id, message="Cancellation requested"):
    return JobStore(connection).cancel_job(job_id, message=message)


def complete_job(connection, job_id, metadata=None):
    return JobStore(connection).complete_job(job_id, metadata=metadata)


def fail_job(connection, job_id, error_message, metadata=None):
    return JobStore(connection).fail_job(
        job_id,
        error_message,
        metadata=metadata,
    )


def get_job(connection, job_id):
    return JobStore(connection).get_job(job_id)


def fail_stale_job(
    connection,
    job_id,
    timeout_seconds=JOB_HEARTBEAT_TIMEOUT_SECONDS,
    now=None,
):
    return JobStore(connection).fail_stale_job(
        job_id,
        timeout_seconds=timeout_seconds,
        now=now,
    )


def get_active_job(
    connection,
    job_id,
    timeout_seconds=JOB_HEARTBEAT_TIMEOUT_SECONDS,
    now=None,
):
    return JobStore(connection).get_active_job(
        job_id,
        timeout_seconds=timeout_seconds,
        now=now,
    )


def list_jobs(connection, limit=50):
    return JobStore(connection).list_jobs(limit=limit)
