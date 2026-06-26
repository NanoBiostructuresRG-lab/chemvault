# SPDX-License-Identifier: LGPL-3.0-or-later
import csv
import io
import requests
import time

from services.activity_enrichment import (
    ensure_compound_activities_table,
    run_pubchem_activity_enrichment,
)

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
COMPOUND_ASSAYS_TABLE = "compound_assays"
REQUEST_TIMEOUT = (5, 60)
COMPOUND_NAME_BATCH_SIZE = 500
AID_CID_BATCH_SIZE = 50
MAX_ACTIVITY_AIDS = 50
SQLITE_WRITE_CHUNK_SIZE = 5000
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
STANDARD_ACTIVITY_COLUMNS = ("PubChem Standard Value", "Standard Value")
STANDARD_TYPE_COLUMNS = ("PubChem Standard Type", "Standard Type")
PUBCHEM_STANDARD_UNIT_COLUMNS = ("PubChem Standard Unit", "PubChem Standard Units")
STANDARD_UNIT_COLUMNS = ("Standard Unit", "Standard Units")
STANDARD_RELATION_COLUMNS = ("PubChem Standard Relation", "Standard Relation")
PUBCHEM_STAGE_LABELS = (
    ("aid_search", "AID search"),
    ("cid_collection", "CID collection"),
    ("compound_names", "Compound names"),
    ("sqlite_main_upsert", "SQLite main upsert"),
    ("compound_assays_insert", "compound_assays insert"),
    ("activity_enrichment", "Activity enrichment"),
)


def _new_stage_timings():
    return {key: 0.0 for key, _ in PUBCHEM_STAGE_LABELS}


def _print_pubchem_stage_timings(timings, total_elapsed):
    total_elapsed = max(total_elapsed, 0.0)
    denominator = total_elapsed if total_elapsed > 0 else 1.0
    for key, label in PUBCHEM_STAGE_LABELS:
        elapsed = timings.get(key, 0.0)
        percent = (elapsed / denominator) * 100
        print(f"{label + ':':<25} {elapsed:.1f}s ({percent:.0f}%)")
    print(f"{'Total:':<25} {total_elapsed:.1f}s")


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


def _ensure_compound_activities_table(cursor):
    ensure_compound_activities_table(cursor.connection)


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
    max_retries = 3
    initial_delay = 1.0
    backoff_multiplier = 2.0
    max_delay = 8.0

    def is_transient_error(error):
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in (429, 503):
            return True
        if status_code is not None:
            return False
        return isinstance(
            error,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ),
        )

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
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    response = requests.get(url, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    break
                except Exception as e:
                    if attempt >= max_retries or not is_transient_error(e):
                        raise
                    time.sleep(min(delay, max_delay))
                    delay = min(delay * backoff_multiplier, max_delay)
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
    normalized = column.strip().lower().replace("_", " ")
    if normalized.endswith(" qualifier"):
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


def _first_row_value(row, columns):
    for column in columns:
        value = row.get(column, "").strip()
        if value:
            return value
    return ""


def _standard_activity_column(row):
    for column in STANDARD_ACTIVITY_COLUMNS:
        value = row.get(column, "").strip()
        if value:
            return column
    return ""


def _activity_unit_map(rows, columns):
    for row in rows:
        if row.get("PUBCHEM_RESULT_TAG") == "RESULT_UNIT":
            return {column: row.get(column, "").strip() for column in columns}
    return {}


def _standard_activity_unit(row, units, source_column, activity_type=""):
    if source_column == "PubChem Standard Value":
        unit = units.get(source_column, "")
        if unit:
            return unit
        unit = _first_row_value(
            row,
            (*PUBCHEM_STANDARD_UNIT_COLUMNS, *STANDARD_UNIT_COLUMNS),
        )
        if unit:
            return unit
    if source_column == "Standard Value":
        unit = _first_row_value(
            row,
            (*STANDARD_UNIT_COLUMNS, *PUBCHEM_STANDARD_UNIT_COLUMNS),
        )
        if unit:
            return unit
        unit = units.get(source_column, "")
        if unit:
            return unit
    if activity_type == "Relative potency":
        return "dimensionless"
    return units.get(source_column, "")


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


def _numeric_activity_value(value):
    clean_value = str(value).strip().replace(",", "")
    if not clean_value:
        return None
    try:
        return float(clean_value)
    except ValueError:
        return None


def _activity_record(
    *,
    cid,
    aid,
    result_tag,
    activity_type,
    relation,
    raw_value,
    unit,
    outcome,
    source_column,
):
    numeric_value = _numeric_activity_value(raw_value)
    if numeric_value is None:
        return None
    return {
        "CID": str(cid),
        "AID": str(aid),
        "Activity_Type": activity_type,
        "Relation": relation,
        "Activity_Value": numeric_value,
        "Activity_Value_Raw": str(raw_value).strip(),
        "Unit": unit,
        "Outcome": outcome,
        "Source_Column": source_column,
        "Activity_Status": "enriched",
        "Result_Tag": str(result_tag),
    }


def _activity_qualifier(row, column):
    for qualifier_column in (f"{column}_Qualifier", f"{column} Qualifier"):
        qualifier = row.get(qualifier_column, "").strip()
        if qualifier:
            return qualifier
    return ""


def _standard_activity_relation(row, column):
    relation = _first_row_value(row, STANDARD_RELATION_COLUMNS)
    if relation:
        return relation
    return _activity_qualifier(row, column)


def _format_standard_activity_value(aid, column, value, standard_type, relation, unit, outcome):
    label = column
    if standard_type:
        label = f"{label} ({standard_type})"
    return _format_activity_value(aid, label, value, relation, unit, outcome)


def _has_unsupported_activity_value(row):
    metadata_columns = {
        *STANDARD_ACTIVITY_COLUMNS,
        *STANDARD_TYPE_COLUMNS,
        *PUBCHEM_STANDARD_UNIT_COLUMNS,
        *STANDARD_UNIT_COLUMNS,
        *STANDARD_RELATION_COLUMNS,
    }
    for column, value in row.items():
        normalized = column.strip().lower().replace("_", " ")
        if (
            not value.strip()
            or column.startswith("PUBCHEM_")
            or column in metadata_columns
            or normalized.endswith(" qualifier")
        ):
            continue
        return True
    return False


def _classify_activity_failure(row, activity_columns):
    outcome = row.get("PUBCHEM_ACTIVITY_OUTCOME", "").strip()
    has_supported_header = bool(activity_columns) or any(
        column in row for column in STANDARD_ACTIVITY_COLUMNS
    )
    if _has_unsupported_activity_value(row):
        return "unsupported_activity_column"
    if has_supported_header:
        return "no_numeric_value_for_cid" if not outcome else "outcome_only"
    if outcome:
        return "outcome_only"
    return "assay_has_no_quantitative_activity"


def _fetch_assay_activity(aid, raise_on_error=False):
    url = f"{BASE_URL}/assay/aid/{aid}/CSV"
    activity_by_cid = {}
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        columns = _activity_columns(reader.fieldnames or [])
        units = _activity_unit_map(rows, [*columns, *STANDARD_ACTIVITY_COLUMNS])

        for row in rows:
            result_tag = row.get("PUBCHEM_RESULT_TAG", "")
            cid = str(row.get("PUBCHEM_CID", "")).strip()
            if not result_tag.isdigit() or not cid:
                continue

            outcome = row.get("PUBCHEM_ACTIVITY_OUTCOME", "").strip()
            found_activity = False
            for column in columns:
                value = row.get(column, "").strip()
                if value == "":
                    continue
                qualifier = _activity_qualifier(row, column)
                activity = activity_by_cid.setdefault(
                    cid,
                    {"types": set(), "values": set(), "records": []},
                )
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
                record = _activity_record(
                    cid=cid,
                    aid=aid,
                    result_tag=result_tag,
                    activity_type=column,
                    relation=qualifier,
                    raw_value=value,
                    unit=units.get(column, ""),
                    outcome=outcome,
                    source_column=column,
                )
                if record is not None:
                    activity["records"].append(record)
                found_activity = True
                break

            if found_activity:
                continue

            standard_column = _standard_activity_column(row)
            if not standard_column:
                continue
            standard_type = _first_row_value(row, STANDARD_TYPE_COLUMNS)
            relation = _standard_activity_relation(row, standard_column)
            unit = _standard_activity_unit(
                row,
                units,
                standard_column,
                activity_type=standard_type,
            )
            activity = activity_by_cid.setdefault(
                cid,
                {"types": set(), "values": set(), "records": []},
            )
            activity["types"].add(standard_column)
            activity["values"].add(
                _format_standard_activity_value(
                    aid,
                    standard_column,
                    row.get(standard_column, "").strip(),
                    standard_type,
                    relation,
                    unit,
                    outcome,
                )
            )
            record = _activity_record(
                cid=cid,
                aid=aid,
                result_tag=result_tag,
                activity_type=standard_type or standard_column,
                relation=relation,
                raw_value=row.get(standard_column, "").strip(),
                unit=unit,
                outcome=outcome,
                source_column=standard_column,
            )
            if record is not None:
                activity["records"].append(record)
    except Exception as e:
        print(f"Error fetching activity for AID {aid}: {e}")
        if raise_on_error:
            raise
    return activity_by_cid


def fetch_pubchem_assay_activity(aid):
    return _fetch_assay_activity(aid, raise_on_error=True)


def _activity_status_for_record(cid, enriched_cids):
    if cid in enriched_cids:
        return "enriched"
    return "partial_or_failed"


def _collect_pubchem_records(connection, proteins, progreso, timings=None):
    if timings is None:
        timings = _new_stage_timings()

    protein_aids = {}
    stage_start = time.monotonic()
    for index, protein in enumerate(proteins, start=1):
        try:
            protein_aids[protein] = _fetch_aids_for_protein(protein)
        except Exception as e:
           print(f"Error con {protein}: {e}")
        _update_progress(progreso, 0.05 * (index / len(proteins)))
    timings["aid_search"] += time.monotonic() - stage_start

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
    stage_start = time.monotonic()
    cids_by_aid = _fetch_cids_for_aids(all_aids, progreso, start=0.05, end=0.55)
    records = {}
    for protein, aid in trabajos:
        for cid in cids_by_aid.get(str(aid), []):
            record = records.setdefault(
                cid,
                {
                    "aids": set(),
                    "proteins": set(),
                    "assays": set(),
                },
            )
            record["aids"].add(str(aid))
            record["proteins"].add(protein)
            record["assays"].add((cid, str(aid), protein))
    _update_progress(progreso, 0.60)
    timings["cid_collection"] += time.monotonic() - stage_start

    stage_start = time.monotonic()
    compound_names = _fetch_compound_names(records.keys(), progreso, start=0.60, end=0.85)
    timings["compound_names"] += time.monotonic() - stage_start

    aid_jobs = [
        {
            "protein": protein,
            "aid": str(aid),
            "cids": cids_by_aid.get(str(aid), []),
        }
        for protein, aid in trabajos
    ]

    def activity_progress_callback(snapshot):
        total_aids = snapshot.get("total_aids", 0)
        processed_aids = snapshot.get("processed_aids", 0)
        fraction = 1.0 if total_aids == 0 else processed_aids / total_aids
        _update_progress(progreso, 0.85 + (0.10 * fraction))

    def activity_fetcher(aid):
        return _fetch_assay_activity(aid, raise_on_error=True)

    stage_start = time.monotonic()
    activity_result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs,
        activity_fetcher,
        progress_callback=activity_progress_callback,
        continue_on_error=True,
        max_workers=4,
        rate_limit_per_second=4,
        max_retries=3,
        retry_initial_delay=1.0,
        retry_backoff_multiplier=2.0,
        retry_max_delay=8.0,
    )
    timings["activity_enrichment"] += time.monotonic() - stage_start
    enriched_cids = set(activity_result.get("successful_cid_values", []))

    for cid, record in records.items():
        record["compound_name"] = compound_names.get(cid, "")
        record["activity_status"] = _activity_status_for_record(cid, enriched_cids)
    _update_progress(progreso, 0.95)

    return records


def obtener_CIDs_Pubchem(connection, proteins, progreso):
    total_start = time.monotonic()
    timings = _new_stage_timings()
    cursor = connection.cursor()
    table = "main"

    _ensure_column(cursor, table, "CID")
    _ensure_column(cursor, table, "AIDs")
    _ensure_column(cursor, table, "Proteins")
    _ensure_column(cursor, table, "Compound_Name")
    _ensure_column(cursor, table, "Activity_Enrichment_Status")
    _ensure_compound_assays_table(cursor)
    _ensure_compound_activities_table(cursor)
    cursor.execute(f"""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_cid_unique
    ON {table}(CID)
    """)
    connection.commit()

    records = _collect_pubchem_records(connection, proteins, progreso, timings)

    total_records = len(records)
    record_items = list(records.items())

    main_upsert_sql = f"""
    INSERT INTO {table}
    (CID, AIDs, Proteins, Compound_Name, Activity_Enrichment_Status)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(CID) DO UPDATE SET
        AIDs = excluded.AIDs,
        Proteins = excluded.Proteins,
        Compound_Name = COALESCE(NULLIF({table}.Compound_Name, ''), excluded.Compound_Name),
        Activity_Enrichment_Status = excluded.Activity_Enrichment_Status
    """

    stage_start = time.monotonic()
    for chunk_index, chunk in enumerate(_batched(record_items, SQLITE_WRITE_CHUNK_SIZE), start=1):
        main_rows = [
            (
                cid,
                _join_values(record["aids"]),
                _join_values(record["proteins"]),
                record["compound_name"],
                record["activity_status"],
            )
            for cid, record in chunk
        ]
        cursor.executemany(main_upsert_sql, main_rows)

        if total_records:
            processed = min(chunk_index * SQLITE_WRITE_CHUNK_SIZE, total_records)
            fraction = processed / total_records
            _update_progress(progreso, 0.95 + (0.025 * fraction))

    timings["sqlite_main_upsert"] += time.monotonic() - stage_start

    compound_assays_insert_sql = f"""
    INSERT OR IGNORE INTO {COMPOUND_ASSAYS_TABLE}
    (CID, AID, Protein)
    VALUES (?, ?, ?)
    """

    total_assay_rows = sum(len(record["assays"]) for record in records.values())
    assay_rows_written = 0
    assay_buffer = []

    stage_start = time.monotonic()
    for record in records.values():
        assay_buffer.extend(record["assays"])

        if len(assay_buffer) >= SQLITE_WRITE_CHUNK_SIZE:
            cursor.executemany(compound_assays_insert_sql, assay_buffer)
            assay_rows_written += len(assay_buffer)
            assay_buffer = []

            if total_assay_rows:
                fraction = assay_rows_written / total_assay_rows
                _update_progress(progreso, 0.975 + (0.020 * fraction))

    if assay_buffer:
        cursor.executemany(compound_assays_insert_sql, assay_buffer)
        assay_rows_written += len(assay_buffer)

        if total_assay_rows:
            fraction = assay_rows_written / total_assay_rows
            _update_progress(progreso, 0.975 + (0.020 * fraction))

    timings["compound_assays_insert"] += time.monotonic() - stage_start

    connection.commit()
    _update_progress(progreso, 1.0)
    _print_pubchem_stage_timings(timings, time.monotonic() - total_start)


def run_pubchem_protein_search(connection, proteins, progress_callback):
    return obtener_CIDs_Pubchem(connection, proteins, progress_callback)


__all__ = [
    "obtener_CIDs_Pubchem",
    "run_pubchem_protein_search",
    "fetch_pubchem_assay_activity",
]
