# SPDX-License-Identifier: LGPL-3.0-or-later
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageTiming:
    name: str
    label: str


PUBCHEM_STAGE_LABELS = (
    ("aid_search", "AID search"),
    ("cid_collection", "CID collection"),
    ("compound_names", "Compound names"),
    ("sqlite_main_upsert", "SQLite main upsert"),
    ("compound_assays_insert", "compound_assays insert"),
    ("activity_enrichment", "Activity enrichment"),
)

PUBCHEM_STAGE_TIMINGS = tuple(
    StageTiming(name=name, label=label)
    for name, label in PUBCHEM_STAGE_LABELS
)


@dataclass
class StageTimings:
    elapsed_by_stage: dict[str, float] = field(
        default_factory=lambda: {
            stage.name: 0.0
            for stage in PUBCHEM_STAGE_TIMINGS
        }
    )

    def add(self, stage_name, elapsed):
        self.elapsed_by_stage[stage_name] = self.get(stage_name) + elapsed

    def get(self, stage_name, default=0.0):
        return self.elapsed_by_stage.get(stage_name, default)


@dataclass(frozen=True)
class ProgressSnapshot:
    stage: str
    value: float
    message: str = ""


@dataclass(frozen=True)
class ProteinSearchSummary:
    total_aids: int = 0
    total_cids: int = 0
    compound_assay_links: int = 0
    enriched_cids: int = 0
