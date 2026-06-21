import html
import streamlit as st

def render_app_identity(container):
    col_logo, col_titulo = container.columns([0.12, 0.88], vertical_alignment="center")

    with col_logo:
        st.image("assets/logo.jpeg", use_container_width=True)

    with col_titulo:
        st.markdown(
            """
            <div style="padding: 0.15rem 0;">
                <div style="
                    font-size: 2.45rem;
                    line-height: 1.05;
                    font-weight: 700;
                    color: var(--cv-heading);
                ">
                    ChemVault
                </div>
                <div style="margin-top: 0.25rem; font-size: 0.98rem; color: var(--cv-muted);">
                    Molecular dataset construction, curation, and export workspace.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_database_metrics(container, database_id, current_table, row_count, group_count):
    container.markdown(
        f"""
        <div style="
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 0.35rem 1.5rem;
            margin: 0.7rem 0 1rem 0;
            padding: 0.85rem 0;
            border-top: 1px solid var(--cv-border);
            border-bottom: 1px solid var(--cv-border);
        ">
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Database</div>
                <div style="
                    font-size: 0.95rem;
                    color: var(--cv-text);
                    overflow-wrap: anywhere;
                ">{html.escape(database_id)}</div>
            </div>
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Table</div>
                <div style="font-size: 0.95rem; color: var(--cv-text);">{html.escape(current_table)}</div>
            </div>
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Rows</div>
                <div style="font-size: 0.95rem; color: var(--cv-text);">{row_count}</div>
            </div>
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Unique groups</div>
                <div style="font-size: 0.95rem; color: var(--cv-text);">{group_count}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer():
    st.markdown(
        """
        <footer style="
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid var(--cv-border);
            text-align: center;
            color: var(--cv-muted);
            font-size: 0.85rem;
            line-height: 1.6;
        ">
            <div>D.R. © ChemVault 2026</div>
            <div>
                Developed by the
                <a href="https://nanobiostructuresrg.github.io/" style="color: var(--cv-link);">
                    Nano]°[Biostructures RG
                </a>
                at Tecnológico de Monterrey.
            </div>
        </footer>
        """,
        unsafe_allow_html=True,
    )
