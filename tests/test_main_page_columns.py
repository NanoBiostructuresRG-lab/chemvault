# SPDX-License-Identifier: LGPL-3.0-or-later
from ui.main_page import ACTIVITY_SUMMARY_COLUMNS, _filter_visible_column_options


def test_filter_visible_column_options_hides_only_activity_summary_columns():
    headers = [
        "primary_id",
        "CID",
        "AIDs",
        "Proteins",
        "Compound_Name",
        "Activity_Type",
        "Activity_Value",
        "Activity_Enrichment_Status",
        "Activity_Value_Raw",
    ]
    selected_headers = ["CID", "Activity_Type", "Activity_Value", "Activity_Value_Raw"]

    options, selected = _filter_visible_column_options(headers, selected_headers)

    assert options == [
        "primary_id",
        "CID",
        "AIDs",
        "Proteins",
        "Compound_Name",
        "Activity_Value_Raw",
    ]
    assert selected == ["CID", "Activity_Value_Raw"]


def test_activity_summary_columns_are_exact_legacy_main_columns():
    assert ACTIVITY_SUMMARY_COLUMNS == {
        "Activity_Type",
        "Activity_Value",
        "Activity_Enrichment_Status",
    }
