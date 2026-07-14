# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

from harmonsmile import load_table
import pandas as pd

from modules import use_harmonsmile
from services.harmonsmile_cache import (
    merge_harmonsmile_cache_to_table,
    normalize_harmonsmile_result,
    upsert_harmonsmile_cache,
)


def test_harmonsmile_032_pubchem_ingest_returns_dataframe_contract(
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
                assert handle.read().splitlines() == ["CID", "1", "2"]
            loaded = load_table(self.cfg.input_path)
            loaded_input_columns.extend(loaded.columns)
            assert list(loaded.columns) == ["CID"]
            assert self.cfg.cid_col in loaded.columns
            return pd.DataFrame({
                "PubChem_CID": ["1", "2"],
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

    assert len(captured_configs) == 1
    captured_path = Path(captured_configs[0]["input_path"])
    assert captured_path.name == "res_pubchem.csv"
    assert captured_path.parent.name.startswith("ingest-")
    assert captured_path.parent.parent == tmp_path / "tempFilesHarmonsile"
    assert not captured_path.exists()
    assert captured_configs[0]["cid_col"] == "CID"
    assert captured_configs[0]["keep_extra_columns"] is True
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


def test_harmonsmile_invocations_use_isolated_temporary_csv_paths(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    barrier = Barrier(2)
    lock = Lock()
    observed_paths = []

    class FakePubChemConfig:
        def __init__(self, **kwargs):
            self.input_path = kwargs["input_path"]

    class FakePubChemIngest:
        def __init__(self, cfg):
            self.cfg = cfg

        def run(self):
            input_path = Path(self.cfg.input_path)
            cid = input_path.read_text(encoding="utf-8").splitlines()[1]
            with lock:
                observed_paths.append(input_path)
            barrier.wait(timeout=2)
            assert input_path.exists()
            return pd.DataFrame({"PubChem_CID": [cid]})

    monkeypatch.setattr(use_harmonsmile, "PubChemConfig", FakePubChemConfig)
    monkeypatch.setattr(use_harmonsmile, "PubChemIngest", FakePubChemIngest)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                use_harmonsmile.use_PubchemIngest,
                [pd.DataFrame({"CID": [1]}), pd.DataFrame({"CID": [2]})],
            )
        )

    assert {result.iloc[0]["PubChem_CID"] for result in results} == {"1", "2"}
    assert len(observed_paths) == 2
    assert observed_paths[0] != observed_paths[1]
    assert observed_paths[0].parent != observed_paths[1].parent
    assert all(not path.exists() for path in observed_paths)
    assert list((tmp_path / "tempFilesHarmonsile").iterdir()) == []


def test_harmonsmile_cache_preserves_032_status_message_and_inchi_fields():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany(
        'INSERT INTO "main" VALUES (?)',
        [("1",), ("2",), ("3",), ("4",)],
    )
    result = pd.DataFrame({
        "PubChem_CID": ["1", "2", "3", "4"],
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
