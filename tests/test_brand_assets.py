# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import ast
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from streamlit.commands.page_config import _get_favicon_string

from ui import main_page

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_LOGO_NAMES = (
    "logo_black.svg",
    "logo_white.svg",
    "logo_cyan.svg",
)
LEGACY_LOGO_NAME = "chemvault" + "-logo.jpeg"


def test_official_svg_assets_are_valid_transparent_square_symbols():
    namespace = "{http://www.w3.org/2000/svg}"

    for filename in OFFICIAL_LOGO_NAMES:
        path = PROJECT_ROOT / "docs" / "assets" / filename
        root = ET.parse(path).getroot()

        assert root.tag == f"{namespace}svg"
        assert root.attrib["viewBox"] == "0 0 500 500"
        assert "width" not in root.attrib
        assert "height" not in root.attrib
        assert root.findall(f".//{namespace}path")
        assert not root.findall(f".//{namespace}text")
        assert not root.findall(f".//{namespace}image")
        assert not root.findall(f".//{namespace}script")
        assert not root.findall(f".//{namespace}rect")


def test_brand_asset_paths_are_cwd_independent_and_available(monkeypatch, tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert main_page.CHEMVAULT_LOGO_PATH.is_absolute()
    assert main_page.CHEMVAULT_FAVICON_PATH.is_absolute()
    assert main_page.CHEMVAULT_LOGO_PATH.name == "logo_black.svg"
    assert main_page.CHEMVAULT_FAVICON_PATH.name == "logo_cyan.svg"
    assert main_page.CHEMVAULT_LOGO_PATH.is_file()
    assert main_page.CHEMVAULT_FAVICON_PATH.is_file()


def test_installed_layout_brand_asset_resolution(monkeypatch, tmp_path):
    installed_root = tmp_path / "site-packages"
    module_path = installed_root / "ui" / "main_page.py"
    assets_path = installed_root / "docs" / "assets"
    assets_path.mkdir(parents=True)
    module_path.parent.mkdir(exist_ok=True)
    for filename in OFFICIAL_LOGO_NAMES:
        (assets_path / filename).touch()

    monkeypatch.setattr(main_page, "__file__", str(module_path))

    for filename in OFFICIAL_LOGO_NAMES:
        resolved = main_page.resolve_brand_asset(filename)
        assert resolved == assets_path / filename
        assert resolved.is_file()


def test_streamlit_favicon_accepts_official_svg_directly():
    favicon = _get_favicon_string(str(main_page.CHEMVAULT_FAVICON_PATH))

    assert favicon.startswith("data:image/svg+xml;base64,")


def test_app_configures_official_svg_favicon_without_pillow():
    app_path = PROJECT_ROOT / "app.py"
    source = app_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    page_config_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_page_config"
    ]

    assert len(page_config_calls) == 1
    page_icon = next(
        keyword.value
        for keyword in page_config_calls[0].keywords
        if keyword.arg == "page_icon"
    )
    assert ast.unparse(page_icon) == "str(CHEMVAULT_FAVICON_PATH)"
    assert "PIL" not in source
    assert "Image.open" not in source


def test_packaging_configuration_includes_all_official_svg_assets():
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    targets = configuration["tool"]["hatch"]["build"]["targets"]
    wheel_includes = set(targets["wheel"]["only-include"])
    sdist_includes = set(targets["sdist"]["only-include"])

    for filename in OFFICIAL_LOGO_NAMES:
        assert f"docs/assets/{filename}" in wheel_includes
    assert "docs" in sdist_includes


def test_active_branding_files_have_no_legacy_jpeg_references():
    active_files = (
        PROJECT_ROOT / "app.py",
        PROJECT_ROOT / "ui" / "main_page.py",
        PROJECT_ROOT / "docs" / "index.md",
        PROJECT_ROOT / "mkdocs.yml",
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "CHANGELOG.md",
    )

    assert not (PROJECT_ROOT / "docs" / "assets" / LEGACY_LOGO_NAME).exists()
    for path in active_files:
        assert LEGACY_LOGO_NAME not in path.read_text(encoding="utf-8")
