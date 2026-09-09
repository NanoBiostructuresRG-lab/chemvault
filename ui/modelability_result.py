# SPDX-License-Identifier: LGPL-3.0-or-later
"""Main-content rendering for completed Modelability Index results."""

import html
from textwrap import dedent

import streamlit as st

from application.modelability_index import DEFAULT_FINGERPRINT_TYPE
from clients.backend_gateway import BackendGatewayError, get_backend_gateway
from ui.state_keys import MODELABILITY_FINGERPRINT_TYPE, MODELABILITY_RESULT
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
MURCKO_SCAFFOLD_DEFINITION_LABELS = {
    "bemis_murcko_atom_bond_aware": (
        "Bemis-Murcko, atom- and bond-aware"
    ),
}


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


def _murcko_analysis_detail_rows(provenance):
    rows = []

    scaffold_definition = provenance.get(
        "murcko_scaffold_definition"
    )
    if scaffold_definition not in (None, ""):
        rows.append(
            {
                "Group": "Murcko context",
                "Field": "Scaffold definition",
                "Value": MURCKO_SCAFFOLD_DEFINITION_LABELS.get(
                    scaffold_definition,
                    str(scaffold_definition),
                ),
            }
        )

    scaffold_chirality = provenance.get(
        "murcko_scaffold_chirality"
    )
    if scaffold_chirality is not None:
        rows.append(
            {
                "Group": "Murcko context",
                "Field": "Scaffold chirality",
                "Value": (
                    "Included"
                    if scaffold_chirality
                    else "Not included"
                ),
            }
        )

    contract = provenance.get(
        "murcko_context_contract_version"
    )
    if contract not in (None, ""):
        rows.append(
            {
                "Group": "Murcko context",
                "Field": "Contract",
                "Value": contract,
            }
        )

    return rows


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
    rows.extend(_murcko_analysis_detail_rows(provenance))
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


def _metric_group_html(title, values, *, row_size=None):
    values = tuple(values)

    if row_size is None:
        rows = (values,)
    else:
        rows = tuple(
            values[index:index + row_size]
            for index in range(0, len(values), row_size)
        )

    grids = []
    for index, row in enumerate(rows):
        tiles = "".join(
            _metric_tile_html(label, value)
            for label, value in row
        )
        margin = "margin-top: 0.4rem;" if index else "margin-top: 0;"
        grids.append(
            dedent(
                f"""
                <div style="
                    display: grid;
                    grid-template-columns:
                        repeat(auto-fit, minmax(120px, 1fr));
                    gap: 0.4rem;
                    {margin}
                ">{tiles}</div>
                """
            ).strip()
        )

    return dedent(
        f"""
        <div style="margin-top: 0.65rem;">
            <div style="
                margin-bottom: 0.3rem;
                font-size: 0.72rem;
                font-weight: 600;
                color: var(--cv-muted);
            ">{html.escape(str(title))}</div>
            {"".join(grids)}
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


def _optional_metric_text(value):
    if value is None:
        return "N/A"
    return f"{float(value):.3f}"


def structural_context_metric_groups(result):
    context = result.get("structural_context")
    if not isinstance(context, dict):
        return ()

    population = context.get("murcko_population")
    metrics = context.get("murcko_metrics")
    nn_interface = context.get("murcko_nn_interface")

    if not all(
        isinstance(section, dict)
        for section in (population, metrics, nn_interface)
    ):
        return ()

    scaffold_count = population.get("scaffold_count")

    return (
        (
            "Structural context",
            (
                (
                    "Murcko coverage",
                    _optional_metric_text(
                        population.get("murcko_coverage")
                    ),
                ),
                (
                    "Murcko scaffolds",
                    (
                        "N/A"
                        if scaffold_count is None
                        else str(scaffold_count)
                    ),
                ),
                (
                    "Shared-scaffold molecular coverage",
                    _optional_metric_text(
                        metrics.get("shared_molecular_coverage")
                    ),
                ),
                (
                    "Adjusted scaffold effect (ε²)",
                    _optional_metric_text(
                        metrics.get("epsilon_squared")
                    ),
                ),
                (
                    "Murcko NN coverage",
                    _optional_metric_text(
                        nn_interface.get("murcko_nn_coverage")
                    ),
                ),
                (
                    "Same-scaffold NN fraction",
                    _optional_metric_text(
                        nn_interface.get("same_scaffold_nn_fraction")
                    ),
                ),
            ),
        ),
    )


def _render_metrics(result):
    modelability_values = (
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
    )

    st.markdown(
        _metric_group_html(
            "Modelability",
            modelability_values,
        ),
        unsafe_allow_html=True,
    )

    for title, values in structural_context_metric_groups(result):
        st.markdown(
            _metric_group_html(
                title,
                values,
                row_size=3,
            ),
            unsafe_allow_html=True,
        )


def render_modelability_result_card(session_state, database_id, table_name):
    """Render the Modelability Index result subcard for the active table."""
    with st.container(border=True):
        st.markdown("**Modelability Index result**")
        fingerprint_type = session_state.get(
            MODELABILITY_FINGERPRINT_TYPE,
            DEFAULT_FINGERPRINT_TYPE,
        )
        scope_matches = modelability_scope_matches(
            session_state,
            database_id,
            table_name,
            fingerprint_type,
        )
        result = session_state.get(MODELABILITY_RESULT)
        if not scope_matches or not isinstance(result, dict):
            st.caption(
                "No Modelability Index result is available for this table."
            )
            return False

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
        diagnostics_column, fingerprints_column = st.columns(2)
        with diagnostics_column:
            st.download_button(
                "Download nearest-neighbor report",
                data=diagnostics_csv(result),
                file_name=f"{table_name}_modelability_diagnostics.csv",
                mime="text/csv",
                key=f"download_modelability_diagnostics_{table_name}",
            )
        analysis_identity = provenance.get("chemvault_analysis_hash")
        result_fingerprint_type = provenance.get(
            "fingerprint_type",
            DEFAULT_FINGERPRINT_TYPE,
        )
        if isinstance(analysis_identity, str) and analysis_identity:
            try:
                npz_bytes, npz_filename = (
                    get_backend_gateway().export_modelability_fingerprints(
                        database_id,
                        table_name,
                        analysis_identity,
                        fingerprint_type=result_fingerprint_type,
                    )
                )
            except BackendGatewayError as error:
                with fingerprints_column:
                    st.error(
                        "Modelability fingerprint download could not be prepared: "
                        f"{error}"
                    )
            else:
                with fingerprints_column:
                    st.download_button(
                        "Download fingerprints (.npz)",
                        data=npz_bytes,
                        file_name=npz_filename,
                        mime="application/octet-stream",
                        key=f"download_modelability_fingerprints_{table_name}",
                    )

        with st.expander("Analysis details", expanded=False):
            st.dataframe(
                analysis_detail_rows(provenance),
                hide_index=True,
                use_container_width=True,
            )
    return True
