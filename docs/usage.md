# Usage

## Requirements

Use Python 3.12, the supported release environment. A virtual environment is
recommended to isolate dependencies. Git and Conda are not required for a PyPI
installation. Compatible versions of HARMONSMILE and MOLRAPTOR are installed as
package dependencies.

## Installation

Install CHEMVAULT from [PyPI](https://pypi.org/project/ChemVault/):

```bash
python -m pip install chemvault
```

To upgrade an existing installation:

```bash
python -m pip install --upgrade chemvault
```

For editable installations and contributor setup, see the
[Contributing guide](https://github.com/NanoBiostructuresRG-lab/chemvault/blob/main/CONTRIBUTING.md).

## Starting the application

Run:

```bash
chemvault
```

The interface is normally available at `http://localhost:8501`. The installed
launcher starts the packaged Streamlit application; it does not require a
source checkout or a direct `streamlit run app.py` command.

To display command-line help or check the installed version:

```bash
chemvault --help
chemvault --version
```

## Execution modes

### Local mode

Local mode is the default. When `CHEMVAULT_API_URL` is not set, the Streamlit
interface calls the application and service layers directly and accesses the
selected SQLite database locally.

```text
Streamlit UI -> application/services -> SQLite
```

FastAPI is not required for normal use.

### API-client mode (optional)

API-client mode sends supported operations through a FastAPI backend. This mode
is intended for development and validation of the HTTP interface. Start the
backend in one terminal:

```bash
python -m uvicorn api.main:app --reload
```

From the same working directory, set the backend URL and start CHEMVAULT in a
second terminal:

=== "Windows PowerShell"

    ```powershell
    $env:CHEMVAULT_API_URL = "http://127.0.0.1:8000"
    chemvault
    ```

=== "macOS / Linux"

    ```bash
    export CHEMVAULT_API_URL="http://127.0.0.1:8000"
    chemvault
    ```

```text
Streamlit UI -> HTTP client -> FastAPI -> application/services -> SQLite
```

The HTTP path covers the supported database inspection and export operations,
UniProt target resolution, PubChem jobs, scientific runtime activation,
HARMONSMILE and MODELABILITY INDEX jobs, structure consolidation, and fingerprint
artifact export. Unsupported table mutations remain local. An unavailable
configured backend produces a transport error; CHEMVAULT does not silently
switch to local execution. See the [API Reference](api.md) for endpoint
contracts and limitations.

To return to local mode, stop the running application, remove
`CHEMVAULT_API_URL`, and start it again:

=== "Windows PowerShell"

    ```powershell
    Remove-Item Env:CHEMVAULT_API_URL -ErrorAction SilentlyContinue
    chemvault
    ```

=== "macOS / Linux"

    ```bash
    unset CHEMVAULT_API_URL
    chemvault
    ```

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

## Table Manager

The **Table Manager** lists user-facing tables with their provenance, row and
column counts, and inferred status. Its database-maintenance controls expose
the supported management actions and can delete a selected non-`main` table
after explicit `DELETE` confirmation. The `main` table and internal SQLite or
CHEMVAULT tables are protected; a successful deletion also removes the table's
CHEMVAULT metadata and records the operation.

## Constructing a dataset from CSV

1. Enter a value in **SQL Database name**.
2. Upload a CSV file in the Build card.
3. Inspect the imported table and its columns.
4. Use the Refine controls to select columns, filter rows, group records, or
   order a derived table.
5. Preserve a selection as a new table when needed.
6. Export the active table or selected columns as CSV.

CSV import creates a SQLite table from the supplied data; it does not
establish PubChem target provenance or the eligible Structured activity source
required for ACTIVITY LABELS and the subsequent MODELABILITY INDEX workflow.
The scientific meaning of each imported record depends on the supplied
columns.

## Constructing a target-centered PubChem dataset

### Select one biological target

The **Select Target** dialog supports two input modes:

- **Gene symbol and organism** resolves exactly one reviewed UniProt entry from
  the supported organism catalog.
- **UniProt accession** accepts one direct accession independently of the gene
  resolver.

The gene-symbol resolver supports this curated organism catalog:

| Scientific name | Common name | NCBI taxonomy ID |
|---|---|---:|
| *Homo sapiens* | Human | `9606` |
| *Mus musculus* | Mouse | `10090` |
| *Rattus norvegicus* | Rat | `10116` |
| *Oryctolagus cuniculus* | Rabbit | `9986` |
| *Mesocricetus auratus* | Golden hamster | `10036` |

*Homo sapiens* (`9606`) is the default organism for gene-symbol resolution.

Confirm the resolved identity before launching the search. When available,
CHEMVAULT persists the input mode, UniProt accession, gene symbol, organism,
entry name, protein name, common name, and reviewed status as target provenance.

### Run the PubChem protein search

The PubChem search runs as a persisted job in a separate process. The
progress dialog reports its stage, progress, message, and terminal state and
allows active searches to be cancelled. A completed build persists distinct
populations:

- `main` contains the compound-centered molecular records;
- `compound_assays` records CID-to-AID associations and assay context;
- `compound_activities` contains structured activity observations.

CHEMVAULT records the `(protein, AID)` identities enumerated from the source
in the same run. AID-population correspondence is certified only when source
enumeration succeeds and every enumerated identity is accounted for by a
persisted terminal completion or an admissible, predefined row-level exclusion
for zero target-matching activity, supported by target evidence and a nonempty
CID set. Transport, parsing, or execution failures are not admissible
exclusions. This check concerns the AID population, not completeness of
individual CIDs, molecular properties, or activity records.

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

The **MODELABILITY INDEX** measures local agreement between preserved binary
activity labels and similarity in molecular fingerprint space. For each eligible
structure, CHEMVAULT selects one nearest neighbor by Tanimoto similarity and
calculates same-class concordance separately for Active and Inactive
structures. The reported index is the macro average of these two concordances.
When multiple structures have exactly the same maximum Tanimoto similarity,
CHEMVAULT selects the neighbor with the lowest index in the ordered analysis
population.

A value nearer to 1 indicates stronger local label agreement in the selected
fingerprint space. It is a dataset diagnostic, not evidence that a predictive
model has been trained or a guarantee of predictive performance.

MOLRAPTOR generates the requested fingerprint representation. CHEMVAULT
consumes that output, persists compatible artifacts, and calculates the
concordance metrics.

### Fingerprint representations

The fingerprint selector exposes seven representations:

| Display name | Fingerprint identifier |
|---|---|
| Morgan | `morgan` |
| Feature Morgan | `featmorgan` |
| Atom Pair | `atompair` |
| RDKit Topological | `rdk` |
| Topological Torsion | `torsion` |
| Layered | `layered` |
| MACCS | `maccs` |

Morgan is the default. Analyses and persisted artifacts remain scoped to the
resolved fingerprint profile and identity.

### Murcko structural context

The result card reports atom- and bond-aware Bemis-Murcko context separately
from the MODELABILITY INDEX calculation. Acyclic structures have no Murcko
scaffold assignment and remain explicit in the population counts.

**Murcko population context** reports:

- **Murcko population coverage**: cyclic structures with a scaffold divided by
  the complete structure population;
- **Murcko scaffold count**: distinct scaffold identities among cyclic
  structures;
- **Shared-scaffold molecular coverage**: cyclic structures belonging to a
  scaffold containing both outcomes, divided by the cyclic population;
- **Adjusted scaffold effect (ε²)**: the persisted
  finite-population-adjusted scaffold effect derived from within-scaffold label
  balance, or `N/A` when its required denominator is unavailable.

**Nearest-neighbor scaffold interface** classifies the already selected
nearest-neighbor relationship for every structure as cyclic-to-cyclic (`CC`),
cyclic-to-acyclic (`CA`), acyclic-to-cyclic (`AC`), or acyclic-to-acyclic
(`AA`). It reports:

- **Murcko nearest-neighbor coverage**: `CC` relationships divided by the
  complete structure population;
- **Same-scaffold nearest-neighbor fraction**: same-scaffold relationships
  divided by `CC` relationships;
- **Same-scaffold concordance**: label concordance among same-scaffold `CC`
  relationships;
- **Different-scaffold concordance**: label concordance among
  different-scaffold `CC` relationships.

These metrics characterize the persisted relationships; they neither choose
another neighbor nor alter the MODELABILITY INDEX.

## Exports and persisted results

Available public downloads use these filename contracts:

| Download | Format | Filename |
|---|---|---|
| Active table or selected columns | UTF-8 CSV | `<table>_export.csv` |
| Filtered subgroup | CSV | `<table>_subgroup.csv` |
| Filtered Structured activity population | CSV | `chemvault_structured_activity.csv` |
| Nearest-neighbor report | CSV | `<table>_<fingerprint>_<analysis8>_modelability_diagnostics.csv` |
| Murcko relationships | CSV | `<table>_<fingerprint>_<analysis8>_profile_<profile8>_murcko_relationships.csv` |
| Analysis report | JSON | `<table>_<fingerprint>_<analysis8>_modelability_analysis.json` |
| Fingerprints | Compressed NumPy archive | `<database_id>_<activity_type>_fingerprints_<analysis8>.npz` |

The four Modelability downloads shown in the result card are **Nearest-neighbor
report (.csv)**, **Murcko relationships (.csv)**, **Analysis report (.json)**,
and **Fingerprints (.npz)**. Here, `<analysis8>` is the first eight characters
of the CHEMVAULT analysis identity and `<profile8>` is the first eight
characters of the MOLRAPTOR profile hash.

The nearest-neighbor CSV carries the fingerprint type, analysis identity, and
population identity with each molecular comparison. The Murcko relationships
CSV adds the source and selected-neighbor scaffold identities, the Murcko
contract provenance, and numeric 0/1 `CC`, `CA`, `AC`, `AA`, `NS`, and `ND`
columns for aggregation. The JSON preserves the full analysis summary,
provenance, diagnostics, and structural context. The NPZ preserves the ordered
fingerprint matrix, structures, outcomes, labels, stable structure identifiers,
and canonical metadata.

The Murcko relationships CSV projects the selected relationships already
present in the MODELABILITY INDEX result. It does not calculate additional
neighbors or modify the index.

Completed MODELABILITY INDEX results and compatible fingerprint artifacts can
be restored for the same database, source table, analysis identity, and
fingerprint profile. Different fingerprint representations remain distinct.

## Next steps

- Use the [API Reference](api.md) for HTTP paths, payloads, lifecycle states,
  and gateway behavior.
- Review the [Changelog](changelog.md) for the authoritative development
  history.
