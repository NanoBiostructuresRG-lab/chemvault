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

The gateway exposes one contract to Streamlit for table listing, metadata,
metrics, and previews. When `CHEMVAULT_API_URL` is defined, its HTTP backend uses:

- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`

When `CHEMVAULT_API_URL` is not defined, the gateway delegates to the existing
local application use cases and services. Streamlit screens do not select a
backend themselves. If HTTP mode is selected and a request fails, the error is
surfaced to Streamlit; the gateway never silently falls back to local access.

The API-client scope remains read-only. PubChem, jobs and workers, curation, exports, and table mutations remain outside FastAPI in this cycle and continue to use their current local paths. This advances Level 2 by moving read-only exploration behind FastAPI, but it does not yet replace all local routes or make FastAPI a complete backend.

## Current endpoints

- `GET /health`
- `GET /databases/{database_id}/tables`
- `GET /databases/{database_id}/tables/{table_name}/metadata`
- `GET /databases/{database_id}/tables/{table_name}/metrics`
- `GET /databases/{database_id}/tables/{table_name}/preview`

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
  "read_only": true
}
```

This endpoint is read-only. It does not export complete data or run PubChem or HARMONSMILE.

## Current limitations

The API is read-only. It does not create databases, modify tables, run PubChem, run HARMONSMILE, or launch workers.

## Architectural rule

`api/`, `application/`, and `services/` must not depend on Streamlit or `st.session_state`.
