# SPDX-License-Identifier: LGPL-3.0-or-later
"""Main-content rendering for completed Modelability Index results."""

import html
from textwrap import dedent

import streamlit as st

from state_keys import MODELABILITY_RESULT
from ui.modelability_state import diagnostics_csv, modelability_scope_matches


DIAGNOSTICS_PREVIEW_ROWS = 10
ANALYSIS_DETAIL_FIELDS = (
    ("Method", "Similarity metric", "similarity_metric"),
    ("Method", "Neighbor rule", "neighbor_rule"),
    ("Method", "Tie policy", "tie_policy"),
    ("Method", "Aggregation method", "aggregation"),
    ("Software", "MOLRAPTOR version", "molraptor_version"),
    ("Software", "RDKit version", "rdkit_version"),
)


def _available_rows(provenance, fields):
    rows = []
    for group, label, key in fields:
        value = provenance.get(key)
        if value in (None, ""):
            continue
        rows.append({"Group": group, "Field": label, "Value": value})
    return rows


def _profile_text(value):
    return str(value).replace("-", " ").replace("_", " ").capitalize()


def analysis_detail_rows(provenance):
    rows = []
    profile = provenance.get("fingerprint_profile")
    if isinstance(profile, dict):
        algorithm = (
            profile.get("algorithm")
            or profile.get("fingerprint_type")
            or profile.get("type")
        )
        if algorithm:
            rows.append(
                {
                    "Group": "Fingerprint",
                    "Field": "Algorithm",
                    "Value": _profile_text(algorithm),
                }
            )

        output_type = profile.get("output_type")
        if output_type:
            rows.append(
                {
                    "Group": "Fingerprint",
                    "Field": "Output type",
                    "Value": _profile_text(output_type),
                }
            )

        fingerprint_size = profile.get("fp_size", profile.get("n_bits"))
        if fingerprint_size not in (None, ""):
            rows.append(
                {
                    "Group": "Fingerprint",
                    "Field": "Fingerprint size",
                    "Value": f"{fingerprint_size} bits",
                }
            )

        radius = profile.get("radius")
        if radius not in (None, ""):
            rows.append(
                {
                    "Group": "Fingerprint",
                    "Field": "Radius",
                    "Value": radius,
                }
            )

        boolean_fields = (
            ("Chirality", "include_chirality", "Included", "Not included"),
            (
                "Ring membership",
                "include_ring_membership",
                "Included",
                "Not included",
            ),
            ("Bond types", "use_bond_types", "Used", "Not used"),
        )
        for label, key, enabled_text, disabled_text in boolean_fields:
            if key in profile and profile[key] is not None:
                rows.append(
                    {
                        "Group": "Fingerprint",
                        "Field": label,
                        "Value": (
                            enabled_text if profile[key] else disabled_text
                        ),
                    }
                )

    rows.extend(_available_rows(provenance, ANALYSIS_DETAIL_FIELDS))
    return rows


def _metric_tile_html(label, value):
    return dedent(
        f"""
        <div style="
            min-width: 0;
            padding: 0.45rem 0.55rem;
            border: 1px solid var(--cv-border);
            border-radius: 0.4rem;
            background: var(--cv-muted-bg);
        ">
            <div style="font-size: 0.68rem; color: var(--cv-muted);">
                {html.escape(str(label))}
            </div>
            <div style="
                margin-top: 0.08rem;
                font-size: 0.94rem;
                font-weight: 600;
                color: var(--cv-heading);
            ">
                {html.escape(str(value))}
            </div>
        </div>
        """
    ).strip()


def _metric_group_html(title, values):
    tiles = "".join(_metric_tile_html(label, value) for label, value in values)
    return dedent(
        f"""
        <div style="margin-top: 0.65rem;">
            <div style="
                margin-bottom: 0.3rem;
                font-size: 0.72rem;
                font-weight: 600;
                color: var(--cv-muted);
            ">{html.escape(str(title))}</div>
            <div style="
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
                gap: 0.4rem;
            ">{tiles}</div>
        </div>
        """
    ).strip()


def _diagnostics_section_heading_html():
    return dedent(
        """
        <p data-cv-modelability-diagnostics-heading style="margin-top: 1.5rem;">
            <strong>Nearest-neighbor diagnostics</strong>
        </p>
        """
    ).strip()


def _render_metrics(result):
    groups = (
        (
            "Modelability",
            (
                (
                    "Modelability Index",
                    f'{float(result.get("modelability_index", 0.0)):.3f}',
                ),
                (
                    "Active Concordance",
                    f'{float(result.get("active_concordance", 0.0)):.3f}',
                ),
                (
                    "Inactive Concordance",
                    f'{float(result.get("inactive_concordance", 0.0)):.3f}',
                ),
            ),
        ),
    )
    for title, values in groups:
        st.markdown(
            _metric_group_html(title, values),
            unsafe_allow_html=True,
        )


def render_modelability_result_card(session_state, database_id, table_name):
    """Render only the completed result owned by the active table scope."""
    if not modelability_scope_matches(session_state, database_id, table_name):
        return False
    result = session_state.get(MODELABILITY_RESULT)
    if not isinstance(result, dict):
        return False

    with st.container(border=True):
        st.markdown("**Modelability Index result**")
        provenance = result.get("provenance", {})
        source_table = provenance.get("source_table")
        if source_table:
            st.caption(f"Calculated from: {source_table}")
        _render_metrics(result)

        diagnostics = result.get("diagnostics", ())
        st.markdown(
            _diagnostics_section_heading_html(),
            unsafe_allow_html=True,
        )
        st.caption(
            "Preview of nearest-neighbor comparisons used in the "
            "Modelability Index calculation."
        )
        st.dataframe(
            list(diagnostics)[:DIAGNOSTICS_PREVIEW_ROWS],
            hide_index=True,
            use_container_width=True,
        )
        st.download_button(
            "Download nearest-neighbor report",
            data=diagnostics_csv(result),
            file_name=f"{table_name}_modelability_diagnostics.csv",
            mime="text/csv",
            key=f"download_modelability_diagnostics_{table_name}",
        )

        with st.expander("Analysis details", expanded=False):
            st.dataframe(
                analysis_detail_rows(provenance),
                hide_index=True,
                use_container_width=True,
            )
    return True
