# FastAPI read-only API

CHEMVAULT provides a FastAPI read-only API.

## Run locally

```bash
python -m uvicorn api.main:app --reload
```

Interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Streamlit read-only backend gateway

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
history, metadata, metrics, previews, and table CSV export. When
`CHEMVAULT_API_URL` is defined, its HTTP backend uses:

- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/operations`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`
- `GET /databases/{database_id}/tables/{table_name}/export`

When `CHEMVAULT_API_URL` is not defined, the gateway delegates to the existing
local application use cases and services. Streamlit screens do not select a
backend themselves. If HTTP mode is selected and a request fails, the error is
surfaced to Streamlit; the gateway never silently falls back to local access.

The API-client scope remains read-only. PubChem, jobs and workers, curation,
filtered subgroup and structured-activity exports, and table mutations remain
outside FastAPI in this cycle. This advances Level 2 by moving read-only
exploration and the minimal table-export surface behind FastAPI, but it does
not yet replace all local routes or make FastAPI a complete backend.

P23 defines a future generic job-status shape, but no job endpoint exists yet.
Current job reads can perform migrations and stale-state transitions, so they
are not suitable for this read-only API boundary. See
[Future backend job-status contract](job_contract.md).

## Current endpoints

- `GET /health`
- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/operations`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`
- `GET /databases/{database_id}/tables/{table_name}/export`

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

The API is read-only. It does not create databases, modify tables, run PubChem, run HARMONSMILE, or launch workers.

## Architectural rule

`api/`, `application/`, and `services/` must not depend on Streamlit or `st.session_state`.
