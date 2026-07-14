# SPDX-License-Identifier: LGPL-3.0-or-later
"""Single-process executor ownership and startup recovery for scientific jobs."""
import errno
import os
from threading import Lock, Thread

from application.harmonsmile_jobs import recover_orphaned_harmonsmile_jobs
from application.database_use_cases import resolve_database_path
from application.scientific_jobs import (
    claim_scientific_job_executor,
    execute_scientific_job,
)
from services.job_models import JobType


_runtime_lock = Lock()
_activation_lock = Lock()
_executors = {}
_activated_databases = {}


def _executor_key(database_id, job_id):
    return str(database_id), str(job_id)


def scientific_job_executor_is_alive(database_id, job_id):
    with _runtime_lock:
        thread = _executors.get(_executor_key(database_id, job_id))
        return thread is not None and thread.is_alive()


def process_is_alive(pid):
    """Return whether an external worker PID still names a live process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied means it exists.
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError as error:
        return error.errno not in {errno.ESRCH, errno.EINVAL}
    return True


def start_scientific_job_executor(
    database_id,
    job_type,
    job_id,
    *,
    name=None,
):
    """Claim and start one daemon executor, returning an existing live owner."""
    key = _executor_key(database_id, job_id)
    with _runtime_lock:
        existing = _executors.get(key)
        if existing is not None and existing.is_alive():
            return existing
        if not claim_scientific_job_executor(
            database_id,
            job_id,
            os.getpid(),
        ):
            return None

        def run():
            try:
                execute_scientific_job(database_id, job_type, job_id)
            finally:
                with _runtime_lock:
                    _executors.pop(key, None)

        thread = Thread(
            target=run,
            daemon=True,
            name=name or f"chemvault-{job_type}",
        )
        _executors[key] = thread
        try:
            thread.start()
        except Exception:
            _executors.pop(key, None)
            raise
        return thread


def activate_scientific_runtime(database_id, *, db_dir="SQL"):
    """Recover jobs once for one explicitly activated database."""
    db_path = resolve_database_path(database_id, db_dir=db_dir)
    database_key = os.path.normcase(str(db_path))
    with _activation_lock:
        if database_key in _activated_databases:
            return _activated_databases[database_key]
        recovered = recover_orphaned_harmonsmile_jobs(
            database_id,
            db_dir=db_dir,
            executor_is_alive=scientific_job_executor_is_alive,
            process_is_alive=process_is_alive,
            current_pid=os.getpid(),
        )
        for recovered_job in recovered:
            start_scientific_job_executor(
                database_id,
                JobType.HARMONSMILE,
                recovered_job.job.job_id,
                name="chemvault-harmonsmile-recovery",
            )
        result = tuple(recovered)
        _activated_databases[database_key] = result
        return result


def _reset_scientific_runtime_for_tests():
    with _activation_lock:
        _activated_databases.clear()
    with _runtime_lock:
        _executors.clear()
