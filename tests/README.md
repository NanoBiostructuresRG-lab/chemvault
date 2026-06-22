# Test Suite Inventory

ChemVault keeps two kinds of files under `tests/`:

- Automated pytest tests: files named `test_*.py`. These are the supported
  suite and must run with one command: `python -m pytest`.
- Legacy/manual scripts and fixtures: exploratory files, Streamlit prototypes,
  external API scripts, local data fixtures, and generated comparison outputs.
  These are not collected by pytest.

## Automated Pytest Suite

| File | Responsibility |
| --- | --- |
| `test_app_characterization.py` | Characterizes SQL query-building behavior extracted from `app.py`. |
| `test_builders_service.py` | Covers CSV and protein database build service behavior. |
| `test_curation_service.py` | Covers curation wrappers, CID header validation, and dataframe merge behavior. |
| `test_database_service.py` | Covers database row counting, table/header discovery, and selected-header synchronization. |
| `test_db_audit.py` | Covers the database audit CLI helpers. |
| `test_export_service.py` | Covers full-table and filtered subgroup CSV export behavior. |
| `test_selection_service.py` | Covers active selected headers, preview table generation, and selected-column retrieval. |
| `test_session_state.py` | Covers Streamlit session-state initialization defaults. |
| `test_sql_utils.py` | Covers SQLite identifier quoting, table existence, table listing, and main-table creation. |
| `test_state_keys.py` | Protects existing Streamlit session-state key string values. |

## Legacy / Manual Files

| File | Responsibility | Suite status |
| --- | --- | --- |
| `appTest1.py` | Streamlit prototype for CSV loading/editing. | Manual only. |
| `appTest2.py` | Streamlit prototype for real-time PubChem CID loading. | Manual only. |
| `coconut.py` | Exploratory COCONUT API request script. | Manual only; should not run in CI. |
| `comparador.py` | Local JSON comparison script that writes `comparador_result.json`. | Manual only. |
| `convert_SDF_to_CSV.py` | Local RDKit SDF-to-CSV conversion helper. | Manual only. |
| `harmonsmile_test.py` | Ad hoc HARMONSMILE smoke script requiring `examples/example_pubchem.csv`. | Manual only; not a pytest test. |
| `requestCIDs_por_AIDs` | Manual PubChem API harvesting script. | Manual only. |
| `example.db`, `example2.db` | SQLite fixtures/examples. | Data only. |
| `P34971_aids.json`, `P34971_cids.json`, `pubchem_protacxn_P34971_bioactivity_protein(2).json` | PubChem fixture or exploratory output data. | Data only. |
| `comparador_result.json` | Generated comparison output. | Data only. |

## Removed Redundant File

`sqlite3_test.py` was removed from `tests/` because it was redundant for the
automated suite. Its behavior is already covered more safely by:

- `test_sql_utils.py`
- `test_database_service.py`
- `test_db_audit.py`

Unlike those tests, the removed script performed database writes at import time
and depended on a relative path outside the pytest temp-directory pattern.
