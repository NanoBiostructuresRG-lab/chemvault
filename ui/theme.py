# SPDX-License-Identifier: LGPL-3.0-or-later
import streamlit as st


def apply_global_theme():
    st.markdown(
        """
        <style>
            :root {
                --cv-bg: #ffffff;
                --cv-panel-bg: #ffffff;
                --cv-sidebar-bg: #f8fafc;
                --cv-muted-bg: #f3f4f6;
                --cv-border: #d6dbe1;
                --cv-border-strong: rgba(71, 85, 105, 0.24);
                --cv-text: #111827;
                --cv-heading: #1f2937;
                --cv-muted: #6b7280;
                --cv-link: #4b5563;
                --cv-control-border: #64748b;
                --cv-accent: #b45309;
                --cv-accent-text: #78350f;
                --cv-accent-bg: #fff7ed;
                --cv-code-bg: #111827;
                --cv-code-text: #f9fafb;
                --cv-shadow-soft: 0 8px 24px rgba(15, 23, 42, 0.04);
                --cv-radius: 0.55rem;
            }

            section[data-testid="stSidebar"] {
                background-color: var(--cv-sidebar-bg);
            }

            section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
                gap: 0.8rem;
            }

            section[data-testid="stSidebar"] h1,
            section[data-testid="stSidebar"] h2,
            section[data-testid="stSidebar"] h3 {
                color: var(--cv-heading);
            }

            section[data-testid="stSidebar"] h2,
            section[data-testid="stSidebar"] h3 {
                margin-bottom: 0.15rem;
            }

            section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
                color: var(--cv-muted);
                line-height: 1.35;
            }

            section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
                background-color: var(--cv-panel-bg);
                border-color: var(--cv-border-strong);
                box-shadow: var(--cv-shadow-soft);
                border-radius: var(--cv-radius);
            }

            section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {
                gap: 0.55rem;
            }

            section[data-testid="stSidebar"] div[data-testid="stButton"],
            section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] {
                width: 100%;
            }

            section[data-testid="stSidebar"] div[data-testid="stButton"] > button,
            section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button {
                width: 100%;
                justify-content: center;
                border-color: var(--cv-control-border);
                color: var(--cv-heading);
                background-color: var(--cv-panel-bg);
                min-height: 2.35rem;
            }

            section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover,
            section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button:hover {
                border-color: var(--cv-accent);
                color: var(--cv-accent-text);
                background-color: var(--cv-accent-bg);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
