# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3
import os

from harmonsmile import load_table
import pandas as pd

from modules import use_harmonsmile
from services.harmonsmile_cache import (
    merge_harmonsmile_cache_to_table,
    normalize_harmonsmile_result,
    upsert_harmonsmile_cache,
)


def test_harmonsmile_031_pubchem_ingest_returns_dataframe_contract(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    captured_configs = []
    loaded_input_columns = []

    class FakePubChemConfig:
        def __init__(self, **kwargs):
            captured_configs.append(kwargs)
            self.input_path = kwargs["input_path"]
            self.cid_col = kwargs["cid_col"]
            self.keep_extra_columns = kwargs["keep_extra_columns"]

    class FakePubChemIngest:
        def __init__(self, cfg):
            self.cfg = cfg

        def run(self):
            with open(self.cfg.input_path, encoding="utf-8") as handle:
                assert handle.readline().strip() == "CID,"
            loaded = load_table(self.cfg.input_path)
            loaded_input_columns.extend(loaded.columns)
            assert list(loaded.columns) == ["CID"]
            assert self.cfg.cid_col in loaded.columns
            return pd.DataFrame({
                "CID": ["1", "2"],
                "SMILES_RDKit": ["CCO", "C1=CC=CC=C1"],
                "SMILES_Harmonized": ["CCO", "c1ccccc1"],
                "SMILES_Harmonization_Status": ["ok", "ok_with_warnings"],
                "SMILES_Harmonization_Message": [None, "stereo_annotation_changed"],
                "InChI": ["InChI=1S/C2H6O", "InChI=1S/C6H6"],
                "InChIKey": ["LFQSCWFLJHTTHZ-UHFFFAOYSA-N", "UHOVQNZJYSORNB-UHFFFAOYSA-N"],
            })

    monkeypatch.setattr(use_harmonsmile, "PubChemConfig", FakePubChemConfig)
    monkeypatch.setattr(use_harmonsmile, "PubChemIngest", FakePubChemIngest)

    result = use_harmonsmile.use_PubchemIngest(pd.DataFrame({"CID": [1, 2]}))

    assert captured_configs == [{
        "input_path": os.path.join("tempFilesHarmonsile", "res_pubchem.csv"),
        "cid_col": "CID",
        "keep_extra_columns": True,
    }]
    assert loaded_input_columns == ["CID"]
    assert list(result.columns) == [
        "PubChem_CID",
        "SMILES_RDKit",
        "SMILES_Harmonized",
        "SMILES_Harmonization_Status",
        "SMILES_Harmonization_Message",
        "InChI",
        "InChIKey",
    ]


def test_harmonsmile_cache_preserves_031_status_message_and_inchi_fields():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany(
        'INSERT INTO "main" VALUES (?)',
        [("1",), ("2",), ("3",), ("4",)],
    )
    result = pd.DataFrame({
        "PubChem CID": ["1", "2", "3", "4"],
        "SMILES_RDKit": ["CCO", "C[NH3+]", None, None],
        "SMILES_Harmonized": ["CCO", "CN", None, None],
        "SMILES_Harmonization_Status": [
            "ok",
            "ok_with_warnings",
            "unsupported",
            "failed",
        ],
        "SMILES_Harmonization_Message": [
            None,
            "normalization/charge standardization applied",
            "unsupported elements: Fe",
            "invalid SMILES",
        ],
        "InChI": ["InChI=1S/C2H6O", "InChI=1S/CH5N", None, None],
        "InChIKey": ["LFQSCWFLJHTTHZ-UHFFFAOYSA-N", "BAVYZALUXZFZLV-UHFFFAOYSA-N", None, None],
    })

    normalized = normalize_harmonsmile_result(result)
    assert set(normalized["SMILES_Harmonization_Status"]) == {
        "ok",
        "ok_with_warnings",
        "unsupported",
        "failed",
    }

    assert upsert_harmonsmile_cache(connection, result) == 4
    assert merge_harmonsmile_cache_to_table(connection, "main", "CID") == 4

    rows = connection.execute(
        """
        SELECT
            CID,
            SMILES_RDKit,
            SMILES_Harmonized,
            SMILES_Harmonization_Status,
            SMILES_Harmonization_Message,
            InChI,
            InChIKey
        FROM main
        ORDER BY CID
        """
    ).fetchall()

    assert rows[0][1:] == (
        "CCO",
        "CCO",
        "ok",
        None,
        "InChI=1S/C2H6O",
        "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    )
    assert rows[1][3] == "ok_with_warnings"
    assert rows[2][3:] == ("unsupported", "unsupported elements: Fe", None, None)
    assert rows[3][3:] == ("failed", "invalid SMILES", None, None)
