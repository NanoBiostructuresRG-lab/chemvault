# SPDX-License-Identifier: LGPL-3.0-or-later
"""AID-level completeness certification for PubChem protein-search builds."""

AID_COMPLETENESS_CONTRACT = "pubchem_protein_search_aid_completeness_v1"

_SOURCE_STATUSES = {"success", "failed", "invalid_response"}
_TARGET_ATTRIBUTIONS = {
    "assay_level_fallback",
    "row_level_with_matches",
    "row_level_zero_matches",
    "not_evaluated",
}


def _normalize_protein(value):
    return str(value).strip().upper()


def _normalize_aid(value):
    return str(value).strip()


def _identity(protein, aid):
    protein = _normalize_protein(protein)
    aid = _normalize_aid(aid)
    if not protein or not aid:
        raise ValueError("protein and AID identities must be non-empty")
    return protein, aid


def _identity_dicts(values):
    return [
        {"protein": protein, "aid": aid}
        for protein, aid in sorted(values)
    ]


def read_source_enumeration(source_enumeration, requested_proteins):
    """Validate persisted source enumeration without reconstructing S."""
    requested = [
        _normalize_protein(value)
        for value in requested_proteins
    ]

    if (
        any(not protein for protein in requested)
        or len(set(requested)) != len(requested)
    ):
        return {
            "valid": False,
            "succeeded": False,
            "source": None,
            "reason": "invalid_requested_proteins",
        }

    if not isinstance(source_enumeration, list):
        return {
            "valid": False,
            "succeeded": False,
            "source": None,
            "reason": "source_enumeration_unavailable",
        }

    entries = {}

    for item in source_enumeration:
        if not isinstance(item, dict):
            return {
                "valid": False,
                "succeeded": False,
                "source": None,
                "reason": "invalid_source_enumeration",
            }

        protein = _normalize_protein(item.get("protein", ""))
        status = item.get("status")
        aids = item.get("aids")

        if (
            not protein
            or protein in entries
            or status not in _SOURCE_STATUSES
            or not isinstance(aids, list)
        ):
            return {
                "valid": False,
                "succeeded": False,
                "source": None,
                "reason": "invalid_source_enumeration",
            }

        normalized_aids = []

        for value in aids:
            aid = _normalize_aid(value)
            if not aid:
                return {
                    "valid": False,
                    "succeeded": False,
                    "source": None,
                    "reason": "invalid_source_enumeration",
                }
            normalized_aids.append(aid)

        if len(set(normalized_aids)) != len(normalized_aids):
            return {
                "valid": False,
                "succeeded": False,
                "source": None,
                "reason": "invalid_source_enumeration",
            }

        # A failed/invalid enumeration cannot legitimately contribute AIDs to S.
        if status != "success" and normalized_aids:
            return {
                "valid": False,
                "succeeded": False,
                "source": None,
                "reason": "invalid_source_enumeration",
            }

        entries[protein] = {
            "status": status,
            "aids": normalized_aids,
        }

    if set(entries) != set(requested):
        return {
            "valid": False,
            "succeeded": False,
            "source": None,
            "reason": "source_enumeration_scope_mismatch",
        }

    succeeded = all(
        entries[protein]["status"] == "success"
        for protein in requested
    )

    if not succeeded:
        return {
            "valid": True,
            "succeeded": False,
            "source": None,
            "reason": "source_enumeration_failed",
        }

    source = {
        _identity(protein, aid)
        for protein in requested
        for aid in entries[protein]["aids"]
    }

    return {
        "valid": True,
        "succeeded": True,
        "source": source,
        "reason": None,
    }


def _evidence_by_identity(aid_evidence):
    evidence = {}

    for item in aid_evidence or []:
        if not isinstance(item, dict):
            continue

        try:
            key = _identity(
                item.get("protein", ""),
                item.get("aid", ""),
            )
        except ValueError:
            continue

        evidence[key] = item

    return evidence


def _candidate_sets(source, aid_evidence):
    evidence = _evidence_by_identity(aid_evidence)

    terminal_candidates = set()
    excluded_b1 = set()

    for key in source:
        item = evidence.get(key, {})

        cid_status = item.get("cid_collection_status")
        activity_status = item.get("activity_retrieval_status")
        attribution = item.get(
            "target_attribution",
            "not_evaluated",
        )

        try:
            cid_count = int(item.get("cid_count", 0) or 0)
            scoped_cid_count = int(
                item.get("scoped_cid_count", 0) or 0
            )
        except (TypeError, ValueError):
            continue

        if attribution not in _TARGET_ATTRIBUTIONS:
            continue

        upstream_ok = (
            cid_status == "success"
            and cid_count > 0
            and activity_status == "success"
        )

        if not upstream_ok:
            continue

        if (
            attribution
            in {
                "assay_level_fallback",
                "row_level_with_matches",
            }
            and scoped_cid_count > 0
        ):
            terminal_candidates.add(key)

        elif (
            attribution == "row_level_zero_matches"
            and scoped_cid_count == 0
        ):
            excluded_b1.add(key)

    return terminal_candidates, excluded_b1


def certify_aid_completeness(
    *,
    source_enumeration,
    requested_proteins,
    aid_evidence,
    persisted_pairs,
):
    """Certify same-run AID correspondence from persisted provenance."""
    source_result = read_source_enumeration(
        source_enumeration,
        requested_proteins,
    )

    persisted = set()

    for protein, aid in persisted_pairs or set():
        try:
            persisted.add(_identity(protein, aid))
        except ValueError:
            continue

    if (
        not source_result["valid"]
        or not source_result["succeeded"]
    ):
        return {
            "contract": AID_COMPLETENESS_CONTRACT,
            "source_enumeration_succeeded": False,
            "certified_complete": False,
            "reason": source_result["reason"],
            "counts": {
                "source_observed": None,
                "terminal": None,
                "excluded_b1": None,
                "unresolved": None,
                "unexpected_persisted": len(persisted),
                "missing_materialization": None,
            },
            "terminal": [],
            "excluded_b1": [],
            "unresolved": [],
            "unexpected_persisted": _identity_dicts(persisted),
            "missing_materialization": [],
            "excluded_b1_persisted": [],
        }

    source = source_result["source"]

    terminal_candidates, excluded_b1 = _candidate_sets(
        source,
        aid_evidence,
    )

    # T is defined only after materialization is verified.
    terminal = terminal_candidates & persisted

    unresolved = source - (terminal | excluded_b1)
    missing_materialization = terminal_candidates - persisted
    unexpected_persisted = persisted - terminal
    excluded_b1_persisted = excluded_b1 & persisted

    certified = (
        terminal.isdisjoint(excluded_b1)
        and source == (terminal | excluded_b1)
        and persisted == terminal
    )

    evidence = _evidence_by_identity(aid_evidence)
    classified_evidence = []

    for key in sorted(source):
        item = dict(evidence.get(key, {}))
        item["protein"], item["aid"] = key

        if key in terminal:
            item["classification"] = "terminal"
        elif key in excluded_b1:
            item["classification"] = "excluded_b1"
        else:
            item["classification"] = "unresolved"

        classified_evidence.append(item)

    return {
        "contract": AID_COMPLETENESS_CONTRACT,
        "source_enumeration_succeeded": True,
        "certified_complete": certified,
        "reason": (
            None
            if certified
            else "aid_population_not_certified"
        ),
        "counts": {
            "source_observed": len(source),
            "terminal": len(terminal),
            "excluded_b1": len(excluded_b1),
            "unresolved": len(unresolved),
            "unexpected_persisted": len(unexpected_persisted),
            "missing_materialization": len(
                missing_materialization
            ),
        },
        "aids": classified_evidence,
        "terminal": _identity_dicts(terminal),
        "excluded_b1": _identity_dicts(excluded_b1),
        "unresolved": _identity_dicts(unresolved),
        "unexpected_persisted": _identity_dicts(
            unexpected_persisted
        ),
        "missing_materialization": _identity_dicts(
            missing_materialization
        ),
        "excluded_b1_persisted": _identity_dicts(
            excluded_b1_persisted
        ),
    }
