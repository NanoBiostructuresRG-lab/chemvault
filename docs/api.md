# FastAPI read-only API

CHEMVAULT provides a FastAPI read-only API.

## Run locally

```bash
python -m uvicorn api.main:app --reload
```

Interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Streamlit API-client pilot

CHEMVAULT can run in an experimental dual mode with FastAPI serving read-only data and Streamlit consuming it over HTTP.

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

When `CHEMVAULT_API_URL` is defined, **Columns → Selected columns preview** uses FastAPI over HTTP. When it is not defined, Streamlit uses the traditional local path.

Only **Selected columns preview** uses FastAPI in this pilot. PubChem, HARMONSMILE, Export, Refine, Table Manager, and workers continue to use their current local paths. This is a step toward using Streamlit as a frontend, not a complete replacement of the local architecture.

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
