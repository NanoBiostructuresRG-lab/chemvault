# Future backend job-status contract

P23 defines a typed read-only status contract; it does not add a runtime job
endpoint or move any execution into FastAPI.

## Current architecture

Persistent jobs use `JobRecord` and `JobStore` in each ChemVault SQLite
database. The only current job type is `pubchem_protein_search`. A local worker
updates status, stage, progress, heartbeat, timestamps, messages, errors, and
process-specific metadata.

Streamlit stores both `job_id` and the database path in session state. Its
PubChem polling service checks for stale jobs and can mark them failed before
returning a view. Cancellation is also performed directly through the local
service.

This means the current status path is not strictly read-only:

- `JobStore.get_job()` and `list_jobs()` run table creation/migrations through
  `ensure_jobs_table()`.
- PubChem polling calls `fail_stale_job()`, which may update job status.
- `PubChemJobView` includes PubChem proteins and lifecycle flags specific to
  the current UI.

## Minimal public status shape

`application.job_contracts.JobStatusContract` defines the proposed reusable
shape:

```json
{
  "job_id": "job-1",
  "job_type": "pubchem_protein_search",
  "status": "running",
  "database_id": "example",
  "stage": "compound_names",
  "progress": 0.6,
  "message": "Fetching names",
  "created_at": "2026-07-03T10:00:00+00:00",
  "started_at": "2026-07-03T10:00:01+00:00",
  "finished_at": null,
  "error": null,
  "cancellable": true
}
```

Supported lifecycle values are `pending`, `running`, `completed`, `failed`,
and `cancelled`. `cancellable` is informational: it is true only for pending or
running jobs and does not imply that a cancellation endpoint exists.

Execution metadata, proteins, worker PID, heartbeat, and cancellation-request
timestamps are intentionally internal. There is no `updated_at` yet because
the current store has no timestamp that reliably represents every state
change; `last_heartbeat_at` is not an equivalent contract.

## Required split before a runtime endpoint

A future read-only endpoint such as
`GET /databases/{database_id}/jobs/{job_id}` should wait until:

1. Job-table initialization and migrations are separated from pure reads.
2. Stale-job transitions run in a worker or maintenance path, never in GET.
3. Database/job lookup no longer depends on a Streamlit-owned filesystem path.
4. API failure and not-found behavior can use the existing backend boundary
   without local fallback.

No POST, execution, worker-launch, or cancellation endpoint is proposed by
P23.
