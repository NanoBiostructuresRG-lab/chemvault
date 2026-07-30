# SPDX-License-Identifier: LGPL-3.0-or-later
import ast
from types import SimpleNamespace

from application.job_contracts import JobStatusContract
from services.job_models import JobStatus, JobType
from ui import dialogs, main_page


def _job(
    *,
    status=JobStatus.RUNNING,
    error=None,
    cancellable=True,
):
    return JobStatusContract(
        job_id="job-1",
        job_type=JobType.PUBCHEM_PROTEIN_SEARCH.value,
        status=status,
        database_id="test_db",
        stage="cid_collection",
        progress=0.5,
        message="Collecting CIDs",
        created_at="2026-07-27T10:00:00+00:00",
        started_at="2026-07-27T10:00:01+00:00",
        finished_at=None,
        error=error,
        cancellable=cancellable,
    )


def test_pubchem_job_status_renderer_is_owned_by_protein_dialog():
    assert callable(dialogs.render_pubchem_job_status)
    assert not hasattr(main_page, "render_pubchem_job_status")


def test_protein_dialog_uses_backend_gateway_without_local_job_service():
    source = dialogs.__loader__.get_source(dialogs.__name__)
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert "services.pubchem_job_service" not in imported_modules
    assert "services.uniprot_client" not in imported_modules
    assert "application.protein_identifiers" not in imported_modules
    assert "sqlite3" not in imported_modules
    assert "get_backend_gateway" in source
    assert "launch_pubchem_protein_search" in source
    assert "get_pubchem_protein_search_status" in source
    assert "cancel_pubchem_protein_search" in source
    assert "finalize_pubchem_protein_search" in source
    assert "list_uniprot_organisms" in source
    assert "resolve_gene_symbol" in source
    assert "Add to selection" not in source


def test_clear_pubchem_job_state_resets_dialog_tracking(monkeypatch):
    session_state = {
        "pubchem_job_id": "job-1",
        "pubchem_job_completion_handled": True,
        "selected_proteins": ["P34971"],
        "resolved_target": {"accession": "P34971"},
    }
    monkeypatch.setattr(dialogs.st, "session_state", session_state)

    dialogs._clear_pubchem_job_state()

    assert session_state == {
        "pubchem_job_id": "",
        "pubchem_job_completion_handled": False,
        "selected_proteins": [],
        "resolved_target": None,
    }


def test_gene_resolution_state_is_singular_and_traceable(monkeypatch):
    session_state = {
        "selected_proteins": [],
        "resolved_target": None,
    }
    monkeypatch.setattr(dialogs.st, "session_state", session_state)
    resolution = SimpleNamespace(
        gene_symbol="LEPR",
        organism_id=9606,
        organism_name="Homo sapiens",
        common_name="Human",
        accession="P48357",
        entry_name="LEPR_HUMAN",
        protein_name="Leptin receptor",
        reviewed=True,
    )

    payload = dialogs._store_resolved_target(resolution)

    assert payload["accession"] == "P48357"
    assert payload["gene_symbol"] == "LEPR"
    assert payload["organism_id"] == 9606
    assert session_state["selected_proteins"] == ["P48357"]


def test_current_target_accession_rejects_stale_gene_resolution(monkeypatch):
    session_state = {
        "target_input_mode": dialogs.GENE_SYMBOL_MODE,
        "input_gene_symbol": "LEPR",
        "selected_organism_id": 9606,
        "resolved_target": {
            "gene_symbol": "LEPR",
            "organism_id": 9606,
            "accession": "P48357",
        },
    }
    monkeypatch.setattr(dialogs.st, "session_state", session_state)

    assert dialogs._current_target_accession() == "P48357"
    session_state["input_gene_symbol"] = "MC4R"
    assert dialogs._current_target_accession() == ""


def test_direct_uniprot_accession_is_normalized(monkeypatch):
    monkeypatch.setattr(
        dialogs.st,
        "session_state",
        {
            "target_input_mode": dialogs.UNIPROT_ACCESSION_MODE,
            "input_protein": " p48357 ",
        },
    )

    assert dialogs._current_target_accession() == "P48357"


def test_accession_input_uses_non_stale_helper_text(monkeypatch):
    captions = []
    monkeypatch.setattr(
        dialogs.st,
        "text_input",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(dialogs.st, "caption", captions.append)

    dialogs._render_accession_target_input()

    assert captions == [
        "Enter one UniProt accession. CHEMVAULT will normalize it to "
        "uppercase and use it to search PubChem BioAssays."
    ]


def test_gene_target_identity_payload_preserves_resolver_provenance(
    monkeypatch,
):
    session_state = {
        "target_input_mode": dialogs.GENE_SYMBOL_MODE,
        "input_gene_symbol": "MC4R",
        "selected_organism_id": 9606,
        "resolved_target": {
            "gene_symbol": "MC4R",
            "organism_id": 9606,
            "organism_name": "Homo sapiens",
            "common_name": "Human",
            "accession": "P32245",
            "entry_name": "MC4R_HUMAN",
            "protein_name": "Melanocortin receptor 4",
            "reviewed": True,
        },
    }
    monkeypatch.setattr(dialogs.st, "session_state", session_state)

    assert dialogs._current_target_identity("P32245") == {
        "input_mode": "gene_symbol",
        "gene_symbol": "MC4R",
        "organism_id": 9606,
        "organism_name": "Homo sapiens",
        "common_name": "Human",
        "uniprot_accession": "P32245",
        "uniprot_entry_name": "MC4R_HUMAN",
        "protein_name": "Melanocortin receptor 4",
        "reviewed": True,
    }


def test_single_target_launch_never_accumulates_proteins(monkeypatch):
    calls = []

    class FakeGateway:
        def launch_pubchem_protein_search(
            self,
            database_id,
            proteins,
            target_identity,
        ):
            calls.append((database_id, proteins, target_identity))
            return SimpleNamespace(job_id="job-target")

    session_state = {
        "target_input_mode": dialogs.UNIPROT_ACCESSION_MODE,
        "input_protein": " p48357 ",
        "selected_proteins": ["OLD1", "OLD2"],
        "current_table": "",
        "pubchem_job_id": "",
        "pubchem_job_completion_handled": True,
    }
    monkeypatch.setattr(dialogs.st, "session_state", session_state)

    dialogs._launch_single_target_search(
        "target_db",
        " p48357 ",
        FakeGateway(),
    )

    assert calls == [
        (
            "target_db",
            ["P48357"],
            {
                "input_mode": "uniprot_accession",
                "uniprot_accession": "P48357",
            },
        )
    ]
    assert session_state["selected_proteins"] == ["P48357"]
    assert session_state["current_table"] == "main"
    assert session_state["pubchem_job_id"] == "job-target"
    assert session_state["pubchem_job_completion_handled"] is False


def test_database_locked_errors_are_detected_as_transient():
    assert dialogs._is_database_locked_error(
        RuntimeError("database is locked")
    )
    assert dialogs._is_database_locked_error(
        RuntimeError("database table is locked")
    )
    assert not dialogs._is_database_locked_error(
        RuntimeError("no such table: main")
    )


def test_cancelled_terminal_job_is_not_finalized(monkeypatch):
    class FakeGateway:
        def finalize_pubchem_protein_search(self, *_args):
            raise AssertionError(
                "cancelled job must not be finalized"
            )

    messages = []
    exits = []
    monkeypatch.setattr(
        dialogs.st,
        "session_state",
        {"pubchem_job_completion_handled": False},
    )
    monkeypatch.setattr(dialogs, "_render_job_snapshot", lambda job: None)
    monkeypatch.setattr(dialogs, "_render_job_dialog_exit", exits.append)
    monkeypatch.setattr(dialogs.st, "info", messages.append)

    dialogs._render_terminal_pubchem_job(
        "test_db",
        _job(status=JobStatus.CANCELLED, cancellable=False),
        FakeGateway(),
    )

    assert messages == ["Protein search cancelled."]
    assert exits == ["Close"]


def test_failed_terminal_job_is_not_finalized(monkeypatch):
    class FakeGateway:
        def finalize_pubchem_protein_search(self, *_args):
            raise AssertionError("failed job must not be finalized")

    messages = []
    exits = []
    monkeypatch.setattr(
        dialogs.st,
        "session_state",
        {"pubchem_job_completion_handled": False},
    )
    monkeypatch.setattr(dialogs, "_render_job_snapshot", lambda job: None)
    monkeypatch.setattr(dialogs, "_render_job_dialog_exit", exits.append)
    monkeypatch.setattr(dialogs.st, "error", messages.append)

    dialogs._render_terminal_pubchem_job(
        "test_db",
        _job(
            status=JobStatus.FAILED,
            error="worker failed",
            cancellable=False,
        ),
        FakeGateway(),
    )

    assert messages == ["The protein search failed: worker failed"]
    assert exits == ["Close"]


def test_completed_terminal_job_finalizes_once_through_gateway(monkeypatch):
    calls = []

    class FakeGateway:
        def finalize_pubchem_protein_search(self, database_id, job_id):
            calls.append(("finalize", database_id, job_id))
            return _job(
                status=JobStatus.COMPLETED,
                cancellable=False,
            )

    session_state = {
        "database_id": "test_db",
        "pubchem_job_completion_handled": False,
    }
    exits = []
    monkeypatch.setattr(dialogs.st, "session_state", session_state)
    monkeypatch.setattr(dialogs, "_render_job_snapshot", lambda job: None)
    monkeypatch.setattr(dialogs, "_render_job_dialog_exit", exits.append)
    monkeypatch.setattr(dialogs.st, "success", lambda message: None)
    monkeypatch.setattr(
        dialogs,
        "refresh_database_state",
        lambda state: calls.append(("refresh", state)),
    )

    completed = _job(
        status=JobStatus.COMPLETED,
        cancellable=False,
    )
    gateway = FakeGateway()
    dialogs._render_terminal_pubchem_job(
        "test_db",
        completed,
        gateway,
    )
    dialogs._render_terminal_pubchem_job(
        "test_db",
        completed,
        gateway,
    )

    assert calls == [
        ("finalize", "test_db", "job-1"),
        ("refresh", session_state),
    ]
    assert session_state["pubchem_job_completion_handled"] is True
    assert exits == ["Continue", "Continue"]
