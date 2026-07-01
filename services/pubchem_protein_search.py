# SPDX-License-Identifier: LGPL-3.0-or-later
import csv
import io
import requests
import time

from services.activity_enrichment import (
    ensure_compound_activities_table,
    run_pubchem_activity_enrichment,
)
from services.job_models import JobNotActiveError, JobStatus, JobType
from services.job_store import JobStore
from services.pubchem_client import (
    fetch_aids_for_protein,
    fetch_assay_activity_csv,
    fetch_cids_for_aid_batch,
    fetch_compound_titles_for_cid_batch,
)
from services.pubchem_models import PUBCHEM_STAGE_LABELS, StageTimings
from services.pubchem_repository import (
    count_compound_assay_rows,
    ensure_pubchem_search_schema,
    insert_compound_assays_chunk,
    iter_compound_assay_chunks,
    iter_main_record_chunks,
    upsert_main_records_chunk,
)

COMPOUND_NAME_BATCH_SIZE = 500
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
STANDARD_ACTIVITY_COLUMNS = ("PubChem Standard Value", "Standard Value")
STANDARD_TYPE_COLUMNS = ("PubChem Standard Type", "Standard Type")
PUBCHEM_STANDARD_UNIT_COLUMNS = ("PubChem Standard Unit", "PubChem Standard Units")
STANDARD_UNIT_COLUMNS = ("Standard Unit", "Standard Units")
STANDARD_RELATION_COLUMNS = ("PubChem Standard Relation", "Standard Relation")

JOB_STAGE_PROGRESS = {
    "aid_search": (0.0, 0.05),
    "cid_collection": (0.05, 0.60),
    "compound_names": (0.60, 0.85),
    "activity_enrichment": (0.85, 0.95),
    "sqlite_main_upsert": (0.95, 0.975),
    "compound_assays_insert": (0.975, 0.995),
    "completed": (1.0, 1.0),
}

JOB_STAGE_MESSAGES = {
    "aid_search": "Searching PubChem AIDs",
    "cid_collection": "Collecting compound CIDs",
    "compound_names": "Fetching compound names",
    "activity_enrichment": "Enriching assay activity",
    "sqlite_main_upsert": "Updating main records",
    "compound_assays_insert": "Inserting compound assay records",
    "completed": "PubChem protein search completed",
}


class _JobTrackingProgress:
    def __init__(self, progress_callback, job_store, job_id):
        self.progress_callback = progress_callback
        self.job_store = job_store
        self.job_id = job_id
        self.stage = ""

    def check_active(self):
        job = self.job_store.heartbeat_job(self.job_id)
        if job is None:
            raise JobNotActiveError(f"Job is no longer active: {self.job_id}")

    def set_stage(self, stage):
        self.stage = stage
        progress = JOB_STAGE_PROGRESS[stage][0]
        job = self.job_store.update_progress(
            self.job_id,
            stage=stage,
            progress=progress,
            message=JOB_STAGE_MESSAGES[stage],
        )
        if job is None:
            raise JobNotActiveError(f"Job is no longer active: {self.job_id}")

    def progress(self, value):
        value = min(max(value, 0.0), 1.0)
        if self.progress_callback is not None:
            self.progress_callback.progress(value)
        if not self.stage:
            return
        lower, upper = JOB_STAGE_PROGRESS[self.stage]
        tracked_progress = min(max(value, lower), upper)
        job = self.job_store.update_progress(
            self.job_id,
            stage=self.stage,
            progress=tracked_progress,
            message=JOB_STAGE_MESSAGES[self.stage],
        )
        if job is None:
            raise JobNotActiveError(f"Job is no longer active: {self.job_id}")


def _new_stage_timings():
    return StageTimings()


def _print_pubchem_stage_timings(timings, total_elapsed):
    total_elapsed = max(total_elapsed, 0.0)
    denominator = total_elapsed if total_elapsed > 0 else 1.0
    for key, label in PUBCHEM_STAGE_LABELS:
        elapsed = timings.get(key, 0.0)
        percent = (elapsed / denominator) * 100
        print(f"{label + ':':<25} {elapsed:.1f}s ({percent:.0f}%)")
    print(f"{'Total:':<25} {total_elapsed:.1f}s")


def _batched(values, size):
    values = list(values)
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _update_progress(progreso, value):
    progreso.progress(min(max(value, 0.0), 1.0))


def _fetch_compound_names(
    cids,
    progreso=None,
    start=0.0,
    end=1.0,
    cancel_check=None,
):
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
        if cancel_check is not None:
            cancel_check()
        try:
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    data = fetch_compound_titles_for_cid_batch(batch)
                    break
                except Exception as e:
                    if attempt >= max_retries or not is_transient_error(e):
                        raise
                    if cancel_check is not None:
                        cancel_check()
                    time.sleep(min(delay, max_delay))
                    if cancel_check is not None:
                        cancel_check()
                    delay = min(delay * backoff_multiplier, max_delay)
            properties = data.get("PropertyTable", {}).get("Properties", [])
            for item in properties:
                cid = str(item.get("CID", "")).strip()
                title = str(item.get("Title", "")).strip()
                if cid and title:
                    compound_names[cid] = title
        except JobNotActiveError:
            raise
        except Exception as e:
            print(f"Error fetching compound names: {e}")
        if progreso is not None:
            fraction = index / len(batches)
            _update_progress(progreso, start + ((end - start) * fraction))
    return compound_names


def _fetch_aids_for_protein(protein):
    data = fetch_aids_for_protein(protein)
    return data["IdentifierList"]["AID"]


def _fetch_cids_for_aids(aids, progreso=None, start=0.0, end=1.0):
    cids_by_aid = {}
    batches = list(_batched(aids, AID_CID_BATCH_SIZE))
    if not batches:
        if progreso is not None:
            _update_progress(progreso, end)
        return cids_by_aid

    for index, batch in enumerate(batches, start=1):
        try:
            data = fetch_cids_for_aid_batch(batch)
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
    activity_by_cid = {}
    try:
        text = fetch_assay_activity_csv(aid)
        reader = csv.DictReader(io.StringIO(text))
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


def _collect_pubchem_records(
    connection,
    proteins,
    progreso,
    timings=None,
    stage_callback=None,
):
    if timings is None:
        timings = _new_stage_timings()

    protein_aids = {}
    if stage_callback is not None:
        stage_callback("aid_search")
    stage_start = time.monotonic()
    for index, protein in enumerate(proteins, start=1):
        try:
            protein_aids[protein] = _fetch_aids_for_protein(protein)
        except Exception as e:
           print(f"Error con {protein}: {e}")
        _update_progress(progreso, 0.05 * (index / len(proteins)))
    timings.add("aid_search", time.monotonic() - stage_start)

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
    if stage_callback is not None:
        stage_callback("cid_collection")
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
    timings.add("cid_collection", time.monotonic() - stage_start)

    if stage_callback is not None:
        stage_callback("compound_names")
    stage_start = time.monotonic()
    compound_names = _fetch_compound_names(
        records.keys(),
        progreso,
        start=0.60,
        end=0.85,
        cancel_check=getattr(progreso, "check_active", None),
    )
    timings.add("compound_names", time.monotonic() - stage_start)

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

    if stage_callback is not None:
        stage_callback("activity_enrichment")
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
    timings.add("activity_enrichment", time.monotonic() - stage_start)
    enriched_cids = set(activity_result.get("successful_cid_values", []))

    for cid, record in records.items():
        record["compound_name"] = compound_names.get(cid, "")
        record["activity_status"] = _activity_status_for_record(cid, enriched_cids)
    _update_progress(progreso, 0.95)

    return records


def _run_pubchem_protein_search(
    connection,
    proteins,
    progreso,
    stage_callback=None,
):
    total_start = time.monotonic()
    timings = _new_stage_timings()
    table = "main"

    ensure_pubchem_search_schema(connection, table)
    ensure_compound_activities_table(connection)

    records = _collect_pubchem_records(
        connection,
        proteins,
        progreso,
        timings,
        stage_callback=stage_callback,
    )

    total_records = len(records)
    main_rows_written = 0

    if stage_callback is not None:
        stage_callback("sqlite_main_upsert")
    stage_start = time.monotonic()
    for chunk in iter_main_record_chunks(records):
        main_rows_written += upsert_main_records_chunk(connection, chunk, table)

        if total_records:
            fraction = main_rows_written / total_records
            _update_progress(progreso, 0.95 + (0.025 * fraction))

    timings.add("sqlite_main_upsert", time.monotonic() - stage_start)

    total_assay_rows = count_compound_assay_rows(records)
    assay_rows_written = 0

    if stage_callback is not None:
        stage_callback("compound_assays_insert")
    stage_start = time.monotonic()
    for assay_chunk in iter_compound_assay_chunks(records):
        assay_rows_written += insert_compound_assays_chunk(connection, assay_chunk)

        if total_assay_rows:
            fraction = assay_rows_written / total_assay_rows
            _update_progress(progreso, 0.975 + (0.020 * fraction))

    timings.add("compound_assays_insert", time.monotonic() - stage_start)

    connection.commit()
    _update_progress(progreso, 1.0)
    _print_pubchem_stage_timings(timings, time.monotonic() - total_start)


def obtener_CIDs_Pubchem(connection, proteins, progreso):
    return _run_pubchem_protein_search(connection, proteins, progreso)


def run_pubchem_protein_search(connection, proteins, progress_callback):
    return obtener_CIDs_Pubchem(connection, proteins, progress_callback)


def run_pubchem_protein_search_job(
    connection,
    proteins,
    progress_callback=None,
    *,
    job_store=None,
    job_id=None,
    database_id="",
    metadata=None,
):
    """Run the search synchronously while persisting its job lifecycle."""
    store = job_store or JobStore(connection)
    job = store.get_job(job_id) if job_id is not None else None
    if job is None:
        job = store.create_job(
            job_type=JobType.PUBCHEM_PROTEIN_SEARCH,
            database_id=database_id,
            metadata=metadata,
            job_id=job_id,
        )

    try:
        started = store.start_job(job.job_id)
        if started is None or started.status != JobStatus.RUNNING.value:
            raise JobNotActiveError(f"Job could not be claimed: {job.job_id}")
        tracked_progress = _JobTrackingProgress(
            progress_callback,
            store,
            job.job_id,
        )
        _run_pubchem_protein_search(
            connection,
            proteins,
            tracked_progress,
            stage_callback=tracked_progress.set_stage,
        )
        tracked_progress.set_stage("completed")
        completed = store.complete_job(job.job_id)
        if completed is None:
            raise JobNotActiveError(f"Job is no longer active: {job.job_id}")
        return completed
    except JobNotActiveError:
        raise
    except Exception as error:
        store.fail_job(job.job_id, str(error))
        raise


__all__ = [
    "obtener_CIDs_Pubchem",
    "run_pubchem_protein_search",
    "run_pubchem_protein_search_job",
    "fetch_pubchem_assay_activity",
]
