# SPDX-License-Identifier: LGPL-3.0-or-later
from ui import dialogs, main_page


def test_pubchem_job_status_renderer_is_owned_by_protein_dialog():
    assert callable(dialogs.render_pubchem_job_status)
    assert not hasattr(main_page, "render_pubchem_job_status")


def test_clear_pubchem_job_state_resets_dialog_tracking(monkeypatch):
    session_state = {
        "pubchem_job_id": "job-1",
        "pubchem_job_db_path": "SQL/test.db",
        "pubchem_job_completion_handled": True,
        "selected_proteins": ["P34971"],
    }
    monkeypatch.setattr(dialogs.st, "session_state", session_state)

    dialogs._clear_pubchem_job_state()

    assert session_state == {
        "pubchem_job_id": "",
        "pubchem_job_db_path": "",
        "pubchem_job_completion_handled": False,
        "selected_proteins": [],
    }
