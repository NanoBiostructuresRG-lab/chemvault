# Scientific backend job contract

CHEMVAULT v0.10.0 treats scientific backend work as a generic persisted job
contract. HARMONSMILE is the first workflow behind this contract; CHAMANP and
PubChem API execution are not migrated in this cycle.

## Public status shape

`application.job_contracts.JobStatusContract` is the public shape returned by
the backend gateway and by `GET /databases/{database_id}/jobs/{job_id}`:

```json
{
  "job_id": "job-1",
  "job_type": "harmonsmile",
  "status": "running",
  "database_id": "example",
  "stage": "running",
  "progress": 0.4,
  "message": "HARMONSMILE chunk 1/3",
  "created_at": "2026-07-03T10:00:00+00:00",
  "updated_at": "2026-07-03T10:00:10+00:00",
  "started_at": "2026-07-03T10:00:01+00:00",
  "finished_at": null,
  "error": null,
  "result": null,
  "cancellable": true
}
```

Supported lifecycle values remain `pending`, `running`, `completed`, `failed`,
and `cancelled`. `cancellable` is informational: it is true for pending/running
jobs, but v0.10.0 does not add a public cancellation endpoint.

Internal metadata such as workflow request payloads, worker process IDs,
heartbeats, and cancellation timestamps are not part of the public contract.
Only the stable `result` summary is exposed.

## Generic application boundary

`application.scientific_jobs` owns the reusable job boundary:

- workflow modules register create/execute hooks by `job_type`
- `create_scientific_job(...)` creates a queued job through the registered hook
- `execute_scientific_job(...)` runs the queued job through the registered hook
- `get_scientific_job_status(...)` reads persisted status without importing or
  dispatching to HARMONSMILE-specific status lookup

HARMONSMILE-specific validation, preparation, chunk execution, cache merging,
operation logging, and result summary mapping remain in
`application.harmonsmile_jobs` and `services.harmonsmile_cache`.

## Local and API semantics

The Streamlit gateway uses the same launch/poll/terminal model in both modes.

Local mode creates a persisted job and starts a daemon thread in the Streamlit
process. API mode posts to FastAPI, which creates the same persisted job and
starts a daemon thread in the FastAPI process. In both modes Streamlit polls
`get_job_status(...)` until a terminal status.

Transport failures are separate from persisted job failures:

- backend unreachable or HTTP/client errors raise `BackendGatewayError`; they
  do not imply that a job failed unless a persisted job status says so
- workflow failures are represented as `status=failed` with `error`
- stale/lost active jobs use generic wording:
  `Backend job stopped unexpectedly. Please try again.`
- success is represented as `status=completed`, `progress=1.0`, and a stable
  workflow result summary

## HARMONSMILE 0.3.1 result contract

CHEMVAULT pins `harmonsmile==0.3.1`. The PubChem integration now consumes
`PubChemIngest.run()` directly as a DataFrame. Expected output fields include:

- `PubChem_CID`
- `SMILES_RDKit`
- `SMILES_Harmonized`
- `SMILES_Harmonization_Status`
- `SMILES_Harmonization_Message`
- `InChI` and `InChIKey` when produced by the PubChem workflow

Known harmonization status values are `ok`, `ok_with_warnings`, `unsupported`,
and `failed`. CHEMVAULT preserves these values and messages through the
HARMONSMILE cache and table merge.
