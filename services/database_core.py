# SPDX-License-Identifier: LGPL-3.0-or-later
"""Streamlit-independent SQLite connection helpers."""
import sqlite3
from pathlib import Path


def get_connection(db_name, db_dir="SQL"):
    db_path = Path(db_dir) / f"{db_name}.db"
    return sqlite3.connect(db_path, check_same_thread=False)
