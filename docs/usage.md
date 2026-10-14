# Usage

## Prerequisites

CHEMVAULT v0.14.7 requires Python 3.12. Git and Conda are recommended for a
source installation. The compatible HARMONSMILE and MOLRAPTOR releases are
declared as project dependencies and do not need to be installed separately.

## Installation

Version 0.14.7 is under development on `dev/v0.14.7` and is not published to
PyPI. Install it from the selected source checkout:

```bash
git clone https://github.com/NanoBiostructuresRG-lab/chemvault.git
cd chemvault
git checkout dev/v0.14.7

conda create -n chemvault_env python=3.12
conda activate chemvault_env
python -m pip install .
```

The published GitHub release `v0.14.6` uses the installation procedure in that
release's
[tagged README](https://github.com/NanoBiostructuresRG-lab/chemvault/blob/v0.14.6/README.md).

## Starting the application

An installed source checkout provides the console command:

```bash
chemvault
```

The launcher preserves the caller's working directory and starts the packaged
Streamlit application with the active Python interpreter. Informational CLI
options do not start Streamlit:

```bash
chemvault --help
chemvault --version
```

For development directly from the repository root, run:

```bash
streamlit run app.py
```

The interface is normally available at `http://localhost:8501`.

## Execution modes

### Local mode

Local mode is selected when `CHEMVAULT_API_URL` is unset. Streamlit calls the
application and service layers in the same installation and accesses the
selected SQLite database locally.

```text
Streamlit UI -> application/services -> SQLite
```

This is the default mode for routine use.

### API-client mode

API-client mode routes the operations supported by the backend gateway through
FastAPI. Start the API from the same working directory as Streamlit:

```bash
python -m uvicorn api.main:app --reload
```

Then set the backend URL before starting the application.

=== "Windows PowerShell"

    ```powershell
    $env:CHEMVAULT_API_URL = "http://127.0.0.1:8000"
    streamlit run app.py
    ```

=== "macOS / Linux"

    ```bash
    export CHEMVAULT_API_URL="http://127.0.0.1:8000"
    streamlit run app.py
    ```

```text
Streamlit UI -> HTTP client -> FastAPI -> application/services -> SQLite
```

The HTTP path covers database inspection and export, UniProt target resolution,
PubChem jobs, scientific runtime activation, HARMONSMILE and MODELABILITY INDEX
jobs, structure consolidation, and fingerprint artifact export. Unsupported
table mutations remain local. If the configured backend is unavailable,
CHEMVAULT reports the transport error and does not silently switch to local
mode. See the [API Reference](api.md) for the exact endpoints.

## Storage and working-directory behavior

CHEMVAULT stores user databases as `SQL/<database_id>.db` relative to the
working directory from which the application is launched. This applies to both
the installed `chemvault` command and source-checkout execution. Launch from the
same workspace to reopen those databases later, or choose a different workspace
for an isolated run.

Scientific job state, table provenance, operation history, HARMONSMILE cache
records, and compatible fingerprint artifacts are persisted in the selected
SQLite database. They are not written into the installed package directory.

!!! warning "Database identity"

    Use a new database name when a scientifically independent run is required.
    Reopening a name deliberately reuses its persisted tables and job history.

## Constructing a dataset from CSV

1. Enter a value in **SQL Database name**.
2. Upload a CSV file in the Build card.
3. Inspect the imported table and its columns.
4. Use the Refine controls to select columns, filter rows, group records, or
   order a derived table.
5. Preserve a selection as a new table when needed.
6. Export the active table or selected columns as CSV.

CSV import constructs a SQLite table from the supplied records; it does not
claim PubChem target provenance. A row may describe a compound, molecular
structure, activity observation, or another user-defined entity depending on
the imported columns.

## Constructing a target-centered PubChem dataset

### Select one biological target

The **Select Target** dialog supports two input modes:

- **Gene symbol and organism** resolves exactly one reviewed UniProt entry from
  the supported organism catalog.
- **UniProt accession** accepts one direct accession independently of the gene
  resolver.

Confirm the resolved identity before launching the search. When available,
CHEMVAULT persists the input mode, UniProt accession, gene symbol, organism,
entry name, protein name, common name, and reviewed status as target provenance.

### Run the PubChem protein search

The PubChem search runs as a persisted job in a separate local process. The
progress dialog reports its stage, progress, message, and terminal state and
allows active searches to be cancelled. A successful build creates distinct
populations rather than collapsing them into one ambiguous row set:

- `main` contains the compound-centered molecular records;
- `compound_assays` records CID-to-AID associations and assay context;
- `compound_activities` contains structured activity observations.

The build also records the same-run `(protein, AID)` source enumeration used for
AID-population correspondence. That correspondence evaluates persisted assay
identities and explicit row-level target exclusions; it is not a certification
that every source CID, property, or activity row is complete.

Completed jobs are finalized once to register the base table and operation
history. Existing target databases can use **Repair activity records** to
retrieve activity for persisted assay-compound relationships without replacing
previously stored records.

## Structured activity selection

Structured PubChem activity remains in `compound_activities`, separate from the
compound-centered `main` table. The Structured activity workflow can filter by
activity type, unit, PubChem outcome, AID, and a compatible numeric range.

The on-screen preview may be limited for responsiveness, while the structured
activity export represents the complete filtered population. A selected subset
provides the traceable input for later label consolidation.

## SMILES HARMONIZED

The **SMILES HARMONIZED** workflow sends a valid CID column to the external
[HARMONSMILE](https://pypi.org/project/harmonsmile/) engine, persists chunked
results, and merges the molecular fields into a derived table. Important fields
include:

| Field | Meaning |
|---|---|
| `PubChem_CID` | Canonical PubChem compound identifier used for acquisition. |
| `PubChem_Acquisition_Status` | Machine-readable outcome of the PubChem molecular-property acquisition stage. |
| `PubChem_Acquisition_Message` | Optional acquisition diagnostic; it is not the decision key. |
| `SMILES_RDKit` | RDKit-derived representation produced during processing. |
| `SMILES_Harmonized` | Harmonized representation used as the downstream structure key. |
| `SMILES_Harmonization_Status` | Molecular harmonization outcome. |
| `SMILES_Harmonization_Message` | Record-level harmonization diagnostic. |
| `InChI`, `InChIKey` | Additional identifiers when returned by the workflow. |

### Acquisition status

| Status | Meaning |
|---|---|
| `ok` | PubChem returned a usable property record. Individual requested properties can still be missing. |
| `failed` | No usable property record was obtained within the attempt budget for that invocation. |
| `not_attempted` | No PubChem request was made because the CID was missing or invalid after local handling. |

Only records with acquisition status `ok` are reusable successful acquisition
cache entries. Older cache records without acquisition provenance are not
silently treated as successful and remain eligible for reacquisition.

### Harmonization status

Known values are `ok`, `ok_with_warnings`, `unsupported`, and `failed`.
Acquisition and harmonization are separate stages, so this is a valid result:

```text
PubChem_Acquisition_Status = ok
SMILES_Harmonization_Status = failed
```

It means PubChem returned a usable molecular record but its structure could not
be harmonized. CHEMVAULT preserves both status families and their messages
through cache reuse and table merge.

## ACTIVITY LABELS and structure consolidation

**ACTIVITY LABELS** operates on an eligible, harmonized Structured activity
table. It preserves PubChem `Active` and `Inactive` outcomes rather than
deriving thresholds such as pEC50 or pKi. Records are grouped by
`SMILES_Harmonized`:

- agreeing observations yield one structure-level record;
- conflicting binary outcomes are excluded traceably;
- unsupported or unusable populations remain represented in summary counts;
- contributing AIDs and reference identifiers are retained;
- the source table remains unchanged.

The output name follows
`activity_subset_<activity>_structure_consolidated`, with a numeric suffix when
necessary.

## MODELABILITY INDEX

The **MODELABILITY INDEX** measures local agreement between the preserved binary
labels and molecular similarity. For every eligible structure, CHEMVAULT finds
its nearest neighbor by Tanimoto similarity and calculates same-class
concordance separately for Active and Inactive structures. The reported index
is their macro average.

A value nearer to 1 indicates stronger local label agreement in the selected
fingerprint space. It is a dataset diagnostic, not evidence that a predictive
model has been trained or a guarantee of predictive performance.

MOLRAPTOR generates the requested fingerprint representation. CHEMVAULT
consumes that output, persists compatible artifacts, and calculates the
concordance metrics. The application also reports atom- and bond-aware
Bemis-Murcko scaffold context, including acyclic coverage and same- versus
different-scaffold nearest-neighbor behavior, without altering the index.

## Exports and persisted results

Available outputs depend on the active workflow and include:

- UTF-8 CSV for complete tables or selected table columns;
- complete CSV for a filtered Structured activity population;
- nearest-neighbor CSV with molecular comparisons and analysis identity;
- JSON analysis report with summary, provenance, diagnostics, and Murcko
  structural context;
- fingerprint `.npz` containing the ordered structures, labels, matrix, and
  canonical provenance required by the export contract.

Completed MODELABILITY INDEX results and compatible fingerprint artifacts can
be restored for the same database, source table, analysis identity, and
fingerprint profile. Different fingerprint representations remain distinct.

## Next steps

- Use the [API Reference](api.md) for HTTP paths, payloads, lifecycle states,
  and gateway behavior.
- Review the [Changelog](changelog.md) for the authoritative development
  history.
