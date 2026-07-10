# Changelog

All notable changes to ChemVault will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v0.10.2] - 2026-07-09

### Changed
- Updated CHEMVAULT to `harmonsmile==0.3.2`.
- Removed the v0.10.1 CSV empty-delimiter workaround for HARMONSMILE input.
- Restored simple CSV-based HARMONSMILE input using a safe `CID` column.
- Relied on HARMONSMILE 0.3.2 deterministic CSV loading, robust CID aliases, and canonical `PubChem_CID` output.
- Updated HARMONSMILE job-contract documentation and focused integration tests for the 0.3.2 contract.

### Notes
- This release does not change the scientific backend job contract.
- CHAMANP backend execution and PubChem API execution/cancellation remain outside this release.

### Validation
- Full suite passed on `main`: `346 passed`.
- HARMONSMILE 0.3.2 was verified in `chemvault_env`.
- Architectural grep over `api`, `application`, and `services` for Streamlit/session-state references returned no matches.

---

## [v0.10.1] - 2026-07-09

### Fixed
- Fixed a HARMONSMILE 0.3.1 input-column regression where the temporary one-column CSV header `PubChem CID` could be parsed as separate `PubChem` and `CID` columns.
- Preserved CSV as the temporary HARMONSMILE interchange format while using a safe `CID` input column and normalizing returned CID data back to `PubChem_CID`.
- Ensured HARMONSMILE execution works from Streamlit when the selected source column is named `CID`.

### Validation
- Full suite passed on `main`: `346 passed`.
- Architectural grep over `api`, `application`, and `services` for Streamlit/session-state references returned no matches.
- Manual Streamlit validation passed on `Dev10_P34971` / `harmin`: HARMONSMILE ran and created the expected output columns.

---

## [v0.10.0] - 2026-07-09

### Added
- Added a generic scientific backend job boundary for reusable workflow execution.
- Added `application/scientific_jobs.py` to register, create, execute, and inspect scientific jobs by job type.
- Added generic backend gateway and API-client methods for launching and querying scientific jobs.
- Added HARMONSMILE 0.3.1 integration coverage, including status/message/result column handling.

### Changed
- Consolidated the v0.9.0 HARMONSMILE backend job path into a reusable scientific job contract.
- Made `GET /databases/{database_id}/jobs/{job_id}` job-type-neutral instead of depending on HARMONSMILE-specific status lookup.
- Aligned local and API HARMONSMILE execution around the same launch, poll, and terminal-status lifecycle.
- Separated backend transport failures from persisted workflow failures.
- Replaced PubChem-specific stale-job wording with generic backend-job wording.
- Updated CHEMVAULT’s HARMONSMILE dependency from `harmonsmile==0.2.4` to `harmonsmile==0.3.1`.
- Updated API and job-contract documentation to describe the current scientific backend job contract.

### Notes
- HARMONSMILE remains the only scientific workflow exposed through the backend job contract in this release.
- CHAMANP backend execution, PubChem API execution, PubChem cancellation, remote workers, task queues, Docker, auth, deployment, and frontend replacement remain outside this release.
- `ARCHITECTURE.md` remains an internal untracked file and is not part of this release commit.

### Validation
- Full suite passed on `main`: `346 passed`.
- Architectural grep over `api`, `application`, and `services` for Streamlit/session-state references returned no matches.
- HARMONSMILE 0.3.1 was verified in `chemvault_env`.

---

## [v0.9.0] - 2026-07-06

### Added
- Added HARMONSMILE backend job execution through the backend gateway.
- Added `POST /databases/{database_id}/jobs/harmonsmile` to launch HARMONSMILE backend jobs.
- Added `GET /databases/{database_id}/jobs/{job_id}` to inspect HARMONSMILE job status.
- Added a minimal backend job runtime for asynchronous HARMONSMILE API execution.
- Added Streamlit polling for HARMONSMILE job progress and terminal status.

### Changed
- Extended the backend gateway from read-only/export coverage to real scientific workflow execution.
- Routed Streamlit HARMONSMILE execution through the backend gateway.
- Preserved local mode as the default execution path.
- Preserved API mode without silent local fallback when `CHEMVAULT_API_URL` is configured.
- Replaced long blocking HARMONSMILE API execution with quick launch plus status polling.
- Improved HARMONSMILE UI execution state handling for success, failure, backend connection loss, and stale workflow state.

### Notes
- This release is the first backend execution milestone for CHEMVAULT.
- Scope is limited to HARMONSMILE execution.
- PubChem execution, PubChem cancellation, CHAMANP execution, remote workers, auth, Docker, deployment, and frontend replacement remain outside this release.
- Level 2 is advanced but not yet complete.

### Validation
- Full suite passed on `main`: `344 passed`.
- Manual API-mode validation passed for normal HARMONSMILE execution and FastAPI shutdown during polling.

---

## [v0.8.0] - 2026-07-03

### Added
- Added read-only operation history/provenance access through the backend gateway.
- Added `GET /databases/{database_id}/operations` for read-only operation history retrieval.
- Added current table CSV export through the backend gateway.
- Added `GET /databases/{database_id}/tables/{table_name}/export?columns=...` for CSV export of the current table.
- Added a typed backend job status contract for future long-running backend execution.

### Changed
- Extended Streamlit backend-gateway coverage to include operation history/provenance and current table CSV export.
- Clarified README usage for default local mode and optional API-client mode.
- Documented how `CHEMVAULT_API_URL` selects API-client mode and how to return to local mode.
- Updated API documentation to describe the new operation-history and CSV-export endpoints.
- Documented that job runtime endpoints, workers, cancellation endpoints, and execution migration remain deferred.

### Notes
- This release further consolidates the Streamlit-to-backend boundary for read-only operations and CSV export.
- Scope remains limited to read-only inspection/export and backend contract preparation.
- PubChem execution, HARMONSMILE execution, CHAMANP execution, structured activity export, subgroup export, runtime job endpoints, workers, cancellation mutation endpoints, curation writes, table mutations, auth, deployment, Docker, and frontend replacement remain outside this release.
- The typed job status contract prepares future backend job execution without changing current runtime behavior.

### Validation
- Full suite passed on `main`: `325 passed in 22.53s`.

---

## [v0.7.0] - 2026-07-03

### Added
- Added `ReadOnlyBackendGateway` as a unified backend boundary for Streamlit read-only database exploration.
- Added local and HTTP backend paths behind the gateway:
  `Streamlit UI → ReadOnlyBackendGateway → local application/services`
  or, when `CHEMVAULT_API_URL` is configured:
  `Streamlit UI → ReadOnlyBackendGateway → HTTP client → FastAPI → application/services`.
- Added active table schema inspection through the read-only backend gateway.
- Extended the existing table metadata API response with schema information.

### Changed
* Routed Streamlit read-only table listing, metadata, metrics, preview, and active table schema inspection through the backend gateway.
* Concentrated runtime `CHEMVAULT_API_URL` backend selection inside `clients/backend_gateway.py`.
* Preserved local mode as the default when `CHEMVAULT_API_URL` is not configured.
* Preserved visible API-mode failures without silent local fallback when `CHEMVAULT_API_URL` is configured.
* Updated API documentation to describe the unified read-only backend boundary.

### Notes
- Scope remains read-only.
- PubChem execution, HARMONSMILE execution, CHAMANP execution, jobs/workers, curation writes, table mutations, auth, deployment, Docker, and frontend replacement remain outside this release.
- This release does not complete the full Streamlit-to-FastAPI migration, but establishes the backend boundary required to continue that migration without scattered UI-level backend decisions.

### Validation
- Full suite passed on `main`: `300 passed in 22.60s`.

---

## [v0.6.0] - 2026-07-03

### Added
- Expanded the Streamlit API-client mode for read-only database exploration when `CHEMVAULT_API_URL` is configured.
- Routed database table listing through FastAPI `GET /databases/{database_id}/tables`.
- Routed table metadata and headers through FastAPI `GET /databases/{database_id}/tables/{table_name}/metadata`.
- Routed database row/group metrics through FastAPI `GET /databases/{database_id}/tables/{table_name}/metrics`.
- Kept selected columns preview routed through FastAPI `GET /databases/{database_id}/tables/{table_name}/preview`.

### Changed
- Streamlit now has a broader read-only API-client path:
  `Streamlit → API client → FastAPI → application/services`.
- Local Streamlit behavior remains the default when `CHEMVAULT_API_URL` is not configured.
- API-mode failures are surfaced visibly instead of silently falling back when API mode is explicitly enabled.
- Updated API documentation to describe the expanded read-only coverage.

### Notes
- Scope remains read-only.
- PubChem execution, HARMONSMILE execution, jobs/workers, curation writes, exports, table mutations, auth, deployment, and frontend replacement remain outside this release.
- This release advances the Streamlit-to-FastAPI decoupling path, but FastAPI is not yet a complete backend replacement.

---

## [0.5.0] - 2026-07-02

### Added
- Added an internal FastAPI read-only client.
- Added an opt-in Streamlit API-client pilot using `CHEMVAULT_API_URL`.

### Changed
- Routed **Columns → Selected columns preview** through the FastAPI client when `CHEMVAULT_API_URL` is configured.
- Preserved default local Streamlit behavior when `CHEMVAULT_API_URL` is not set.
- Documented the dual FastAPI + Streamlit API-client mode in `docs/api.md`.
- Clarified the README release checkout and existing-clone update workflow.

### Notes
- Scope remains limited: no PubChem execution through FastAPI, HARMONSMILE execution through FastAPI, workers, backend runner, export endpoints, or table mutation.

---

## [0.4.1] - 2026-07-02

### Added
- Added OpenAPI contract tests for the read-only API surface.
- Added `uvicorn==0.49.0` as the ASGI server dependency for local FastAPI execution.
- Added read-only table metadata endpoint `GET /databases/{database_id}/tables/{table_name}/metadata`.

### Changed
- Documented FastAPI read-only API local execution.
- Documented current API endpoints, limitations, and the metadata endpoint.

### Notes
- Scope remains read-only: no PubChem execution, workers, backend runner, or table mutation.

---

## [0.4.0] - 2026-07-01

### Added
- Added a minimal read-only FastAPI interface under `api/`.
- Added `GET /health`.
- Added `GET /databases/{database_id}/tables`.
- Added `GET /databases/{database_id}/tables/{table_name}/metrics`.
- Added `GET /databases/{database_id}/tables/{table_name}/preview`.
- Added FastAPI `TestClient` coverage for health, table listing, metrics, preview, missing databases, missing tables, and invalid column requests.

### Changed
- Extended `application/database_use_cases.py` with backend/API-ready read-only helpers for database table listing, table state validation, table metrics, and invalid-column handling.
- Added FastAPI/runtime test dependencies to `requirements.txt`.

### Notes
- FastAPI consumes `application/`; it does not depend on Streamlit or `st.session_state`.
- Streamlit remains the local UI.
- PubChem API endpoints, authentication, Docker, deployment, and remote workers remain intentionally out of scope for this checkpoint.

---
## [0.3.0] - 2026-07-01

### Added
- Added backend-ready `application/` use-case layer.
- Added database use cases for database creation, opening, refresh, and metrics.
- Added table use cases for active column selection, previews, selected-row loading, and CSV export.
- Added curation use cases for CID validation, HARMONSMILE, CHAMANP, and curated-data merge operations.

### Changed
- Updated Streamlit UI modules to delegate selected operations through `application/`.
- Preserved Streamlit as the UI layer while keeping backend-ready orchestration outside the UI.

### Validation
- Full grep over `application/` and `services/` for Streamlit/session_state references returns no output.
- Full test suite passed: 249 tests.
- Manual Streamlit smoke test passed.

---

## [0.2.0] - 2026-07-01

### Changed
- Decoupled service-layer logic from Streamlit session state.
- Refactored export, selection, curation, builders, and database services to receive explicit inputs and return explicit results/state.
- Moved Streamlit session-state mutation, toast messages, and UI feedback responsibility to the UI layer.
- Added DatabaseState to represent database-related UI state transitions without mutating Streamlit state inside services.

### Validation
- Full grep over `services/` for Streamlit/session_state references returns no output.
- Full test suite passed: 235 tests.
- Manual Streamlit smoke test passed with existing and new databases.

---

## [0.1.0] - 2026-07-01

First formal tagged release of CHEMVAULT as a local Streamlit + SQLite application.

### Added
- Streamlit-based local interface for building, refining, curating, inspecting, and exporting molecular SQLite datasets.
- CSV upload and CSV export workflows.
- PubChem protein-target search using UniProt accessions and BioAssay-derived CIDs.
- Persistent local PubChem worker jobs with a progress modal, job status, stage, progress, messages, and safe cancellation.
- SQLite job persistence for PubChem searches.
- `main`, `compound_assays`, and `compound_activities` tables for molecule, assay-link, and structured activity data.
- HARMONSMILE integration for CID-based molecular property and SMILES enrichment.
- CHAMANP workflow integration.
- Structured activity filtering and CSV export.
- Table Manager for inspecting tables, schema, provenance, and operation history, with derived-table deletion.
- Local stable validation checklist in the README.

### Changed
- PubChem protein searches now use the local worker path instead of direct synchronous UI execution.
- PubChem job lifecycle and launch logic are routed through a reusable service layer.
- PubChem job state is exposed through a stable job-view contract instead of UI code depending on internal job-store records.
- SQLite connection handling now includes a Streamlit-independent database core for backend services.
- README documentation reflects the current local stable app and English UI labels.

### Fixed
- Stale PubChem worker jobs are detected and marked failed.
- Locked PubChem job databases are treated as transient while the worker finishes writing.
- Cancelled PubChem jobs are not registered as completed.
- PubChem cancellation is checked during compound-name retry waits.
- Release-noise debug prints were removed from normal Streamlit flows.

### Validation
- Full suite passed with `python -m pytest -q -p no:cacheprovider`.
- Integration validation passed for:
    - `P34971` complete PubChem smoke test.
    - `P32245` cancellation smoke test.
    - Opening existing SQLite databases.
    - CSV export.
    - Structured activity filtering and export.
