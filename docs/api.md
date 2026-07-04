# FastAPI backend API

CHEMVAULT provides a FastAPI API for supported database reads and the controlled HARMONSMILE command.

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
history, metadata, metrics, previews, table CSV export, and HARMONSMILE. When
`CHEMVAULT_API_URL` is defined, its HTTP backend uses:

- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/operations`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`
- `GET /databases/{database_id}/tables/{table_name}/export`
- `POST /databases/{database_id}/jobs/harmonsmile`
- `GET /databases/{database_id}/jobs/{job_id}`

When `CHEMVAULT_API_URL` is not defined, the gateway delegates to the existing
local application use cases and services. Streamlit screens do not select a
backend themselves. If HTTP mode is selected and a request fails, the error is
surfaced to Streamlit; the gateway never silently falls back to local access.

HARMONSMILE uses a minimal synchronous runtime in the FastAPI process. The POST
request runs preparation, chunk processing, cache merge, and provenance before
returning; the resulting status remains queryable through the GET endpoint.
This is not a remote worker. PubChem, CHAMANP, cancellation, filtered subgroup
and structured-activity exports, and general table mutations remain outside
FastAPI in this cycle.

## Current endpoints

- `GET /health`
- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/operations`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`
- `GET /databases/{database_id}/tables/{table_name}/export`
- `POST /databases/{database_id}/jobs/harmonsmile`
- `GET /databases/{database_id}/jobs/{job_id}`

## HARMONSMILE job

Launch a synchronous job with:

```json
{
  "table_name": "main",
  "cid_column": "CID"
}
```

The launch and status responses share the typed job contract: `job_id`,
`job_type`, `status`, `database_id`, `stage`, `progress`, `message`, timestamps,
`result`, and `error`. Status and provenance are persisted in the same SQLite
database. Local mode remains the default and invokes the same application use
case directly through the gateway.

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
or launch remote workers. Only the HARMONSMILE command crosses the mutation
boundary in this milestone.

## Architectural rule

`api/`, `application/`, and `services/` must not depend on Streamlit or `st.session_state`.
