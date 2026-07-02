# Changelog

All notable changes to ChemVault will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
