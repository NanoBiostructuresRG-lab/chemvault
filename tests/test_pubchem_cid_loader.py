# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services import pubchem_protein_search as pubchem_loader
from services import pubchem_client


class FakeResponse:
    def __init__(self, json_data=None, text="", status_code=200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data


class FakeProgress:
    def __init__(self):
        self.values = []

    def progress(self, value):
        self.values.append(value)


def test_fetch_compound_names_uses_configured_batch_size(monkeypatch):
    requested_urls = []

    def fake_get(url, timeout):
        requested_urls.append(url)
        cid_block = url.split("/compound/cid/")[1].split("/property/Title/JSON")[0]
        return FakeResponse(
            {
                "PropertyTable": {
                    "Properties": [
                        {"CID": int(cid), "Title": f"Compound {cid}"}
                        for cid in cid_block.split(",")
                    ]
                }
            }
        )

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)

    names = pubchem_loader._fetch_compound_names(range(1, 502))

    assert len(requested_urls) == 2
    assert "/compound/cid/1,2,3" in requested_urls[0]
    assert "/compound/cid/501/property/Title/JSON" in requested_urls[1]
    assert names["1"] == "Compound 1"
    assert names["500"] == "Compound 500"
    assert names["501"] == "Compound 501"


def test_obtener_cids_pubchem_enriches_main_table(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,IC50_Mean_Qualifier,IC50_Mean",
            "RESULT_TYPE,,,STRING,FLOAT",
            "RESULT_UNIT,,,,MICROMOLAR",
            "1,3779,Active,=,0.42",
        ]
    )

    def fake_get(url, timeout):
        if "/assay/target/accession/P21554/aids/JSON" in url:
            return FakeResponse({"IdentifierList": {"AID": [2339]}})
        if "/assay/aid/2339/cids/JSON" in url:
            return FakeResponse(
                {"InformationList": {"Information": [{"AID": 2339, "CID": [3779]}]}}
            )
        if "/assay/aid/2339/CSV" in url:
            return FakeResponse(text=assay_csv)
        if "/compound/cid/3779/property/Title/JSON" in url:
            return FakeResponse(
                {"PropertyTable": {"Properties": [{"CID": 3779, "Title": "Isoproterenol"}]}}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)
    progress = FakeProgress()

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], progress)

    cursor = connection.cursor()
    cursor.execute("PRAGMA table_info(main)")
    columns = [row[1] for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT CID, AIDs, Proteins, Compound_Name, Activity_Enrichment_Status
        FROM main
        """
    )
    row = cursor.fetchone()

    assert columns == [
        "primary_id",
        "CID",
        "AIDs",
        "Proteins",
        "Compound_Name",
        "Activity_Enrichment_Status",
    ]
    assert row == (
        "3779",
        "2339",
        "P21554",
        "Isoproterenol",
        "enriched",
    )
    cursor.execute("SELECT CID, AID, Protein FROM compound_assays")
    assert cursor.fetchall() == [("3779", "2339", "P21554")]
    cursor.execute(
        """
        SELECT
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
        FROM compound_activities
        """
    )
    assert cursor.fetchall() == [
        (
            "3779",
            "2339",
            "P21554",
            "IC50_Mean",
            "=",
            0.42,
            "0.42",
            "MICROMOLAR",
            "Active",
            "IC50_Mean",
            "enriched",
            "1",
        )
    ]
    assert progress.values[-1] == 1.0
    assert len(progress.values) > 1


def test_obtener_cids_pubchem_uses_concurrent_activity_enrichment(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    captured = {}

    def fake_get(url, timeout):
        if "/assay/target/accession/P21554/aids/JSON" in url:
            return FakeResponse({"IdentifierList": {"AID": [2339]}})
        if "/assay/aid/2339/cids/JSON" in url:
            return FakeResponse(
                {"InformationList": {"Information": [{"AID": 2339, "CID": [3779]}]}}
            )
        if "/compound/cid/3779/property/Title/JSON" in url:
            return FakeResponse(
                {"PropertyTable": {"Properties": [{"CID": 3779, "Title": "Isoproterenol"}]}}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_activity_runner(connection, aid_jobs, activity_fetcher, **kwargs):
        captured["aid_jobs"] = aid_jobs
        captured["kwargs"] = kwargs
        return {"successful_cid_values": ["3779"]}

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)
    monkeypatch.setattr(
        pubchem_loader,
        "run_pubchem_activity_enrichment",
        fake_activity_runner,
    )

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], FakeProgress())

    assert captured["aid_jobs"] == [
        {"protein": "P21554", "aid": "2339", "cids": ["3779"]}
    ]
    assert captured["kwargs"]["max_workers"] == 4
    assert captured["kwargs"]["rate_limit_per_second"] == 4
    assert captured["kwargs"]["max_retries"] == 3
    assert captured["kwargs"]["retry_initial_delay"] == 1.0
    assert captured["kwargs"]["retry_backoff_multiplier"] == 2.0
    assert captured["kwargs"]["retry_max_delay"] == 8.0
    assert captured["kwargs"]["continue_on_error"] is True


def test_obtener_cids_pubchem_enriches_activity_for_large_aid_sets(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    aids = list(range(1, pubchem_loader.MAX_ACTIVITY_AIDS + 2))
    requested_urls = []

    def fake_get(url, timeout):
        requested_urls.append(url)
        if "/assay/target/accession/P21554/aids/JSON" in url:
            return FakeResponse({"IdentifierList": {"AID": aids}})
        if "/assay/aid/" in url and "/cids/JSON" in url:
            aid_block = url.split("/assay/aid/")[1].split("/cids/JSON")[0]
            return FakeResponse(
                {
                    "InformationList": {
                        "Information": [
                            {"AID": int(aid), "CID": [1000 + int(aid)]}
                            for aid in aid_block.split(",")
                        ]
                    }
                }
            )
        if "/assay/aid/" in url and url.endswith("/CSV"):
            aid = int(url.split("/assay/aid/")[1].split("/CSV")[0])
            cid = 1000 + aid
            assay_csv = "\n".join(
                [
                    "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki",
                    "RESULT_TYPE,,,FLOAT",
                    "RESULT_UNIT,,,NANOMOLAR",
                    f"1,{cid},Active,{aid}",
                ]
            )
            return FakeResponse(text=assay_csv)
        if "/compound/cid/" in url:
            cid_block = url.split("/compound/cid/")[1].split("/property/Title/JSON")[0]
            return FakeResponse(
                {
                    "PropertyTable": {
                        "Properties": [
                            {"CID": int(cid), "Title": f"Compound {cid}"}
                            for cid in cid_block.split(",")
                        ]
                    }
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], FakeProgress())

    assert len([url for url in requested_urls if url.endswith("/CSV")]) == len(aids)
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*), COUNT(Compound_Name) FROM main")
    assert cursor.fetchone() == (len(aids), len(aids))
    cursor.execute(
        "SELECT COUNT(*) FROM main WHERE Activity_Enrichment_Status = 'enriched'"
    )
    assert cursor.fetchone() == (len(aids),)
    cursor.execute(
        "SELECT COUNT(*) FROM main WHERE Activity_Enrichment_Status = 'skipped_aid_limit'"
    )
    assert cursor.fetchone() == (0,)
    cursor.execute("SELECT COUNT(DISTINCT AID), COUNT(*) FROM compound_assays")
    assert cursor.fetchone() == (len(aids), len(aids))
    cursor.execute("SELECT COUNT(*) FROM compound_activities")
    assert cursor.fetchone() == (len(aids),)


def test_obtener_cids_pubchem_preserves_cid_deduplication_and_assay_traceability(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )

    def fake_get(url, timeout):
        if "/assay/target/accession/P21554/aids/JSON" in url:
            return FakeResponse({"IdentifierList": {"AID": [11, 22]}})
        if "/assay/aid/11,22/cids/JSON" in url:
            return FakeResponse(
                {
                    "InformationList": {
                        "Information": [
                            {"AID": 11, "CID": [3779]},
                            {"AID": 22, "CID": [3779]},
                        ]
                    }
                }
            )
        if "/assay/aid/11/CSV" in url or "/assay/aid/22/CSV" in url:
            return FakeResponse(
                text="PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME\n"
                "RESULT_TYPE,,\n"
                "1,3779,Active\n"
            )
        if "/compound/cid/3779/property/Title/JSON" in url:
            return FakeResponse(
                {"PropertyTable": {"Properties": [{"CID": 3779, "Title": "Isoproterenol"}]}}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], FakeProgress())
    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], FakeProgress())

    cursor = connection.cursor()
    cursor.execute("SELECT CID, AIDs, Proteins FROM main")
    assert cursor.fetchall() == [("3779", "11, 22", "P21554")]
    cursor.execute("SELECT CID, AID, Protein FROM compound_assays ORDER BY AID")
    assert cursor.fetchall() == [
        ("3779", "11", "P21554"),
        ("3779", "22", "P21554"),
    ]
    cursor.execute("SELECT COUNT(*) FROM compound_assays")
    assert cursor.fetchone() == (2,)


def test_compound_activities_stores_one_row_per_cid_aid_activity(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )

    def fake_get(url, timeout):
        if "/assay/target/accession/P21554/aids/JSON" in url:
            return FakeResponse({"IdentifierList": {"AID": [11, 22]}})
        if "/assay/aid/11,22/cids/JSON" in url:
            return FakeResponse(
                {
                    "InformationList": {
                        "Information": [
                            {"AID": 11, "CID": [3779]},
                            {"AID": 22, "CID": [3779]},
                        ]
                    }
                }
            )
        if "/assay/aid/11/CSV" in url:
            return FakeResponse(
                text="PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki\n"
                "RESULT_TYPE,,,FLOAT\n"
                "RESULT_UNIT,,,NANOMOLAR\n"
                "1,3779,Active,10"
            )
        if "/assay/aid/22/CSV" in url:
            return FakeResponse(
                text="PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki\n"
                "RESULT_TYPE,,,FLOAT\n"
                "RESULT_UNIT,,,NANOMOLAR\n"
                "1,3779,Active,20"
            )
        if "/compound/cid/3779/property/Title/JSON" in url:
            return FakeResponse(
                {"PropertyTable": {"Properties": [{"CID": 3779, "Title": "Isoproterenol"}]}}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], FakeProgress())

    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM main WHERE CID = '3779'")
    assert cursor.fetchone() == (1,)
    cursor.execute("SELECT COUNT(*) FROM compound_assays")
    assert cursor.fetchone() == (2,)
    cursor.execute(
        """
        SELECT AID, Activity_Type, Activity_Value, Activity_Value_Raw, Source_Column
        FROM compound_activities
        ORDER BY AID
        """
    )
    assert cursor.fetchall() == [
        ("11", "Ki", 10.0, "10", "Ki"),
        ("22", "Ki", 20.0, "20", "Ki"),
    ]


def test_compound_activities_allows_multiple_results_for_same_cid_aid(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki",
            "RESULT_TYPE,,,FLOAT",
            "RESULT_UNIT,,,NANOMOLAR",
            "1,3779,Active,10",
            "2,3779,Active,20",
        ]
    )

    def fake_get(url, timeout):
        if "/assay/target/accession/P21554/aids/JSON" in url:
            return FakeResponse({"IdentifierList": {"AID": [11]}})
        if "/assay/aid/11/cids/JSON" in url:
            return FakeResponse(
                {"InformationList": {"Information": [{"AID": 11, "CID": [3779]}]}}
            )
        if "/assay/aid/11/CSV" in url:
            return FakeResponse(text=assay_csv)
        if "/compound/cid/3779/property/Title/JSON" in url:
            return FakeResponse(
                {"PropertyTable": {"Properties": [{"CID": 3779, "Title": "Isoproterenol"}]}}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], FakeProgress())

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT Result_Tag, Activity_Value, Activity_Value_Raw
        FROM compound_activities
        ORDER BY Result_Tag
        """
    )
    assert cursor.fetchall() == [("1", 10.0, "10"), ("2", 20.0, "20")]


def test_activity_parser_enriches_real_ki_value(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki",
            "RESULT_TYPE,,,FLOAT",
            "RESULT_UNIT,,,NANOMOLAR",
            "1,3779,Active,1.891e+07",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(1804316)

    assert activity["3779"]["types"] == {"Ki"}
    assert activity["3779"]["values"] == {
        "AID 1804316: Ki 1.891e+07 NANOMOLAR (Active)"
    }
    assert activity["3779"]["records"] == [
        {
            "CID": "3779",
            "AID": "1804316",
            "Activity_Type": "Ki",
            "Relation": "",
            "Activity_Value": 1.891e+07,
            "Activity_Value_Raw": "1.891e+07",
            "Unit": "NANOMOLAR",
            "Outcome": "Active",
            "Source_Column": "Ki",
            "Activity_Status": "enriched",
            "Result_Tag": "1",
        }
    ]


def test_activity_parser_ignores_qualifier_only_columns(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki Qualifier",
            "RESULT_TYPE,,,STRING",
            "RESULT_UNIT,,,NONE",
            "1,3779,Inactive,>",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    assert pubchem_loader._fetch_assay_activity(1804316) == {}


def test_activity_parser_uses_qualifier_as_complement_to_real_value(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki Qualifier,Ki",
            "RESULT_TYPE,,,STRING,FLOAT",
            "RESULT_UNIT,,,NONE,NANOMOLAR",
            "1,3779,Active,>,1.891e+07",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(1804316)

    assert activity["3779"]["types"] == {"Ki"}
    assert activity["3779"]["values"] == {
        "AID 1804316: Ki > 1.891e+07 NANOMOLAR (Active)"
    }
    assert activity["3779"]["records"][0]["Relation"] == ">"


def test_activity_parser_enriches_pubchem_standard_value_with_metadata(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,PubChem Standard Type,PubChem Standard Relation,PubChem Standard Value,PubChem Standard Unit",
            "RESULT_TYPE,,,STRING,STRING,FLOAT,STRING",
            "1,3779,Active,IC50,>,12.3,MICROMOLAR",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(41441)

    assert activity["3779"]["types"] == {"PubChem Standard Value"}
    assert activity["3779"]["values"] == {
        "AID 41441: PubChem Standard Value (IC50) > 12.3 MICROMOLAR (Active)"
    }
    assert activity["3779"]["records"] == [
        {
            "CID": "3779",
            "AID": "41441",
            "Activity_Type": "IC50",
            "Relation": ">",
            "Activity_Value": 12.3,
            "Activity_Value_Raw": "12.3",
            "Unit": "MICROMOLAR",
            "Outcome": "Active",
            "Source_Column": "PubChem Standard Value",
            "Activity_Status": "enriched",
            "Result_Tag": "1",
        }
    ]


def test_activity_parser_uses_result_unit_for_pubchem_standard_value(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Type,Standard Relation,PubChem Standard Value",
            "RESULT_TYPE,,,STRING,STRING,FLOAT",
            "RESULT_UNIT,,,,,MICROMOLAR",
            "1,3779,Active,EC50,=,0.049",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(41441)

    assert activity["3779"]["values"] == {
        "AID 41441: PubChem Standard Value (EC50) = 0.049 MICROMOLAR (Active)"
    }
    assert activity["3779"]["records"][0]["Unit"] == "MICROMOLAR"


def test_activity_parser_enriches_standard_value_fallback(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Type,Standard Value,Standard Unit",
            "RESULT_TYPE,,,STRING,FLOAT,STRING",
            "1,3779,Active,Potency,4.5,NANOMOLAR",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(41443)

    assert activity["3779"]["types"] == {"Standard Value"}
    assert activity["3779"]["values"] == {
        "AID 41443: Standard Value (Potency) 4.5 NANOMOLAR (Active)"
    }
    assert activity["3779"]["records"][0]["Activity_Type"] == "Potency"
    assert activity["3779"]["records"][0]["Source_Column"] == "Standard Value"


def test_activity_parser_uses_plural_standard_units_for_standard_value(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Type,Standard Relation,Standard Value,Standard Units",
            "RESULT_TYPE,,,STRING,STRING,FLOAT,STRING",
            "1,3779,Unspecified,Inhibition,=,4,%",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(41908)

    assert activity["3779"]["values"] == {
        "AID 41908: Standard Value (Inhibition) = 4 % (Unspecified)"
    }
    assert activity["3779"]["records"][0]["Unit"] == "%"


def test_activity_parser_marks_relative_potency_without_declared_unit_as_dimensionless(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Type,Standard Relation,Standard Value",
            "RESULT_TYPE,,,STRING,STRING,FLOAT",
            "1,3779,Unspecified,Relative potency,=,3.6e-06",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(201139)

    assert activity["3779"]["values"] == {
        "AID 201139: Standard Value (Relative potency) = 3.6e-06 dimensionless (Unspecified)"
    }
    assert activity["3779"]["records"][0]["Unit"] == "dimensionless"


def test_activity_parser_keeps_declared_unit_for_relative_potency(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Type,Standard Relation,Standard Value,Standard Units",
            "RESULT_TYPE,,,STRING,STRING,FLOAT,STRING",
            "1,3779,Unspecified,Relative potency,=,3.6e-06,fold",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(201139)

    assert activity["3779"]["values"] == {
        "AID 201139: Standard Value (Relative potency) = 3.6e-06 fold (Unspecified)"
    }
    assert activity["3779"]["records"][0]["Unit"] == "fold"


def test_activity_parser_leaves_kd_unit_empty_when_pubchem_has_none(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Type,Standard Relation,Standard Value",
            "RESULT_TYPE,,,STRING,STRING,FLOAT",
            "1,3779,Unspecified,Kd,=,3.2e-07",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(41443)

    assert activity["3779"]["values"] == {
        "AID 41443: Standard Value (Kd) = 3.2e-07 (Unspecified)"
    }
    assert activity["3779"]["records"][0]["Unit"] == ""


def test_activity_parser_keeps_specific_column_priority_over_standard_value(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Ki,PubChem Standard Type,PubChem Standard Value,PubChem Standard Unit",
            "RESULT_TYPE,,,FLOAT,STRING,FLOAT,STRING",
            "RESULT_UNIT,,,NANOMOLAR,,,",
            "1,3779,Active,1.891e+07,Ki,18.91,MICROMOLAR",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(1804316)

    assert activity["3779"]["types"] == {"Ki"}
    assert activity["3779"]["values"] == {
        "AID 1804316: Ki 1.891e+07 NANOMOLAR (Active)"
    }
    assert activity["3779"]["records"][0]["Source_Column"] == "Ki"


def test_activity_parser_leaves_empty_standard_value_as_no_activity(monkeypatch):
    assay_csv = "\n".join(
        [
            "PUBCHEM_RESULT_TAG,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Value",
            "RESULT_TYPE,,,FLOAT",
            "1,3779,Inactive,",
        ]
    )

    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    assert pubchem_loader._fetch_assay_activity(41441) == {}
    assert (
        pubchem_loader._classify_activity_failure(
            {
                "PUBCHEM_CID": "3779",
                "PUBCHEM_ACTIVITY_OUTCOME": "Inactive",
                "Standard Value": "",
            },
            [],
        )
        == "outcome_only"
    )


def test_activity_failure_classifier_detects_unsupported_activity_column():
    assert (
        pubchem_loader._classify_activity_failure(
            {
                "PUBCHEM_CID": "3779",
                "PUBCHEM_ACTIVITY_OUTCOME": "Active",
                "Inhibition": "73",
            },
            [],
        )
        == "unsupported_activity_column"
    )


def test_fetch_assay_activity_keeps_legacy_empty_result_on_request_error(monkeypatch):
    def failing_get(url, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(pubchem_client.requests, "get", failing_get)

    assert pubchem_loader._fetch_assay_activity(41441) == {}


def test_fetch_assay_activity_reraises_when_requested(monkeypatch):
    def failing_get(url, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(pubchem_client.requests, "get", failing_get)

    try:
        pubchem_loader._fetch_assay_activity(41441, raise_on_error=True)
    except RuntimeError as exc:
        assert str(exc) == "network down"
    else:
        raise AssertionError("Expected RuntimeError")


def test_fetch_pubchem_assay_activity_uses_strict_fetch_contract(monkeypatch):
    def failing_get(url, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(pubchem_client.requests, "get", failing_get)

    try:
        pubchem_loader.fetch_pubchem_assay_activity(41441)
    except RuntimeError as exc:
        assert str(exc) == "network down"
    else:
        raise AssertionError("Expected RuntimeError")
