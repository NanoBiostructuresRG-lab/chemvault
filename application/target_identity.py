# SPDX-License-Identifier: LGPL-3.0-or-later
"""Typed target identity provenance for PubChem protein-search builds."""
from dataclasses import asdict, dataclass
import json
from typing import Any


TARGET_IDENTITY_ARTIFACT_CONTRACT = "protein_search_target_identity"
TARGET_IDENTITY_ARTIFACT_VERSION = 1
GENE_SYMBOL_INPUT_MODE = "gene_symbol"
UNIPROT_ACCESSION_INPUT_MODE = "uniprot_accession"
TARGET_IDENTITY_INPUT_MODES = frozenset(
    {GENE_SYMBOL_INPUT_MODE, UNIPROT_ACCESSION_INPUT_MODE}
)


class InvalidTargetIdentityError(ValueError):
    """Raised when target identity provenance is incomplete or inconsistent."""


@dataclass(frozen=True)
class TargetIdentity:
    input_mode: str
    uniprot_accession: str
    gene_symbol: str | None = None
    organism_id: int | None = None
    organism_name: str | None = None
    common_name: str | None = None
    uniprot_entry_name: str | None = None
    protein_name: str | None = None
    reviewed: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


def _required_text(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidTargetIdentityError(
            f"Target identity field '{key}' is required."
        )
    return value.strip()


def _optional_text(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvalidTargetIdentityError(
            f"Target identity field '{key}' must be a non-empty string."
        )
    return value.strip()


def target_identity_from_payload(
    payload,
    *,
    expected_accession: str | None = None,
) -> TargetIdentity | None:
    """Validate and normalize one optional target-identity payload."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise InvalidTargetIdentityError(
            "Target identity must be provided as an object."
        )

    allowed_fields = {
        "input_mode",
        "uniprot_accession",
        "gene_symbol",
        "organism_id",
        "organism_name",
        "common_name",
        "uniprot_entry_name",
        "protein_name",
        "reviewed",
    }
    unknown_fields = sorted(set(payload) - allowed_fields)
    if unknown_fields:
        raise InvalidTargetIdentityError(
            "Unsupported target identity fields: "
            f"{', '.join(unknown_fields)}."
        )

    input_mode = _required_text(payload, "input_mode")
    if input_mode not in TARGET_IDENTITY_INPUT_MODES:
        raise InvalidTargetIdentityError(
            f"Unsupported target identity input mode: {input_mode}."
        )

    uniprot_accession = _required_text(
        payload,
        "uniprot_accession",
    ).upper()
    if (
        expected_accession is not None
        and uniprot_accession != str(expected_accession).strip().upper()
    ):
        raise InvalidTargetIdentityError(
            "Target identity UniProt accession must match the protein-search "
            "accession."
        )

    if input_mode == UNIPROT_ACCESSION_INPUT_MODE:
        extra_fields = (
            "gene_symbol",
            "organism_id",
            "organism_name",
            "common_name",
            "uniprot_entry_name",
            "protein_name",
            "reviewed",
        )
        if any(payload.get(field) is not None for field in extra_fields):
            raise InvalidTargetIdentityError(
                "Direct UniProt accession input must not include inferred "
                "gene or organism metadata."
            )
        return TargetIdentity(
            input_mode=input_mode,
            uniprot_accession=uniprot_accession,
        )

    gene_symbol = _required_text(payload, "gene_symbol").upper()
    organism_id = payload.get("organism_id")
    if (
        isinstance(organism_id, bool)
        or not isinstance(organism_id, int)
        or organism_id <= 0
    ):
        raise InvalidTargetIdentityError(
            "Target identity field 'organism_id' must be a positive integer."
        )
    reviewed = payload.get("reviewed")
    if not isinstance(reviewed, bool):
        raise InvalidTargetIdentityError(
            "Target identity field 'reviewed' must be a boolean."
        )

    return TargetIdentity(
        input_mode=input_mode,
        uniprot_accession=uniprot_accession,
        gene_symbol=gene_symbol,
        organism_id=organism_id,
        organism_name=_required_text(payload, "organism_name"),
        common_name=_optional_text(payload, "common_name"),
        uniprot_entry_name=_required_text(
            payload,
            "uniprot_entry_name",
        ),
        protein_name=_required_text(payload, "protein_name"),
        reviewed=reviewed,
    )


def target_identity_notes(identity: TargetIdentity) -> str:
    """Serialize target identity into versioned table-provenance notes."""
    return json.dumps(
        {
            "artifact_contract": TARGET_IDENTITY_ARTIFACT_CONTRACT,
            "version": TARGET_IDENTITY_ARTIFACT_VERSION,
            "target_identity": identity.to_payload(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def target_identity_from_notes(notes: str | None) -> TargetIdentity | None:
    """Read target identity from table metadata without guessing legacy data."""
    if not notes:
        return None
    try:
        payload = json.loads(notes)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if (
        payload.get("artifact_contract")
        != TARGET_IDENTITY_ARTIFACT_CONTRACT
        or payload.get("version") != TARGET_IDENTITY_ARTIFACT_VERSION
    ):
        return None
    try:
        return target_identity_from_payload(payload.get("target_identity"))
    except InvalidTargetIdentityError:
        return None
