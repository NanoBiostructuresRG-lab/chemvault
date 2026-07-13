# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.activity_data import (
    ACTIVITY_EXPORT_COLUMNS,
    build_activity_subset_base_name,
    compound_activities_exists,
    create_activity_subset_table,
    get_activity_cids,
    get_activity_csv_bytes,
    get_activity_row_count,
    get_activity_rows,
    get_activity_summary,
    get_activity_value_stats,
    unique_activity_subset_table_name,
)


def csv_text(data):
    return data.decode("utf-8").replace("\r\n", "\n")


def create_activity_connection():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE compound_activities (
            CID TEXT,
            AID TEXT,
            Protein TEXT,
            Activity_Type TEXT,
            Relation TEXT,
            Activity_Value REAL,
            Activity_Value_Raw TEXT,
            Unit TEXT,
            Outcome TEXT,
            Source_Column TEXT,
            Activity_Status TEXT,
            Result_Tag TEXT
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO compound_activities (
            CID,
            AID,
            Protein,
            Activity_Type,
            Relation,
            Activity_Value,
            Activity_Value_Raw,
            Unit,
            Outcome,
            Source_Column,
            Activity_Status,
            Result_Tag
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "100",
                "11",
                "P34971",
                "Ki",
                ">",
                10.0,
                "10",
                "NANOMOLAR",
                "Active",
                "Ki",
                "enriched",
                "1",
            ),
            (
                "101",
                "12",
                "P34971",
                "IC50",
                "",
                25.0,
                "25",
                "MICROMOLAR",
                "Inactive",
                "PubChem Standard Value",
                "enriched",
                "1",
            ),
            (
                "102",
                "12",
                "P34971",
                "IC50",
                "",
                40.0,
                "40",
                "MICROMOLAR",
                "Active",
                "PubChem Standard Value",
                "enriched",
                "2",
            ),
        ],
    )
    return connection


def test_compound_activities_missing_table_is_safe():
    connection = sqlite3.connect(":memory:")

    assert compound_activities_exists(connection) is False
    assert get_activity_summary(connection) is None
    assert get_activity_row_count(connection) == 0
    assert get_activity_value_stats(connection) is None
    assert get_activity_rows(connection) == []


def test_get_activity_summary_counts_and_options():
    connection = create_activity_connection()

    summary = get_activity_summary(connection)

    assert summary["total_rows"] == 3
    assert summary["unique_cids"] == 3
    assert summary["unique_aids"] == 2
    assert summary["min_value"] == 10.0
    assert summary["max_value"] == 40.0
    assert summary["activity_types"] == ["IC50", "Ki"]
    assert summary["outcomes"] == ["Active", "Inactive"]
    assert summary["units"] == ["MICROMOLAR", "NANOMOLAR"]
    assert summary["source_columns"] == ["Ki", "PubChem Standard Value"]
    assert summary["aids"] == ["11", "12"]


def test_get_activity_rows_filters_by_type_outcome_unit_and_value_range():
    connection = create_activity_connection()

    rows = get_activity_rows(
        connection,
        activity_types=["IC50"],
        outcomes=["Active"],
        units=["MICROMOLAR"],
        value_range=(30.0, 45.0),
    )

    assert len(rows) == 1
    assert rows[0]["CID"] == "102"
    assert rows[0]["Activity_Value"] == 40.0
    assert rows[0]["Source_Column"] == "PubChem Standard Value"


def test_get_activity_row_count_uses_full_filtered_result():
    connection = create_activity_connection()

    count = get_activity_row_count(
        connection,
        activity_types=["IC50"],
        units=["MICROMOLAR"],
    )

    assert count == 2


def test_get_activity_value_stats_uses_categorical_filters_without_value_range():
    connection = create_activity_connection()

    stats = get_activity_value_stats(
        connection,
        activity_types=["IC50"],
        outcomes=["Active"],
        units=["MICROMOLAR"],
    )

    assert stats == {
        "total_rows": 1,
        "min_value": 40.0,
        "max_value": 40.0,
        "qualified_rows": 0,
    }


def test_get_activity_value_stats_counts_qualified_relations():
    connection = create_activity_connection()

    stats = get_activity_value_stats(
        connection,
        activity_types=["Ki"],
        units=["NANOMOLAR"],
    )

    assert stats["total_rows"] == 1
    assert stats["min_value"] == 10.0
    assert stats["max_value"] == 10.0
    assert stats["qualified_rows"] == 1


def test_get_activity_rows_can_limit_preview_without_changing_count():
    connection = create_activity_connection()

    preview_rows = get_activity_rows(connection, limit=2)
    full_count = get_activity_row_count(connection)

    assert len(preview_rows) == 2
    assert full_count == 3


def test_get_activity_rows_filters_by_aid():
    connection = create_activity_connection()

    rows = get_activity_rows(connection, aids=["11"])

    assert [row["CID"] for row in rows] == ["100"]


def test_get_activity_cids_uses_structured_activity_filters_and_deduplicates():
    connection = create_activity_connection()
    connection.execute(
        """
        INSERT INTO compound_activities (
            CID,
            AID,
            Protein,
            Activity_Type,
            Relation,
            Activity_Value,
            Activity_Value_Raw,
            Unit,
            Outcome,
            Source_Column,
            Activity_Status,
            Result_Tag
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "102",
            "13",
            "P34971",
            "IC50",
            "",
            42.0,
            "42",
            "MICROMOLAR",
            "Active",
            "PubChem Standard Value",
            "enriched",
            "3",
        ),
    )

    cids = get_activity_cids(
        connection,
        activity_types=["IC50"],
        outcomes=["Active"],
        units=["MICROMOLAR"],
        value_range=(30.0, 45.0),
    )

    assert cids == ["102"]


def test_get_activity_rows_uses_expected_export_columns():
    connection = create_activity_connection()

    rows = get_activity_rows(connection)

    assert list(rows[0].keys()) == ACTIVITY_EXPORT_COLUMNS


def test_get_activity_csv_bytes_exports_filtered_rows_with_expected_columns():
    connection = create_activity_connection()

    result = get_activity_csv_bytes(
        connection,
        activity_types=["IC50"],
        units=["MICROMOLAR"],
    )

    assert csv_text(result) == (
        "CID,AID,Protein,Activity_Type,Relation,Activity_Value,Activity_Value_Raw,"
        "Unit,Outcome,Source_Column,Result_Tag\n"
        "101,12,P34971,IC50,,25.0,25,MICROMOLAR,Inactive,PubChem Standard Value,1\n"
        "102,12,P34971,IC50,,40.0,40,MICROMOLAR,Active,PubChem Standard Value,2\n"
    )


def test_get_activity_csv_bytes_fetches_rows_in_chunks():
    connection = create_activity_connection()

    result = get_activity_csv_bytes(connection, fetch_size=2)

    assert csv_text(result).count("\n") == 4


def test_activity_subset_base_name_uses_exact_activity_type_and_unit():
    assert build_activity_subset_base_name(
        activity_types=["EC50"],
        units=["MICROMOLAR"],
    ) == "activity_subset_EC50_MICROMOLAR"
    assert build_activity_subset_base_name(
        activity_types=["IC50 (%)"],
        units=[],
    ) == "activity_subset_IC50"
    assert build_activity_subset_base_name(
        activity_types=["Relative potency"],
        units=[],
    ) == "activity_subset_Relative_potency"
    assert build_activity_subset_base_name(
        activity_types=["EC50", "IC50"],
        units=["MICROMOLAR"],
    ) == "activity_subset_filtered_activity"


def test_unique_activity_subset_table_name_appends_numeric_suffix():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "activity_subset_EC50" (CID TEXT)')
    connection.execute('CREATE TABLE "activity_subset_EC50_2" (CID TEXT)')

    table_name = unique_activity_subset_table_name(
        connection,
        activity_types=["EC50"],
        units=[],
    )

    assert table_name == "activity_subset_EC50_3"


def test_create_activity_subset_table_matches_filtered_activity_export():
    connection = create_activity_connection()
    filter_kwargs = {
        "activity_types": ["IC50"],
        "units": ["MICROMOLAR"],
    }
    expected_rows = get_activity_rows(connection, **filter_kwargs)

    inserted = create_activity_subset_table(
        connection,
        "activity_subset_IC50_MICROMOLAR",
        **filter_kwargs,
    )

    columns = [
        row[1]
        for row in connection.execute(
            'PRAGMA table_info("activity_subset_IC50_MICROMOLAR")'
        )
    ]
    columns_sql = ", ".join(f'"{column}"' for column in ACTIVITY_EXPORT_COLUMNS)
    rows = connection.execute(
        f'SELECT {columns_sql} FROM "activity_subset_IC50_MICROMOLAR" '
        'ORDER BY CAST(AID AS INTEGER), CID, Result_Tag'
    ).fetchall()
    expected_values = [
        tuple(row[column] for column in ACTIVITY_EXPORT_COLUMNS)
        for row in expected_rows
    ]

    assert inserted == len(expected_rows) == 2
    assert columns == ACTIVITY_EXPORT_COLUMNS
    assert rows == expected_values
