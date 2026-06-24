# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from modules import obtener_CIDs_Pubchem as pubchem_loader


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

    monkeypatch.setattr(pubchem_loader.requests, "get", fake_get)
    progress = FakeProgress()

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], progress)

    cursor = connection.cursor()
    cursor.execute("PRAGMA table_info(main)")
    columns = [row[1] for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT CID, AIDs, Proteins, Compound_Name, Activity_Type, Activity_Value, Activity_Enrichment_Status
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
        "Activity_Type",
        "Activity_Value",
        "Activity_Enrichment_Status",
    ]
    assert row == (
        "3779",
        "2339",
        "P21554",
        "Isoproterenol",
        "IC50_Mean",
        "AID 2339: IC50_Mean = 0.42 MICROMOLAR (Active)",
        "enriched",
    )
    cursor.execute("SELECT CID, AID, Protein FROM compound_assays")
    assert cursor.fetchall() == [("3779", "2339", "P21554")]
    assert progress.values[-1] == 1.0
    assert len(progress.values) > 1


def test_obtener_cids_pubchem_skips_activity_for_large_aid_sets(monkeypatch):
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

    monkeypatch.setattr(pubchem_loader.requests, "get", fake_get)

    pubchem_loader.obtener_CIDs_Pubchem(connection, ["P21554"], FakeProgress())

    assert not any(url.endswith("/CSV") for url in requested_urls)
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*), COUNT(Compound_Name) FROM main")
    assert cursor.fetchone() == (len(aids), len(aids))
    cursor.execute("SELECT COUNT(*) FROM main WHERE Activity_Value != ''")
    assert cursor.fetchone() == (0,)
    cursor.execute(
        "SELECT COUNT(*) FROM main WHERE Activity_Enrichment_Status = 'skipped_aid_limit'"
    )
    assert cursor.fetchone() == (len(aids),)
    cursor.execute("SELECT COUNT(DISTINCT AID), COUNT(*) FROM compound_assays")
    assert cursor.fetchone() == (len(aids), len(aids))


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

    monkeypatch.setattr(pubchem_loader.requests, "get", fake_get)

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
        pubchem_loader.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(1804316)

    assert activity["3779"]["types"] == {"Ki"}
    assert activity["3779"]["values"] == {
        "AID 1804316: Ki 1.891e+07 NANOMOLAR (Active)"
    }


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
        pubchem_loader.requests,
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
        pubchem_loader.requests,
        "get",
        lambda url, timeout: FakeResponse(text=assay_csv),
    )

    activity = pubchem_loader._fetch_assay_activity(1804316)

    assert activity["3779"]["types"] == {"Ki"}
    assert activity["3779"]["values"] == {
        "AID 1804316: Ki > 1.891e+07 NANOMOLAR (Active)"
    }
