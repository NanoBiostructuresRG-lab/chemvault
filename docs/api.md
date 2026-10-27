# API Reference

ChemVault exposes an optional FastAPI interface for supported database reads,
exports, UniProt gene-symbol resolution, PubChem protein-search jobs, scientific
jobs, structure consolidation, and fingerprint artifact retrieval. The API does
not expose every operation available in the Streamlit interface. Routine use
through `chemvault` does not require starting FastAPI; see the [Usage guide](usage.md).

## Starting FastAPI

From the working directory containing the `SQL/` database directory, run
FastAPI in the Python environment where ChemVault is installed:

```bash
python -m uvicorn api.main:app
```

The `--reload` option may be added for source development. It is not required
to operate the API. The default base URL is `http://127.0.0.1:8000`, and
interactive OpenAPI documentation is available at
[`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs).

Database identifiers may contain letters, numbers, underscores, and hyphens.
Database operations require an existing `SQL/<database_id>.db` in the active
working directory; the API does not provide an endpoint for creating databases.
When using the Streamlit API-client mode, start both processes from the same
working directory so that they refer to the same SQLite databases.

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
define the HTTP contract. The routes listed here are the implemented endpoints;
the API is not a general-purpose interface for all Streamlit operations.

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

Scientific and PubChem job-status endpoints use a shared response schema.
The following JSON illustrates its fields; the values are examples, not an
observed job:

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
`cancelled`. HTTP 201 alone does not establish workflow completion: inspect
the returned `status`, which can already be `completed` for a reused result.
Successful completion has `status=completed`, `progress=1.0`, and a result
summary in `result`; a persisted workflow failure has `status=failed` and an
`error`.
Internal request metadata, worker process IDs, heartbeats, and cancellation
timestamps are not public status fields.

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

`proteins` is a non-empty list of accession strings. The target-centered UI
uses one biological target. The optional `target_identity` payload is permitted
only when `proteins` contains exactly one accession and must identify that same
target. Launch returns HTTP 201 with the persisted job status; inspect the
PubChem-specific status endpoint to determine the workflow outcome.

Cancellation is supported for active PubChem jobs; repeated cancellation of an
already terminal job returns its terminal status. Finalization requires a
completed job and registers its base-table metadata and build operation exactly
once. Finalization is not a separate certification of source-record
completeness. Invalid job type or state returns 409; invalid launch input
returns 422.

### Generic scientific jobs

`application.scientific_jobs` is the application boundary for HARMONSMILE
and MODELABILITY INDEX jobs. Each registered workflow supplies creation and
execution hooks. Launch returns a persisted job status and starts an in-process
executor for pending work. A compatible completed MODELABILITY INDEX result may
be returned without another calculation. The generic status endpoint reads the
persisted job record.

PubChem uses a separate worker process and dedicated routes. HARMONSMILE and
MODELABILITY INDEX use registered scientific-job execution in the active
Streamlit or FastAPI process. They share a public status schema and SQLite
persistence, but not an execution engine.

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
requeues eligible HARMONSMILE jobs, starts their executors, and returns
recovered HARMONSMILE job snapshots with `table_name`. It does not create a
distributed worker service.

## Local and API-client semantics

`clients.backend_gateway.BackendGateway` provides Streamlit with a common
interface for supported operations:

- when `CHEMVAULT_API_URL` is unset, the local backend calls application and
  service functions directly;
- when `CHEMVAULT_API_URL` is set, the HTTP backend calls the corresponding
  FastAPI endpoints.

API-client mode covers only operations implemented by the HTTP backend; it does
not make all local Streamlit functionality available over HTTP. See the
[Usage guide](usage.md) for configuration and launch instructions.

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

`GET /databases/{database_id}/tables` returns user-visible table names.
`GET /databases/{database_id}/operations` returns recorded processing
operations, newest first, including operation type, source and target table,
source columns, timestamp, status, and details when available. Processing
history records application operations; it is distinct from the provenance of
the source data.

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

This response is an illustrative schema example, not the output of a specific
dataset. The `read_only` field describes the HTTP table interface; it does not
mean that the underlying SQLite database cannot be changed through other
supported workflows. Target identity and consolidation summaries are returned
only when supported by persisted metadata. Their presence documents provenance
or processing results, not independent source-data completeness.

`GET /metrics` returns `row_count` and `group_count`; the optional
`group_column` parameter selects a valid grouping column. These counts refer
to database records or groups, not necessarily to distinct compounds, bioassays,
or molecular structures. `GET /preview` accepts repeated `columns` parameters
and returns at most ten records.

## Structure consolidation

```http
POST /databases/example/tables/activity_subset_IC50/structure-consolidation
```

The endpoint creates an eligible ACTIVITY LABELS structure-level table and
returns its generated name and a summary of source activity records, eligible
records, distinct molecular structures, consolidated structures, class counts,
exclusions, contributing observations, and quantitative-reference selection.
The response fields use different populations and denominators; these counts
must not be interpreted as interchangeable. Their exact names are defined by
`StructureConsolidationResponse` in `api/schemas.py`. Missing resources return
404; scientific ineligibility returns 422.

## Downloads

### Table CSV

```http
GET /databases/example/tables/main/export?columns=CID&columns=SMILES
```

The response is UTF-8 `text/csv` and includes all records for the requested
columns in request order. Omitting `columns` exports the complete table.
Unknown columns return 422. This endpoint does not apply the UI's filtered
subgroup or Structured activity filters.

### Fingerprint artifact

```http
GET /databases/example/tables/activity_subset_IC50_structure_consolidated/modelability-index/fingerprints/export?analysis_identity=<identity>&fingerprint_type=morgan
```

The response is `application/octet-stream` with the backend-generated `.npz`
filename. The endpoint retrieves an existing fingerprint artifact only after
validating the source table, analysis identity, and fingerprint type. It does
not generate new fingerprints. A stale identity or a missing, corrupt, or
incompatible artifact returns 409.

The other three MODELABILITY INDEX downloads—nearest-neighbor CSV, Murcko
relationships CSV, and analysis JSON—are available from the Streamlit result
card; they are not separate HTTP endpoints in this API.

## Current boundary

The API does not create or delete databases, expose general table mutation,
or operate as a distributed worker platform. Filtered subgroup export and
Structured activity CSV export remain Streamlit workflows. The supported
PubChem jobs, scientific jobs, structure consolidation, and fingerprint
artifact retrieval are explicit exceptions to a read-oriented HTTP interface.

The `api/`, `application/`, and `services/` layers remain independent of
Streamlit and `st.session_state`.
