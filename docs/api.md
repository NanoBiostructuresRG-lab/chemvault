# API Reference

CHEMVAULT exposes a FastAPI boundary for supported database reads and exports,
UniProt resolution, PubChem protein-search jobs, scientific runtime activation,
HARMONSMILE and MODELABILITY INDEX jobs, structure consolidation, and
fingerprint artifact export.

## Starting FastAPI

From the working directory that contains the `SQL/` database directory:

```bash
python -m uvicorn api.main:app --reload
```

The default base URL is `http://127.0.0.1:8000`. Interactive OpenAPI
documentation is available at
[`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs).

Database identifiers are path-safe names containing letters, numbers,
underscores, or hyphens. Most database endpoints require an existing
`SQL/<database_id>.db`; the API does not provide a database-creation endpoint.

## Endpoint inventory

| Method | Path | Capability |
|---|---|---|
| `GET` | `/health` | Service health. |
| `GET` | `/protein-identifiers/uniprot/organisms` | Ordered supported-organism catalog. |
| `GET` | `/protein-identifiers/uniprot` | Resolve one gene symbol and organism to one reviewed UniProt target. |
| `POST` | `/databases/{database_id}/scientific-runtime/activate` | Activate recovery for scientific jobs in one database. |
| `POST` | `/databases/{database_id}/jobs/pubchem_protein_search` | Launch a persisted PubChem protein-search job. |
| `GET` | `/databases/{database_id}/jobs/pubchem_protein_search/{job_id}` | Read PubChem job status. |
| `POST` | `/databases/{database_id}/jobs/pubchem_protein_search/{job_id}/cancel` | Cancel an active PubChem job. |
| `POST` | `/databases/{database_id}/jobs/pubchem_protein_search/{job_id}/finalize` | Register a completed PubChem build exactly once. |
| `POST` | `/databases/{database_id}/jobs/harmonsmile` | Launch a HARMONSMILE scientific job. |
| `POST` | `/databases/{database_id}/jobs/modelability_index` | Launch a MODELABILITY INDEX scientific job. |
| `GET` | `/databases/{database_id}/jobs/harmonsmile/active` | Find the active HARMONSMILE job for a table. |
| `GET` | `/databases/{database_id}/jobs/{job_id}` | Read generic persisted scientific-job status. |
| `GET` | `/databases/{database_id}/tables` | List user-visible tables. |
| `GET` | `/databases/{database_id}/operations` | Read operation history newest first. |
| `GET` | `/databases/{database_id}/tables/{table_name}/metadata` | Read columns, row count, schema, provenance, and available summaries. |
| `GET` | `/databases/{database_id}/tables/{table_name}/metrics` | Read row and optional grouped counts. |
| `GET` | `/databases/{database_id}/tables/{table_name}/preview` | Preview selected columns. |
| `GET` | `/databases/{database_id}/tables/{table_name}/export` | Download a complete table or selected columns as UTF-8 CSV. |
| `POST` | `/databases/{database_id}/tables/{table_name}/structure-consolidation` | Create an ACTIVITY LABELS structure-level table. |
| `GET` | `/databases/{database_id}/tables/{table_name}/modelability-index/fingerprints/export` | Download one validated fingerprint artifact as `.npz`. |

The route definitions in `api/main.py` and response models in `api/schemas.py`
are authoritative.

## UniProt target resolution

### Supported organisms

```http
GET /protein-identifiers/uniprot/organisms
```

The response contains the backend-defined ordered catalog with organism ID,
scientific name, and common name.

### Resolve a gene symbol

```http
GET /protein-identifiers/uniprot?gene_symbol=LEPR&organism_id=9606
```

Successful resolution returns the gene symbol, organism identity, UniProt
accession, entry name, protein name, and reviewed status. The resolution is
strict: invalid input returns 422, no reviewed match returns 404, ambiguity
returns 409, and upstream UniProt failure returns 502.

Direct UniProt-accession entry is a Streamlit input mode and does not require a
separate resolver endpoint.

## Public persisted-job status

Scientific and PubChem status responses use the same stable public field
shape:

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

Supported lifecycle states are `pending`, `running`, `completed`, `failed`, and
`cancelled`. A terminal success has `status=completed`, `progress=1.0`, and its
stable result summary in `result`. Workflow failure is persisted as
`status=failed` with `error`. Internal request metadata, worker process IDs,
heartbeats, and cancellation timestamps are not public status fields.

`cancellable` describes the persisted job's current capability; it is not a
promise that every job type has a public cancellation endpoint. PubChem has an
explicit cancellation route. HARMONSMILE and MODELABILITY INDEX currently do
not.

## Execution contracts

### PubChem protein-search jobs

PubChem execution uses a dedicated persisted-job adapter and an external worker
process. Launching creates the job and starts that worker:

```http
POST /databases/example/jobs/pubchem_protein_search
Content-Type: application/json
```

```json
{
  "proteins": ["P34971"],
  "target_identity": {
    "input_mode": "uniprot_accession",
    "uniprot_accession": "P34971"
  }
}
```

`target_identity` is optional, but when supplied it must agree with the single
protein accession. Launch returns 201 with the persisted status. Use the
PubChem-specific status endpoint while the worker runs.

Cancellation is safe for active jobs and idempotently returns an already
terminal status. Finalization accepts only a completed PubChem job and records
the base-table metadata and build operation exactly once. Invalid job type or
state returns 409; invalid launch input returns 422.

### Generic scientific jobs

`application.scientific_jobs` is the generic application boundary used by the
HARMONSMILE and MODELABILITY INDEX workflows. Each registered job type supplies
create and execute hooks. The launch route creates a persisted job, claims one
in-process daemon-thread executor, and returns immediately. The generic status
endpoint reads the persisted record without dispatching to a workflow-specific
status function.

This mechanism is not identical to PubChem execution: PubChem uses its own
specific routes and separate worker process, while generic scientific jobs run
through registered hooks in the active Streamlit or FastAPI process. They share
the public status projection and SQLite persistence, not an execution engine.

#### HARMONSMILE launch

```http
POST /databases/example/jobs/harmonsmile
Content-Type: application/json
```

```json
{
  "table_name": "main",
  "cid_column": "CID"
}
```

The source table and CID column must exist. Missing resources return 404 and an
invalid column returns 422.

The active lookup requires `table_name`:

```http
GET /databases/example/jobs/harmonsmile/active?table_name=main
```

It returns the equivalent active job or `null`.

#### MODELABILITY INDEX launch

```http
POST /databases/example/jobs/modelability_index
Content-Type: application/json
```

```json
{
  "table_name": "activity_subset_IC50_structure_consolidated",
  "fingerprint_type": "morgan"
}
```

The table must be an eligible ACTIVITY LABELS consolidated source. A compatible
completed analysis can be returned immediately; otherwise a pending job is
executed through the scientific runtime. Missing resources return 404 and an
invalid scientific source returns 422.

### Scientific runtime activation

```http
POST /databases/example/scientific-runtime/activate
```

Activation runs once per database path in the current process. It marks
orphaned MODELABILITY INDEX jobs according to their non-resumable contract,
requeues resumable HARMONSMILE jobs, starts their executors, and returns the
recovered HARMONSMILE job snapshots with `table_name`. It does not create a
distributed worker service.

## Local and API-client semantics

`clients.backend_gateway.BackendGateway` presents the same interface to
Streamlit in both modes:

- with no `CHEMVAULT_API_URL`, the local backend calls application and service
  functions directly;
- with `CHEMVAULT_API_URL`, the HTTP backend calls the endpoints above and
  converts payloads into the same contracts.

Local HARMONSMILE and MODELABILITY launches run a daemon thread in the
Streamlit process. HTTP launches run one in the FastAPI process. PubChem launch
starts the external worker from the selected backend process. All modes persist
status in the selected database and the UI polls until a terminal state.

Transport failures are distinct from persisted workflow failures. An
unreachable backend or invalid HTTP response raises `BackendGatewayError`; it
does not establish that the persisted scientific job failed. Only the stored
job status is authoritative for workflow success or failure. The gateway never
silently falls back to local execution.

## Database inspection

### Tables and operation history

`GET /databases/{database_id}/tables` returns the user-visible table names.
`GET /databases/{database_id}/operations` returns persisted operation records
newest first, including operation type, source and target table, source columns,
timestamp, status, and details when available.

### Metadata and schema

```http
GET /databases/example/tables/main/metadata
```

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
  ],
  "origin": "protein_search",
  "source_table": null,
  "structure_consolidation_summary": null,
  "target_identity": null
}
```

Target identity and consolidation summary are included only when valid
persisted provenance exists.

`GET /metrics` returns `row_count` and `group_count`; the optional
`group_column` query parameter selects a valid grouping column. `GET /preview`
accepts repeated `columns` parameters and returns at most ten rows.

## Structure consolidation

```http
POST /databases/example/tables/activity_subset_IC50/structure-consolidation
```

The endpoint creates the ACTIVITY LABELS structure-level table and returns its
generated name plus source, valid, unique, created, Active, Inactive,
conflicting, non-binary, unusable, duplicated, represented, reference, and
no-eligible-activity counts. Missing resources return 404; scientific
ineligibility returns 422.

## Downloads

### Table CSV

```http
GET /databases/example/tables/main/export?columns=CID&columns=SMILES
```

The response is UTF-8 `text/csv` and contains every row for the requested
columns in request order. Omitting `columns` exports the complete table. Unknown
columns return 422. Filtered subgroup and Structured activity exports are UI
workflows outside this endpoint.

### Fingerprint artifact

```http
GET /databases/example/tables/activity_subset_IC50_structure_consolidated/modelability-index/fingerprints/export?analysis_identity=<identity>&fingerprint_type=morgan
```

The response is `application/octet-stream` with the backend-generated `.npz`
filename. The endpoint only reads an existing artifact validated against the
source table, analysis identity, and fingerprint type; it never calculates new
fingerprints. A stale identity or missing, corrupt, or incompatible artifact
returns 409.

## Current boundary

The API does not create or delete databases, provide general table mutation,
or act as a distributed worker platform. Filtered subgroup export and complete
Structured activity export remain application workflows rather than table
export endpoint variants. These limits do not apply to the explicitly supported
PubChem execution, PubChem cancellation, structure consolidation, or scientific
jobs documented above.

The `api/`, `application/`, and `services/` layers remain independent of
Streamlit and `st.session_state`.
