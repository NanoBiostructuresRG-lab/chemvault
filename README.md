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

Then open your browser at `http://localhost:8501`

---

## Quick Start

1. Launch the app and open your browser at `http://localhost:8501`
2. In the sidebar, upload `examples/example_chamanp.csv`
3. Explore the loaded dataset using the **Headers** pills
4. Use the **Depurado** section in the sidebar to filter and create new tables
5. Click **Download CSV** to export your curated dataset

---

## Related Tools

CHEMVAULT is part of a broader ecosystem developed by the NanoBiostructures Research Group:

- [CHAMANP](https://pypi.org/project/chamanp/) — molecular dataset curation and preparation
- [HARMONSMILE](https://pypi.org/project/harmonsmile/) — SMILES harmonization toolkit

---

## Citation

If you use **CHEMVAULT** in your research, please cite it using the metadata in
[CITATION.cff](CITATION.cff) or the format below:

```text
Castro-Flores, D. and Contreras-Torres, F. F. (2026). CHEMVAULT: Streamlit app for building, curating, and exporting molecular chemical datasets. https://github.com/NanoBiostructuresRG-lab/chemvault
```

---

## License

This project is licensed under the terms of the
[GNU Lesser General Public License v3.0 or later](LICENSE). See `LICENSE`, `COPYING`, and `COPYING.LESSER`.
SPDX identifier: `LGPL-3.0-or-later`.