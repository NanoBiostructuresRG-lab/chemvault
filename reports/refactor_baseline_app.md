# App Refactor Baseline

Date: 2026-06-21

This baseline freezes the current operational expectations before refactoring
`app.py`. The goal is to prepare extraction work without changing chemistry,
SQL behavior, Streamlit session keys, or user-facing workflows.

## Current Shape

`app.py` is a monolithic Streamlit file. It currently contains:

- page configuration and CSS injection
- Streamlit session state defaults
- sidebar UI for Build, Refine, Curate, and Export
- main page UI cards
- SQLite helpers and SQL query construction
- CSV database creation
- PubChem/protein database creation
- table preview and selected-column extraction
- export logic
- HARMONSMILE orchestration
- CHAMANP orchestration
- column type maintenance UI and SQL

Approximate size: 860 lines.

## Baseline Diagnostics

Commands run:

```powershell
python -m py_compile app.py
python -m py_compile modules\obtener_CIDs_Pubchem.py modules\use_harmonsmile.py modules\use_chamanp.py tools\db_audit.py
python -m pytest tests/test_db_audit.py -q
python tools\db_audit.py inspect SQL\harmonsmile_test_01.db
python -m pytest -q
```

Results:

- `app.py` compiles successfully.
- Chemistry integration modules and `tools\db_audit.py` compile successfully.
- `tests/test_db_audit.py` passes: 6 passed.
- `SQL\harmonsmile_test_01.db` inspect result:
  - `Nueva_tabla`: 102 rows
  - `main`: 102 rows
  - `sqlite_sequence`: 1 row
- Full `pytest` is not currently clean because some files in `tests/` behave
  as exploratory scripts during test collection:
  - `tests/harmonsmile_test.py` expects `examples/example_pubchem.csv`.
  - `tests/sqlite3_test.py` attempts to open `../SQL/example.db` and fails.

## Critical Workflows To Preserve

Manual behavior to preserve during refactor:

1. Load or create SQL database.
2. Load existing database from the `SQL/` folder.
3. Build database from uploaded CSV.
4. Build database from protein targets using PubChem CID retrieval.
5. Keep `database_id`, `current_table`, `headers`, `all_tables`, and
   `selected_headers` synchronized.
6. Select columns in the Columns card.
7. Preview selected columns.
8. Create derived tables from selected columns in Refine.
9. Preserve GROUP BY, WHERE, and ORDER BY query behavior.
10. Run HARMONSMILE only with one valid CID column.
11. Merge HARMONSMILE output back into the active table by key.
12. Run CHAMANP with identifier, canonical_smiles, and collections selections.
13. Download CHAMANP artifacts.
14. Export the current table as CSV.
15. Export filtered subgroups as CSV.
16. Show table schema and allow column type changes.

## Non-Negotiable Refactor Constraints

- Do not change HARMONSMILE internals.
- Do not change CHAMANP internals.
- Do not change SQL semantics while extracting modules.
- Do not rename existing `st.session_state` keys.
- Do not change exported CSV behavior.
- Do not change active database/table synchronization behavior.
- Prefer small extractions with diagnostics after every step.

## Recommended Next Step

Create characterization tests for pure and high-risk functions before moving
them:

- `quote_identifier`
- `is_valid_table_name`
- `is_cid_header`
- `construir_linea_query`
- row counting helpers
- export query helpers
- selected-column helpers

## Characterization Tests Added

Added `tests/test_app_characterization.py` to capture current behavior without
importing the full Streamlit app. The tests load selected function definitions
from `app.py` with `ast`, avoiding execution of the Streamlit UI at import time.

Covered behavior:

- `quote_identifier`
- `is_valid_table_name`
- `is_cid_header`
- `construir_linea_query`
  - no filter
  - `GROUP BY`
  - `WHERE`
  - `ORDER BY`
  - stale selected headers
  - missing selected columns
  - invalid group-by column

Validation after adding tests:

```powershell
python -m pytest tests/test_app_characterization.py -q
python -m pytest tests/test_db_audit.py -q
python -m py_compile app.py
```

Results:

- `tests/test_app_characterization.py`: 23 passed.
- `tests/test_db_audit.py`: 6 passed.
- `app.py` compiles successfully.

## Session-State Key Constants Added

Added `state_keys.py` as a central inventory of Streamlit session-state keys.
This does not change app behavior yet; it preserves the existing string values
and prepares future extractions to avoid typo-prone key usage.

Added `tests/test_state_keys.py` to verify:

- all listed session-state keys are unique
- core session-state key strings are preserved
- widget-generated session-state key strings are preserved

Validation after adding constants:

```powershell
python -m pytest tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py
```

## Session-State Initialization Extracted

Added `ui/session_state.py` with `initialize_session_state(session_state,
verify_directories_callback)`.

This extraction preserves behavior from `app.py`:

- `verify_directories_callback()` runs only when `database_id` is missing.
- Existing session-state values are not overwritten.
- Existing key strings remain unchanged.
- `selecting_harmonsmile` and `selecting_chamanp` are initialized with the same
  previous empty-string defaults.

Added `tests/test_session_state.py` to verify defaults, preservation of existing
values, and independent list defaults.

Validation after extraction:

```powershell
python -m pytest tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py
```

## SQL Utilities Extracted

Added `services/sql_utils.py` and moved low-risk SQL helper functions out of
`app.py`:

- `quote_identifier`
- `is_valid_table_name`
- `table_exists`
- `get_tables_from_connection`
- `ensure_main_table`

`app.py` now imports these helpers from `services.sql_utils`.

Added `tests/test_sql_utils.py` to protect the extracted SQLite helpers with
temporary in-memory databases. Updated `tests/test_app_characterization.py` so
`construir_linea_query` remains characterized while using the extracted helper
functions.

Validation after extraction:

```powershell
python -m pytest tests/test_sql_utils.py tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py services/sql_utils.py
```

## Database Service Extracted

Added `services/database.py` and moved database/session-state orchestration out
of `app.py`:

- `get_connection`
- `count_rows`
- `count_rows_group_by`
- `set_database_id`
- `load_existing_database`
- `get_tables`
- `update_headers`

The extracted service intentionally preserves Streamlit callback-compatible
signatures and current `st.session_state` key strings. Chemistry integrations,
SQL query semantics, and export behavior were not changed.

Added `tests/test_database_service.py` to protect:

- empty-table row counts
- active-table row counts
- group counting
- header/table synchronization
- stale selected-header cleanup

Validation after extraction:

```powershell
python -m pytest tests/test_database_service.py tests/test_sql_utils.py tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py services/sql_utils.py services/database.py
```

Results:

- 42 passed.
- All compiled files passed `py_compile`.

## Export Service Extracted

Added `services/export.py` and moved export helpers out of `app.py`:

- `export_table`
- `export_table_by_sub_grupo`

The function names and signatures remain the same so Streamlit download buttons
keep their current behavior. The implementation still uses the active database,
active table, selected headers, and filtered subgroup behavior from the
monolithic app.

Added `tests/test_export_service.py` to protect:

- empty CSV output with no active database/table
- full-table export when no columns are selected
- selected-column export while ignoring stale selections
- filtered subgroup export
- invalid subgroup filter column handling

Validation after extraction:

```powershell
python -m pytest tests/test_export_service.py tests/test_database_service.py tests/test_sql_utils.py tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py services/sql_utils.py services/database.py services/export.py
```

## Selection and Preview Service Extracted

Added `services/selection.py` and moved selection/preview helpers out of
`app.py`:

- `get_active_selected_headers`
- `sync_selected_headers`
- `build_preview_table`
- `get_selected_columns`

The function names remain imported into `app.py`, preserving existing callers in
Refine, Curate, Export-adjacent UI, and the main Columns card.

Added `tests/test_selection_service.py` to protect:

- stale selected-column cleanup
- selected-header synchronization
- empty preview behavior
- selected-column preview
- full selected-column retrieval for downstream chemistry workflows

Validation after extraction:

```powershell
python -m pytest tests/test_selection_service.py tests/test_export_service.py tests/test_database_service.py tests/test_sql_utils.py tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py services/sql_utils.py services/database.py services/export.py services/selection.py
```

## Data Builders Extracted

Added `services/builders.py` and moved data-building helpers out of `app.py`:

- `build_from_csv`
- `build_from_proteins`

The function names and signatures remain the same for existing UI callers.
`build_from_csv` preserves current SQLite table creation and CSV column
normalization behavior. `build_from_proteins` still delegates to
`obtener_CIDs_Pubchem` without changing PubChem/CID retrieval internals.

Added `tests/test_builders_service.py` to protect:

- CSV import into `main` when no current table is set
- CSV import into an existing active table name
- protein builder delegation to `obtener_CIDs_Pubchem` without making network
  calls

Validation after extraction:

```powershell
python -m pytest tests/test_builders_service.py tests/test_selection_service.py tests/test_export_service.py tests/test_database_service.py tests/test_sql_utils.py tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py services/sql_utils.py services/database.py services/export.py services/selection.py services/builders.py
```

## Curation Validation Extracted

Added `services/curation.py` and moved lightweight chemistry validation out of
`app.py`:

- `is_cid_header`

This step does not change HARMONSMILE or CHAMANP internals. It only relocates
the CID-header validation used before running HARMONSMILE.

Added `tests/test_curation_service.py` to protect accepted CID header variants
and rejected non-CID columns.

Validation after extraction:

```powershell
python -m pytest tests/test_curation_service.py tests/test_builders_service.py tests/test_selection_service.py tests/test_export_service.py tests/test_database_service.py tests/test_sql_utils.py tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py services/sql_utils.py services/database.py services/export.py services/selection.py services/builders.py services/curation.py
```

## Curation Workflow Wrappers Added

Added workflow wrappers in `services/curation.py`:

- `run_harmonsmile(selected_columns_df)`
- `run_chamanp(selected_columns_df, identifier_col, smiles_col, collections_col)`

`app.py` now calls these wrappers instead of importing HARMONSMILE/CHAMANP
helpers directly. The wrappers delegate to the same underlying functions:

- `modules.use_harmonsmile.use_PubchemIngest`
- `modules.use_chamanp.use_chamanp`

No HARMONSMILE or CHAMANP internals were changed.

Added tests in `tests/test_curation_service.py` to verify delegation without
running real HARMONSMILE or CHAMANP work.

## Sidebar Build Card Extracted

Added `ui/sidebar.py` with:

- `render_build_card(select_proteins_callback)`

`app.py` now delegates only the Build card rendering to this helper while
keeping the rest of the sidebar in place. The callback for protein selection is
passed in from `app.py` to avoid circular imports with the Streamlit dialog.

The Build card behavior remains unchanged:

- "Search Proteins" opens the existing protein dialog callback.
- CSV upload locks the database input, derives the database name from the file,
  sets the active table to `main`, calls `build_from_csv`, refreshes headers,
  and reruns Streamlit.

## Sidebar Refine Card Extracted

Added `render_refine_card(clear_preview_callback, build_query_callback)` to
`ui/sidebar.py`.

`app.py` now delegates Refine card rendering while keeping SQL query
construction in `app.py` for this step. The query builder is passed as a
callback to avoid changing SQL semantics during the UI extraction.

The Refine card behavior remains unchanged:

- new table name input
- filter selector and filter-specific controls
- SQL preview rendering
- create-table action
- duplicate-table validation
- active table update
- selected-header reset
- success message handling

## Curation Merge Extracted

Moved `agregar_df_por_pk` from `app.py` to `services/curation.py`.

The function name and signature remain unchanged for the HARMONSMILE caller.
The SQL flow was preserved:

- identify update columns excluding the foreign key
- add missing columns to the active table
- write `_temp_updates`
- update matching rows by key
- drop `_temp_updates`
- commit on success
- rollback and return `False` on error

Added tests in `tests/test_curation_service.py` for:

- adding new columns and updating matching rows
- preserving non-matching rows
- updating existing columns without duplicate column creation
- returning `False` when there are no update columns
- rollback/error behavior

Validation after extraction:

```powershell
python -m pytest tests/test_curation_service.py tests/test_builders_service.py tests/test_selection_service.py tests/test_export_service.py tests/test_database_service.py tests/test_sql_utils.py tests/test_session_state.py tests/test_state_keys.py tests/test_app_characterization.py tests/test_db_audit.py -q
python -m py_compile app.py state_keys.py ui/session_state.py services/sql_utils.py services/database.py services/export.py services/selection.py services/builders.py services/curation.py
```
