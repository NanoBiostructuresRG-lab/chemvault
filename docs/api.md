# FastAPI backend API

CHEMVAULT provides a FastAPI API for supported database reads, controlled
scientific backend jobs, structure consolidation, and binary Modelability
fingerprint export.

## Run locally

```bash
python -m uvicorn api.main:app --reload
```

Interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Streamlit backend gateway

Streamlit consumes database exploration data through one backend gateway. The
gateway selects the local application/services backend by default, or the HTTP
FastAPI backend when `CHEMVAULT_API_URL` is configured.

Terminal 1:

```powershell
conda activate chemvault_env
python -m uvicorn api.main:app --reload
```

Terminal 2:

```powershell
conda activate chemvault_env
$env:CHEMVAULT_API_URL="http://127.0.0.1:8000"
streamlit run app.py
```

The gateway exposes one contract to Streamlit for table listing, operation
history, metadata, metrics, previews, table CSV export, and scientific jobs.
When `CHEMVAULT_API_URL` is defined, its HTTP backend uses:

- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/operations`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`
- `GET /databases/{database_id}/tables/{table_name}/export`
- `POST /databases/{database_id}/scientific-runtime/activate`
- `POST /databases/{database_id}/jobs/harmonsmile`
- `POST /databases/{database_id}/jobs/modelability_index`
- `GET /databases/{database_id}/jobs/harmonsmile/active`
- `GET /databases/{database_id}/jobs/{job_id}`
- `POST /databases/{database_id}/tables/{table_name}/structure-consolidation`
- `GET /databases/{database_id}/tables/{table_name}/modelability-index/fingerprints/export`

When `CHEMVAULT_API_URL` is not defined, the gateway delegates to the existing
local application use cases and services. Streamlit screens do not select a
backend themselves. If HTTP mode is selected and a request fails, the error is
surfaced to Streamlit; the gateway never silently falls back to local access.

SMILES HARMONIZED uses the external HARMONSMILE engine, and both HARMONSMILE
and Modelability Index use the generic scientific job contract. Launch requests
return persisted job status while execution continues in an in-process
background thread when needed. Streamlit polls the generic GET endpoint for
persisted progress and terminal status. This is not a remote worker.

## Current endpoints

- `GET /health`
- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/operations`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`
- `GET /databases/{database_id}/tables/{table_name}/export`
- `POST /databases/{database_id}/scientific-runtime/activate`
- `POST /databases/{database_id}/jobs/harmonsmile`
- `POST /databases/{database_id}/jobs/modelability_index`
- `GET /databases/{database_id}/jobs/harmonsmile/active`
- `GET /databases/{database_id}/jobs/{job_id}`
- `POST /databases/{database_id}/tables/{table_name}/structure-consolidation`
- `GET /databases/{database_id}/tables/{table_name}/modelability-index/fingerprints/export`

## Scientific runtime activation

`POST /databases/{database_id}/scientific-runtime/activate` activates recovery
once for the selected database in the current API process. It resolves orphaned
Modelability jobs, recovers resumable HARMONSMILE jobs, and returns
`database_id` plus the `recovered_jobs` list. A missing database returns HTTP
404.

## SMILES HARMONIZED job

The SMILES HARMONIZED operation is implemented by the external HARMONSMILE
engine. Launch it with `POST /databases/{database_id}/jobs/harmonsmile` and:

```json
{
  "table_name": "main",
  "cid_column": "CID"
}
```

The launch and status responses share the typed job contract: `job_id`,
`job_type`, `status`, `database_id`, `stage`, `progress`, `message`, timestamps,
`result`, `error`, and `cancellable`. Status and provenance are persisted in the
same SQLite database. Local mode remains the default and uses the same
launch/poll/terminal semantics as API mode through the backend gateway.

`GET /databases/{database_id}/jobs/{job_id}` is job-type-neutral. It reads the
persisted job record from the selected database and does not dispatch to a
HARMONSMILE-specific status function.

### Active HARMONSMILE job lookup

`GET /databases/{database_id}/jobs/harmonsmile/active` requires the
`table_name` query parameter. It returns the equivalent active HARMONSMILE job
for that table, or `null` when none exists. A missing database returns HTTP 404.

## Modelability Index job

Launch with `POST /databases/{database_id}/jobs/modelability_index` and:

```json
{
  "table_name": "activity_subset_IC50_structure_consolidated"
}
```

The source must be an eligible ACTIVITY LABELS consolidated table. The endpoint
uses the generic persisted job contract and may return an exact compatible
completed analysis immediately; otherwise the pending job executes through the
scientific runtime. Missing databases or tables return HTTP 404, and an invalid
Modelability source returns HTTP 422.

## Structure consolidation

`POST /databases/{database_id}/tables/{table_name}/structure-consolidation`
creates the ACTIVITY LABELS consolidated structure table and returns its counts
and generated table name. Missing databases or tables return HTTP 404; an
ineligible source returns HTTP 422.

## Modelability fingerprint NPZ export

`GET /databases/{database_id}/tables/{table_name}/modelability-index/fingerprints/export`
requires the `analysis_identity` query parameter. A successful response uses
`application/octet-stream`; `Content-Disposition` preserves the filename
generated by the backend, following
`<database_id>_<activity_type>*fingerprints*<analysis8>.npz`.

Missing databases or tables return HTTP 404. A stale `analysis_identity`, or a
missing, corrupt, or incompatible fingerprint artifact, returns HTTP 409. The
export reads the existing validated artifact only: it never calculates
fingerprints.

Backend transport failures are gateway/API-client errors, not persisted job
failures. Persisted workflow failures are represented by `status=failed` and
`error`; stale/lost jobs use generic backend-job wording.

## Table metadata

`GET /databases/{database_id}/tables/{table_name}/metadata` inspects the metadata of an existing table before requesting a preview.

Expected response:

```json
{
  "database_id": "example",
  "table": "main",
  "columns": ["CID", "SMILES"],
  "row_count": 100,
  "preview_limit": 10,
  "read_only": true,
  "schema": [
    {
      "cid": 0,
      "name": "CID",
      "data_type": "TEXT",
      "not_null": false,
      "default_value": null,
      "primary_key": false
    }
  ]
}
```

The detailed `schema` field powers the Streamlit active-table schema inspection
through the same backend gateway. This endpoint is read-only. It does not export
complete data or run PubChem or HARMONSMILE.

## Operation history

`GET /databases/{database_id}/operations` returns the recorded database
operations newest first. It powers the Streamlit operation-history inspection
and does not create, rerun, export, or delete anything.

## Table CSV export

`GET /databases/{database_id}/tables/{table_name}/export` returns a UTF-8 CSV
containing all rows from the table. Repeated `columns` query parameters select
and order exported columns; omitting `columns` exports every table column.

The contract has a fixed full-table row scope, `text/csv` output, and no filter
parameters. Unknown columns return HTTP 422, and missing databases or tables
return HTTP 404. Filtered subgroup and structured-activity CSV exports are not
part of this endpoint.

## Current limitations

The API does not create databases, run PubChem or CHAMANP, expose cancellation,
or launch remote workers. Filtered subgroup and structured-activity exports and
general table mutations other than structure consolidation remain outside this
API surface.

## Architectural rule

`api/`, `application/`, and `services/` must not depend on Streamlit or `st.session_state`.
