# SPDX-License-Identifier: LGPL-3.0-or-later
from ui import sidebar


def test_build_card_uses_singular_target_language():
    source = sidebar.__loader__.get_source(sidebar.__name__)

    assert "Select Target" in source
    assert "Start from one gene or UniProt target" in source
    assert "Search Proteins" not in source
