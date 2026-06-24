# SPDX-License-Identifier: LGPL-3.0-or-later
import csv
import io
import requests

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
COMPOUND_ASSAYS_TABLE = "compound_assays"
REQUEST_TIMEOUT = (5, 60)
COMPOUND_NAME_BATCH_SIZE = 100
AID_CID_BATCH_SIZE = 50
MAX_ACTIVITY_AIDS = 50
ACTIVITY_KEYWORDS = (
    "IC50",
    "EC50",
    "AC50",
    "GI50",
    "LC50",
    "Ki",
    "Kd",
    "Potency",
)


def _ensure_column(cursor, table, column, column_type="TEXT"):
    columns = [row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _ensure_compound_assays_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {COMPOUND_ASSAYS_TABLE} (
            CID TEXT NOT NULL,
            AID TEXT NOT NULL,
            Protein TEXT NOT NULL,
            UNIQUE(CID, AID, Protein)
        )
    """)


def _join_values(values):
    clean_values = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(sorted(set(clean_values)))


def _batched(values, size):
    values = list(values)
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _update_progress(progreso, value):
    progreso.progress(min(max(value, 0.0), 1.0))


def _fetch_compound_names(cids, progreso=None, start=0.0, end=1.0):
    compound_names = {}
    batches = list(_batched(cids, COMPOUND_NAME_BATCH_SIZE))
    if not batches:
        if progreso is not None:
            _update_progress(progreso, end)
        return compound_names

    for index, batch in enumerate(batches, start=1):
        url = (
            f"{BASE_URL}/compound/cid/"
            f"{','.join(map(str, batch))}/property/Title/JSON"
        )
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            properties = data.get("PropertyTable", {}).get("Properties", [])
            for item in properties:
                cid = str(item.get("CID", "")).strip()
                title = str(item.get("Title", "")).strip()
                if cid and title:
                    compound_names[cid] = title
        except Exception as e:
            print(f"Error fetching compound names: {e}")
        if progreso is not None:
            fraction = index / len(batches)
            _update_progress(progreso, start + ((end - start) * fraction))
    return compound_names


def _fetch_aids_for_protein(protein):
    url = f"{BASE_URL}/assay/target/accession/{protein}/aids/JSON"
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data["IdentifierList"]["AID"]


def _fetch_cids_for_aids(aids, progreso=None, start=0.0, end=1.0):
    cids_by_aid = {}
    batches = list(_batched(aids, AID_CID_BATCH_SIZE))
    if not batches:
        if progreso is not None:
            _update_progress(progreso, end)
        return cids_by_aid

    for index, batch in enumerate(batches, start=1):
        url = (
            f"{BASE_URL}/assay/aid/"
            f"{','.join(map(str, batch))}/cids/JSON"
        )
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            for item in data.get("InformationList", {}).get("Information", []):
                aid = str(item.get("AID", batch[0] if len(batch) == 1 else "")).strip()
                cids = item.get("CID", [])
                if aid:
                    cids_by_aid[aid] = [str(cid) for cid in cids]
        except Exception as e:
            print(f"Error fetching CIDs for AID batch {batch}: {e}")
        if progreso is not None:
            fraction = index / len(batches)
            _update_progress(progreso, start + ((end - start) * fraction))
    return cids_by_aid


def _is_activity_column(column):
    if column.startswith("PUBCHEM_"):
        return False
    if column.endswith("_Qualifier"):
        return False
    return any(keyword.lower() in column.lower() for keyword in ACTIVITY_KEYWORDS)


def _activity_columns(fieldnames):
    columns = [column for column in fieldnames if _is_activity_column(column)]
    return sorted(
        columns,
        key=lambda column: next(
            index
            for index, keyword in enumerate(ACTIVITY_KEYWORDS)
            if keyword.lower() in column.lower()
        ),
    )


def _activity_unit_map(rows, columns):
    for row in rows:
        if row.get("PUBCHEM_RESULT_TAG") == "RESULT_UNIT":
            return {column: row.get(column, "").strip() for column in columns}
    return {}


def _format_activity_value(aid, column, value, qualifier, unit, outcome):
    parts = [f"AID {aid}: {column}"]
    if qualifier:
        parts.append(qualifier)
    parts.append(value)
    if unit and unit.upper() != "NONE":
        parts.append(unit)
    formatted = " ".join(parts)
    if outcome:
        formatted = f"{formatted} ({outcome})"
    return formatted


def _fetch_assay_activity(aid):
    url = f"{BASE_URL}/assay/aid/{aid}/CSV"
    activity_by_cid = {}
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        columns = _activity_columns(reader.fieldnames or [])
        units = _activity_unit_map(rows, columns)

        for row in rows:
            result_tag = row.get("PUBCHEM_RESULT_TAG", "")
            cid = str(row.get("PUBCHEM_CID", "")).strip()
            if not result_tag.isdigit() or not cid:
                continue

            outcome = row.get("PUBCHEM_ACTIVITY_OUTCOME", "").strip()
            for column in columns:
                value = row.get(column, "").strip()
                if value == "":
                    continue
                qualifier = row.get(f"{column}_Qualifier", "").strip()
                activity = activity_by_cid.setdefault(cid, {"types": set(), "values": set()})
                activity["types"].add(column)
                activity["values"].add(
                    _format_activity_value(
                        aid,
                        column,
                        value,
                        qualifier,
                        units.get(column, ""),
                        outcome,
                    )
                )
                break
    except Exception as e:
        print(f"Error fetching activity for AID {aid}: {e}")
    return activity_by_cid


def _activity_status_for_record(record, activity_was_skipped):
    if activity_was_skipped:
        return "skipped_aid_limit"
    if record["activity_values"]:
        return "enriched"
    return "partial_or_failed"


def _collect_pubchem_records(proteins, progreso):
    protein_aids = {}
    for index, protein in enumerate(proteins, start=1):
        try:
            protein_aids[protein] = _fetch_aids_for_protein(protein)
        except Exception as e:
           print(f"Error con {protein}: {e}")
        _update_progress(progreso, 0.05 * (index / len(proteins)))

    trabajos = [
        (protein, aid)
        for protein, aids in protein_aids.items()
        for aid in aids
    ]
    total_steps = len(trabajos)
    print(f"Total de AIDs: {total_steps}")
    if total_steps == 0:
        _update_progress(progreso, 1.0)
        return {}

    all_aids = [aid for _, aid in trabajos]
    cids_by_aid = _fetch_cids_for_aids(all_aids, progreso, start=0.05, end=0.55)
    records = {}
    for protein, aid in trabajos:
        for cid in cids_by_aid.get(str(aid), []):
            record = records.setdefault(
                cid,
                {
                    "aids": set(),
                    "proteins": set(),
                    "activity_types": set(),
                    "activity_values": set(),
                    "assays": set(),
                },
            )
            record["aids"].add(str(aid))
            record["proteins"].add(protein)
            record["assays"].add((cid, str(aid), protein))
    _update_progress(progreso, 0.60)

    compound_names = _fetch_compound_names(records.keys(), progreso, start=0.60, end=0.85)

    activity_was_skipped = total_steps > MAX_ACTIVITY_AIDS
    if total_steps > MAX_ACTIVITY_AIDS:
        print(
            "Skipping activity CSV enrichment for this protein search because "
            f"{total_steps} AIDs exceeds the limit of {MAX_ACTIVITY_AIDS}."
        )
    else:
        for step, (protein, aid) in enumerate(trabajos, start=1):
            activity_by_cid = _fetch_assay_activity(aid)
            for cid, activity in activity_by_cid.items():
                if cid in records:
                    records[cid]["activity_types"].update(activity["types"])
                    records[cid]["activity_values"].update(activity["values"])
            fraction = step / total_steps
            _update_progress(progreso, 0.85 + (0.10 * fraction))

    for cid, record in records.items():
        record["compound_name"] = compound_names.get(cid, "")
        record["activity_status"] = _activity_status_for_record(record, activity_was_skipped)
    _update_progress(progreso, 0.95)

    return records


def obtener_CIDs_Pubchem(connection, proteins, progreso):
    cursor = connection.cursor()
    table = "main"

    _ensure_column(cursor, table, "CID")
    _ensure_column(cursor, table, "AIDs")
    _ensure_column(cursor, table, "Proteins")
    _ensure_column(cursor, table, "Compound_Name")
    _ensure_column(cursor, table, "Activity_Type")
    _ensure_column(cursor, table, "Activity_Value")
    _ensure_column(cursor, table, "Activity_Enrichment_Status")
    _ensure_compound_assays_table(cursor)
    cursor.execute(f"""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_cid_unique
    ON {table}(CID)
    """)
    connection.commit()

    records = _collect_pubchem_records(proteins, progreso)
    total_records = len(records)
    for index, (cid, record) in enumerate(records.items(), start=1):
        cursor.execute(f"""
        INSERT INTO {table}
        (CID, AIDs, Proteins, Compound_Name, Activity_Type, Activity_Value, Activity_Enrichment_Status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(CID) DO UPDATE SET
            AIDs = excluded.AIDs,
            Proteins = excluded.Proteins,
            Compound_Name = COALESCE(NULLIF({table}.Compound_Name, ''), excluded.Compound_Name),
            Activity_Type = excluded.Activity_Type,
            Activity_Value = excluded.Activity_Value,
            Activity_Enrichment_Status = excluded.Activity_Enrichment_Status
        """, (
            cid,
            _join_values(record["aids"]),
            _join_values(record["proteins"]),
            record["compound_name"],
            _join_values(record["activity_types"]),
            _join_values(record["activity_values"]),
            record["activity_status"],
        ))
        cursor.executemany(
            f"""
            INSERT OR IGNORE INTO {COMPOUND_ASSAYS_TABLE}
            (CID, AID, Protein)
            VALUES (?, ?, ?)
            """,
            sorted(record["assays"]),
        )
        if total_records:
            fraction = index / total_records
            _update_progress(progreso, 0.95 + (0.05 * fraction))

    connection.commit()
    _update_progress(progreso, 1.0)
