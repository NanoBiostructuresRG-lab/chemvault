# CHEMVAULT: Streamlit app for building, curating, and exporting molecular chemical datasets.

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)

---

## What is CHEMVAULT?

**CHEMVAULT** is a visual, no-code tool designed for researchers who need to prepare structured chemical databases for downstream cheminformatics and machine learning pipelines.

It allows you to:

- **Build** molecular datasets from PubChem (via protein targets / BioAssays) or CSV files
- **Curate** datasets using [HARMONSMILE](https://pypi.org/project/harmonsmile/) and [CHAMANP](https://pypi.org/project/chamanp/)
- **Explore** and filter your SQLite database interactively
- **Export** curated subsets as CSV for downstream analysis

CHEMVAULT is developed and maintained by the [NanoBiostructures Research Group](https://github.com/NanoBiostructuresRG-lab).

---

## Who is it for?

CHEMVAULT is intended for researchers in chemistry, biochemistry, and related fields who work with molecular data and need a straightforward way to build and curate chemical databases.

---

## Prerequisites

Before installing CHEMVAULT, make sure you have the following installed on your system:

- [Git](https://git-scm.com/)
- [Conda](https://docs.conda.io/en/latest/)

---

## Installation

> **Windows users:** All the following steps are run from **Anaconda Prompt**.
> **macOS / Linux users:** Use your system **Terminal**.
> **Advanced users:** PowerShell or VS Code integrated terminal also work if conda is properly configured.

1. Navigate to the folder where you want to store the project:

```bash
cd path/to/your/folder  # e.g. cd Documents/GitHub
```

2. Clone the repository:

```bash
git clone https://github.com/NanoBiostructuresRG-lab/chemvault.git
cd chemvault
```

3. Create a conda environment:

```bash
conda create -n chemvault_env python=3.12
```

4. Activate the environment:

```bash
conda activate chemvault_env
```

> You should now see `(chemvault_env)` at the beginning of your prompt.

5. Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

> Make sure `chemvault_env` is activated before running the app.

```bash
streamlit run app.py
```

Then open your browser at `http://localhost:8501`.

---

## Quick Start

### From a CSV file

1. Launch the app and open your browser at `http://localhost:8501`
2. Enter a name for your SQL database in the **SQL Database name** field
3. In the sidebar, upload `examples/example_chamanp.csv`
4. Explore the loaded dataset using the **Columns** pills
5. Use **Refine** to filter the dataset, then click **Create table from current selection** if you want to save a derived table
6. Click **Download CSV** to export your curated dataset

### From PubChem (protein targets)

1. Launch the app and open your browser at `http://localhost:8501`
2. Enter a name for your SQL database in the **SQL Database name** field
3. Click **Search Proteins** in the sidebar
4. Enter a UniProt accession, click **Add to selection**, then **Confirm selection**. `P34971` is a small, practical protein for a smoke test
5. Follow the progress modal while the persistent local worker searches PubChem. It shows the current status, stage, progress, and messages; use **Cancel search** if you need to stop safely
6. Completed PubChem searches populate `main`, `compound_assays`, and `compound_activities`
7. Select the `CID` pill in the **Columns** section
8. Click **HARMONSMILE** in the sidebar, then **Run**
9. Wait for HARMONSMILE to enrich your dataset with molecular properties
10. Use **Refine** to create a focused subtable (for example, select only `CID` and `SMILES_RDKit`), then click **Create table from current selection**
11. Click **Download CSV** to export your curated dataset

> **Note:** Databases are stored in the `SQL/` folder and can be opened again in a later app session. Use a different database name when you want to start fresh.

---

## PubChem worker jobs

PubChem jobs are stored in the SQLite database. Long protein searches continue through a persistent local worker while the app shows status, stage, progress, and messages in the progress modal. Searches can be cancelled safely with **Cancel search**.

---

## Structured activity

Structured PubChem activity is stored in `compound_activities`, separately from the main molecule table. Users can filter activity records by activity type, unit, outcome, AID, and, when one activity type and one unit are selected, a numeric range. The on-screen preview is limited, but **Download CSV** exports the complete filtered result.

---

## Table Manager and operation history

The **Table Manager** lets users inspect database tables, schema, provenance, and operation history. Derived tables can also be deleted there when they are no longer needed.

---

## Understanding HARMONSMILE output

When you run HARMONSMILE on a column of PubChem CIDs, CHEMVAULT enriches your table with molecular properties retrieved and standardized from PubChem. The output includes three SMILES variants:

- **SMILES** -- the original SMILES as retrieved from PubChem.
- **SMILES_RDKit** -- the harmonized SMILES, recanonized by RDKit following a consistent convention (canonical + isomeric + Kekulized). **This is the recommended column for downstream cheminformatics and ML workflows**, as it provides a standardized, uniform representation.
- **ConnectivitySMILES** -- a simplified SMILES describing only atom connectivity, without stereochemistry. Useful for comparing molecular skeletons.

Additional columns include molecular descriptors such as `MolecularFormula`, `MW` (molecular weight), `InChI`, `InChIKey`, `XLogP`, `TPSA`, `Charge`, `HBondDonorCount`, `HBondAcceptorCount`, `RotatableBondCount`, and `HeavyAtomCount`.

> **Tip:** To prepare a clean dataset for ML, use **Refine** to select the columns and rows you need (for example, `CID` + `SMILES_RDKit` + selected descriptors), then use **Create table from current selection** or **Download CSV**.

---

## Running tests

Run the local test suite from the repository root:

```bash
python -m pytest -q -p no:cacheprovider
```

---

## Local stable validation

Before treating a local installation as release-ready, validate these core workflows:

- Complete a PubChem protein-search smoke test with `P34971`
- Start a search with `P32245` and verify the cancellation flow with **Cancel search**
- Open an existing database from the `SQL/` folder
- Export the current molecule selection with **Download CSV**
- Filter structured activity and export the complete filtered result

---

## Related Tools

CHEMVAULT is part of a broader ecosystem developed by the NanoBiostructures Research Group:

- [CHAMANP](https://pypi.org/project/chamanp/) -- molecular dataset curation and preparation
- [HARMONSMILE](https://pypi.org/project/harmonsmile/) -- SMILES harmonization toolkit

---

## Citation

If you use **CHEMVAULT** in your research, please cite it using the format below until a `CITATION.cff` file is added:

```text
Castro-Flores, D. and Contreras-Torres, F. F. (2026). CHEMVAULT: Streamlit app for building, curating, and exporting molecular chemical datasets. https://github.com/NanoBiostructuresRG-lab/chemvault
```

---

## License

This project is licensed under the terms of the
[GNU Lesser General Public License v3.0 or later](LICENSE). See `LICENSE`, `COPYING`, and `COPYING.LESSER`.
SPDX identifier: `LGPL-3.0-or-later`.
