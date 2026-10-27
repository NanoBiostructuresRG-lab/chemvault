# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import inspect
from contextlib import nullcontext
from pathlib import Path

import pytest

from ui import main_page, sidebar


def test_build_card_uses_singular_target_language():
    source = sidebar.__loader__.get_source(sidebar.__name__)

    assert "Select Target" in source
    assert "Start from one gene or UniProt target" in source
    assert "Search Proteins" not in source


def test_application_identity_uses_approved_subtitle(monkeypatch):
    rendered = []
    images = []

    class Container:
        def columns(self, *_args, **_kwargs):
            return nullcontext(), nullcontext()

    monkeypatch.setattr(
        main_page.st,
        "image",
        lambda *args, **kwargs: images.append((args, kwargs)),
    )
    monkeypatch.setattr(
        main_page.st,
        "markdown",
        lambda value, **_kwargs: rendered.append(value),
    )

    main_page.render_app_identity(Container())

    assert images == [
        ((main_page.CHEMVAULT_LOGO_PATH,), {"width": "stretch"}),
    ]
    assert main_page.CHEMVAULT_LOGO_PATH.name == "logo_black.svg"
    identity = "\n".join(rendered)
    assert (
        "Traceable Target-Centered Bioactivity Dataset Construction "
        "and Modelability Assessment"
    ) in identity
    assert "Target-centered bioactivity dataset curation from PubChem" not in identity
    assert "A Cheminformatics Application for" not in identity


def _set_module_location(monkeypatch, root: Path) -> Path:
    module_path = root / "ui" / "sidebar.py"
    monkeypatch.setattr(sidebar, "__file__", str(module_path))
    return root / "pyproject.toml"


def test_source_version_comes_from_project_metadata_independent_of_cwd(
    monkeypatch,
    tmp_path,
):
    project_root = tmp_path / "source"
    project_root.mkdir()
    project_path = _set_module_location(monkeypatch, project_root)
    project_path.write_text(
        '[project]\nname = "ChemVault"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.setattr(
        sidebar.importlib.metadata,
        "version",
        lambda _name: pytest.fail("source metadata must take precedence"),
    )

    assert sidebar.resolve_application_version() == "1.2.3"
    assert Path.cwd() == unrelated_cwd


def test_installed_version_comes_from_distribution_metadata_when_source_is_absent(
    monkeypatch,
    tmp_path,
):
    _set_module_location(monkeypatch, tmp_path / "site-packages")
    requested = []

    def distribution_version(name):
        requested.append(name)
        return "2.3.4"

    monkeypatch.setattr(sidebar.importlib.metadata, "version", distribution_version)

    assert sidebar.resolve_application_version() == "2.3.4"
    assert requested == ["ChemVault"]


@pytest.mark.parametrize(
    ("project_text", "message"),
    [
        ('[project]\nname = "Other"\nversion = "1.2.3"\n', "does not identify"),
        ('[project]\nname = "ChemVault"\n', "source version metadata is unavailable"),
        ('[project\nname = "ChemVault"\n', "source version metadata is invalid"),
    ],
)
def test_invalid_source_version_metadata_is_explicit(
    monkeypatch,
    tmp_path,
    project_text,
    message,
):
    project_path = _set_module_location(monkeypatch, tmp_path)
    project_path.write_text(project_text, encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        sidebar.resolve_application_version()


def test_missing_installed_version_metadata_is_explicit(monkeypatch, tmp_path):
    _set_module_location(monkeypatch, tmp_path / "site-packages")

    def unavailable(_name):
        raise sidebar.importlib.metadata.PackageNotFoundError("ChemVault")

    monkeypatch.setattr(sidebar.importlib.metadata, "version", unavailable)

    with pytest.raises(RuntimeError, match="distribution version metadata is unavailable"):
        sidebar.resolve_application_version()


def test_about_card_renders_github_identity_link_and_prefixed_version(monkeypatch):
    rendered = {"containers": [], "subheaders": [], "markdown": []}
    monkeypatch.setattr(
        sidebar.st,
        "container",
        lambda **kwargs: rendered["containers"].append(kwargs) or nullcontext(),
    )
    monkeypatch.setattr(sidebar.st, "subheader", rendered["subheaders"].append)
    monkeypatch.setattr(
        sidebar.st,
        "markdown",
        lambda value, **kwargs: rendered["markdown"].append((value, kwargs)),
    )
    monkeypatch.setattr(sidebar, "resolve_application_version", lambda: "1.2.3")

    sidebar.render_about_card()

    link_html, link_kwargs = rendered["markdown"][0]
    assert rendered["containers"] == [{"border": True}]
    assert rendered["subheaders"] == ["About"]
    assert sidebar.GITHUB_REPOSITORY_URL in link_html
    assert "<svg" in link_html
    assert 'aria-label="GitHub"' in link_html
    assert "GitHub repository" in link_html
    assert link_kwargs == {"unsafe_allow_html": True}
    assert rendered["markdown"][1] == ("**Version:** v1.2.3", {})


@pytest.mark.parametrize(
    ("database_id", "current_table", "expected_first"),
    [("", "", "build"), ("active", "main", "refine")],
)
def test_about_card_follows_export_independent_of_database_selection(
    monkeypatch,
    database_id,
    current_table,
    expected_first,
):
    calls = []
    monkeypatch.setattr(sidebar.st, "sidebar", nullcontext())
    monkeypatch.setattr(sidebar.st, "header", lambda _value: None)
    monkeypatch.setattr(
        sidebar.st,
        "session_state",
        {"database_id": database_id, "current_table": current_table},
    )
    monkeypatch.setattr(sidebar, "count_rows", lambda *_args: 1)
    monkeypatch.setattr(sidebar, "get_connection", lambda *_args: object())
    monkeypatch.setattr(sidebar, "render_build_card", lambda *_args: calls.append("build"))
    monkeypatch.setattr(sidebar, "render_refine_card", lambda *_args: calls.append("refine"))
    monkeypatch.setattr(sidebar, "render_curate_card", lambda: calls.append("curate"))
    monkeypatch.setattr(sidebar, "render_export_card", lambda: calls.append("export"))
    monkeypatch.setattr(sidebar, "render_about_card", lambda: calls.append("about"))

    sidebar.render_sidebar(lambda: None, lambda: None, lambda: None)

    assert calls == [expected_first, "curate", "export", "about"]


def test_application_version_is_not_hardcoded_in_sidebar():
    source = inspect.getsource(sidebar)

    assert '"v0.14.7"' not in source
    assert "'v0.14.7'" not in source
