# SPDX-License-Identifier: LGPL-3.0-or-later
import json

import pytest

from ui import main_page


INTRODUCTION = (
    "Review recorded database events such as builds, derived tables, "
    "and table cleanup."
)


def _certificate_details(
    *,
    proteins=("P32245",),
    certified_complete=True,
    source_enumeration_succeeded=True,
    reason=None,
    counts=None,
    include_certified_complete=True,
    contract=main_page.AID_COMPLETENESS_CONTRACT,
):
    certificate = {
        "contract": contract,
        "source_enumeration_succeeded": source_enumeration_succeeded,
        "reason": reason,
        "counts": counts or {
            "unresolved": 0,
            "unexpected_persisted": 0,
            "missing_materialization": 0,
        },
    }
    if include_certified_complete:
        certificate["certified_complete"] = certified_complete
    return json.dumps(
        {
            "proteins": list(proteins),
            "aid_completeness": certificate,
        }
    )


def _operation(
    *,
    details=None,
    operation_type="protein_search_loaded",
    created_at="2026-10-13T12:30:00+00:00",
    status="success",
):
    return {
        "operation_type": operation_type,
        "target_table": "main",
        "source_table": None,
        "source_columns": '["CID", "AID"]',
        "created_at": created_at,
        "status": status,
        "details": details,
    }


def _render_history(monkeypatch, operations):
    events = []

    class Gateway:
        def get_operation_history(self, database_id):
            assert database_id == "test_db"
            return tuple(operations)

    monkeypatch.setattr(main_page, "get_backend_gateway", lambda: Gateway())
    monkeypatch.setattr(
        main_page.st,
        "markdown",
        lambda value, **kwargs: events.append(("markdown", value, kwargs)),
    )
    monkeypatch.setattr(
        main_page.st,
        "caption",
        lambda value: events.append(("caption", value)),
    )
    monkeypatch.setattr(
        main_page.st,
        "dataframe",
        lambda value, **kwargs: events.append(("dataframe", value, kwargs)),
    )

    main_page.render_operation_history("test_db")
    return events


def _summary_captions(events):
    return [
        event[1]
        for event in events
        if event[0] == "caption" and event[1] != INTRODUCTION
    ]


def test_certified_correspondence_precedes_operation_history_dataframe(monkeypatch):
    events = _render_history(
        monkeypatch,
        [_operation(details=_certificate_details(proteins=("P16233",)))],
    )

    assert _summary_captions(events) == [
        "AID source correspondence · P16233: Certified."
    ]
    assert [event[0] for event in events] == [
        "markdown",
        "caption",
        "caption",
        "dataframe",
    ]


def test_successful_operation_can_be_not_certified_with_unresolved_identities(
    monkeypatch,
):
    events = _render_history(
        monkeypatch,
        [
            _operation(
                status="success",
                details=_certificate_details(
                    certified_complete=False,
                    reason="aid_population_not_certified",
                    counts={
                        "unresolved": 2,
                        "unexpected_persisted": 0,
                        "missing_materialization": 0,
                    },
                ),
            )
        ],
    )

    assert _summary_captions(events) == [
        "AID source correspondence · P32245: Not certified — "
        "2 unresolved AID identities."
    ]
    dataframe = next(event[1] for event in events if event[0] == "dataframe")
    assert dataframe.loc[0, "Operation status"] == "Success"


@pytest.mark.parametrize(
    ("reason", "diagnostic"),
    [
        ("source_enumeration_failed", "source enumeration failed"),
        (
            "source_enumeration_unavailable",
            "source enumeration metadata unavailable",
        ),
        (
            "invalid_source_enumeration",
            "source enumeration metadata invalid",
        ),
        (
            "source_enumeration_scope_mismatch",
            "source enumeration metadata mismatched the recorded proteins",
        ),
        (
            "unrecognized_reason",
            "source enumeration was not successfully established",
        ),
    ],
)
def test_unsuccessful_source_enumeration_uses_persisted_reason(
    monkeypatch,
    reason,
    diagnostic,
):
    events = _render_history(
        monkeypatch,
        [
            _operation(
                details=_certificate_details(
                    certified_complete=False,
                    source_enumeration_succeeded=False,
                    reason=reason,
                )
            )
        ],
    )

    assert _summary_captions(events) == [
        f"AID source correspondence · P32245: Not certified — {diagnostic}."
    ]


def test_all_non_certification_diagnostics_remain_independent(monkeypatch):
    events = _render_history(
        monkeypatch,
        [
            _operation(
                details=_certificate_details(
                    certified_complete=False,
                    counts={
                        "unresolved": 2,
                        "unexpected_persisted": 3,
                        "missing_materialization": 4,
                    },
                )
            )
        ],
    )

    summary = _summary_captions(events)[0]
    assert summary == (
        "AID source correspondence · P32245: Not certified — "
        "2 unresolved AID identities; "
        "3 unexpected persisted AID identities; "
        "4 AID identities missing persisted materialization."
    )
    assert "9 AID" not in summary


def test_false_certificate_without_valid_diagnostics_invents_no_cause(monkeypatch):
    events = _render_history(
        monkeypatch,
        [
            _operation(
                details=_certificate_details(
                    certified_complete=False,
                    counts={
                        "unresolved": -1,
                        "unexpected_persisted": "2",
                        "missing_materialization": True,
                    },
                )
            )
        ],
    )

    assert _summary_captions(events) == [
        "AID source correspondence · P32245: Not certified."
    ]


def test_multiple_builds_remain_independent_newest_first_with_dates(monkeypatch):
    events = _render_history(
        monkeypatch,
        [
            _operation(
                created_at="2026-10-13T14:00:00+00:00",
                details=_certificate_details(proteins=("P16233",)),
            ),
            _operation(
                created_at="2026-10-12T09:00:00+00:00",
                details=_certificate_details(
                    proteins=("P32245",),
                    certified_complete=False,
                    counts={
                        "unresolved": 1,
                        "unexpected_persisted": 0,
                        "missing_materialization": 0,
                    },
                ),
            ),
        ],
    )

    assert _summary_captions(events) == [
        "AID source correspondence · P16233 · 2026-10-13: Certified.",
        "AID source correspondence · P32245 · 2026-10-12: "
        "Not certified — 1 unresolved AID identity.",
    ]


def test_legacy_malformed_unsupported_and_non_pubchem_operations_add_no_summary(
    monkeypatch,
):
    supported_details = _certificate_details()
    operations = [
        _operation(details="Loaded selected proteins: P32245."),
        _operation(details="{malformed"),
        _operation(details=json.dumps(["not", "an", "object"])),
        _operation(
            details=_certificate_details(contract="unsupported_contract")
        ),
        _operation(
            details=supported_details,
            operation_type="structured_activity_repair",
        ),
    ]

    events = _render_history(monkeypatch, operations)

    assert _summary_captions(events) == []
    dataframe = next(event[1] for event in events if event[0] == "dataframe")
    assert dataframe["Details"].tolist() == [
        operation["details"] for operation in operations
    ]


@pytest.mark.parametrize(
    ("certified_complete", "include_certified_complete"),
    [
        (None, False),
        (None, True),
        ("false", True),
        (1, True),
    ],
)
def test_missing_or_invalid_certification_is_not_available(
    monkeypatch,
    certified_complete,
    include_certified_complete,
):
    events = _render_history(
        monkeypatch,
        [
            _operation(
                details=_certificate_details(
                    certified_complete=certified_complete,
                    include_certified_complete=include_certified_complete,
                    counts={
                        "unresolved": 8,
                        "unexpected_persisted": 0,
                        "missing_materialization": 0,
                    },
                )
            )
        ],
    )

    assert _summary_captions(events) == [
        "AID source correspondence · P32245: Not available."
    ]


def test_operation_history_dataframe_preserves_values_with_header_rename():
    operations = [
        {
            "operation_type": "protein_search_loaded",
            "target_table": "main",
            "source_table": None,
            "source_columns": '["CID", "AID"]',
            "created_at": "2026-10-13T12:30:00+00:00",
            "status": "success",
            "details": "first details",
        },
        {
            "operation_type": "structured_activity_repair",
            "target_table": "compound_activities",
            "source_table": "compound_assays",
            "source_columns": '["Protein"]',
            "created_at": "2026-10-12T08:00:00+00:00",
            "status": "partial",
            "details": "second details",
        },
    ]

    dataframe = main_page._build_operation_history_dataframe(operations)

    assert list(dataframe.columns) == [
        "Created",
        "Operation",
        "Target",
        "Source",
        "Columns",
        "Operation status",
        "Details",
    ]
    assert dataframe.to_dict("records") == [
        {
            "Created": "2026-10-13",
            "Operation": "Protein Search Loaded",
            "Target": "main",
            "Source": "-",
            "Columns": "CID, AID",
            "Operation status": "Success",
            "Details": "first details",
        },
        {
            "Created": "2026-10-12",
            "Operation": "Structured Activity Repair",
            "Target": "compound_activities",
            "Source": "compound_assays",
            "Columns": "Protein",
            "Operation status": "Partial",
            "Details": "second details",
        },
    ]
