# SPDX-License-Identifier: LGPL-3.0-or-later
def quote_identifier(identifier):
    """Quote a SQLite identifier such as a table or column name."""
    return '"' + str(identifier).replace('"', '""') + '"'


def is_valid_table_name(table_name):
    if not table_name:
        return False
    return str(table_name).replace("_", "").isalnum() and not str(table_name)[0].isdigit()


def is_user_facing_table_name(table_name):
    """Return whether a physical SQLite table belongs in user workflows."""
    name = str(table_name)
    return not (
        name.startswith("_chemvault_")
        or name.startswith("sqlite_")
        or name in {"compound_assays", "compound_activities"}
    )


def table_exists(connection, table_name):
    cursor = connection.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def get_tables_from_connection(connection):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        ORDER BY name
    """)
    return [
        row[0]
        for row in cursor.fetchall()
        if is_user_facing_table_name(row[0])
    ]


def ensure_main_table(connection):
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS "main" (
            primary_id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    ''')
    connection.commit()
