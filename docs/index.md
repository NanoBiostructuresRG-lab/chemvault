# CHEMVAULT

<section class="cv-hero">
  <div class="cv-hero__content">
    <p class="cv-eyebrow">Cheminformatics dataset curation</p>
    <div class="cv-brand">
      <img class="cv-brand__logo" src="assets/chemvault-logo.jpeg" alt="CHEMVAULT molecular logo">
      <span class="cv-brand__wordmark">CHEMVAULT</span>
    </div>
    <p class="cv-subtitle">Traceable Target-Centered Bioactivity Dataset Construction and Modelability Assessment</p>
    <div class="cv-actions">
      <a class="md-button md-button--primary" href="usage/#installation">Installation</a>
      <a class="md-button" href="usage/">Usage</a>
      <a class="md-button" href="api/">API Reference</a>
      <a class="md-button" href="changelog/">Changelog</a>
    </div>
  </div>
</section>

## Scientific purpose

CHEMVAULT is a visual application for constructing, curating, tracing, and
exporting molecular and bioactivity datasets. A dataset can begin with a CSV
table or with one biological target resolved to a reviewed UniProt accession.
The target-centered path retrieves compounds, bioassays, and structured
activity observations from PubChem and persists them in SQLite.

Subsequent workflows harmonize molecular structures through HARMONSMILE,
preserve and consolidate PubChem activity labels at the harmonized-structure
level, and assess whether those labels are locally consistent in molecular
fingerprint space. CHEMVAULT records source identity, derived-table provenance,
operation history, and scientific-job state so results remain connected to the
inputs and processing steps that produced them.

!!! note "Scientific boundary"

    CHEMVAULT is a dataset construction and assessment application, not a
    predictive-model training system. Molecular fingerprint generation is
    delegated to [MOLRAPTOR](https://pypi.org/project/molraptor/); CHEMVAULT
    does not implement fingerprint algorithms.

## Core scientific entities

| Entity | Meaning in CHEMVAULT |
|---|---|
| Compound | A source compound identity, normally represented by a PubChem CID. One compound can participate in multiple bioassays. |
| Molecular structure | The chemical representation associated with a compound. `SMILES_Harmonized` is the downstream structure key after harmonization. |
| Activity record | One structured observation for a compound in a bioassay, including its reported outcome and, when available, quantitative type, value, and unit. |
| Bioassay | A PubChem assay identified by an AID. It can contribute activity records for many compounds. |
| Biological target | The protein-centered identity used to construct a PubChem dataset, represented canonically by one UniProt accession and its available target metadata. |

These concepts are deliberately separate. A CID count is not an activity-record
count, an AID is not a compound, and repeated activity observations do not
automatically represent distinct harmonized structures.

## Traceable workflow

<section class="cv-panel">
  <div class="cv-grid cv-grid--three">
    <article class="cv-card">
      <span class="cv-card__tag">01</span>
      <h3>Construct</h3>
      <p>Import a CSV dataset or construct a target-centered PubChem dataset from a gene symbol and organism or a direct UniProt accession.</p>
    </article>
    <article class="cv-card">
      <span class="cv-card__tag">02</span>
      <h3>Curate</h3>
      <p>Inspect structured activity, harmonize structures, preserve binary PubChem outcomes, and consolidate repeated observations by structure.</p>
    </article>
    <article class="cv-card">
      <span class="cv-card__tag">03</span>
      <h3>Assess</h3>
      <p>Calculate the MODELABILITY INDEX from MOLRAPTOR fingerprints and interpret it alongside Murcko structural context and provenance.</p>
    </article>
  </div>
</section>

CHEMVAULT keeps source tables available while derived tables carry their source
relationship and processing summary. Persisted jobs expose progress and
terminal outcomes, while export contracts preserve the selected scientific
population and its analysis identity.

## Documentation

- [Usage](usage.md) covers installation, execution modes, dataset construction,
  scientific workflows, storage, and exports.
- [API Reference](api.md) documents the supported FastAPI endpoints, backend
  gateway, persisted job contracts, and execution distinctions.
- [Changelog](changelog.md) includes the authoritative root changelog without
  duplicating it.

## License

CHEMVAULT is licensed under the
[GNU Lesser General Public License v3.0 or later](https://github.com/NanoBiostructuresRG-lab/chemvault/blob/dev/v0.14.7/LICENSE).
The SPDX identifier is `LGPL-3.0-or-later`.
