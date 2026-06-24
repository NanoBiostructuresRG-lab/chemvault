# SPDX-License-Identifier: LGPL-3.0-or-later
def quote_identifier(identifier):
    """Quote a SQLite identifier such as a table or column name."""
    return '"' + str(identifier).replace('"', '""') + '"'


def is_valid_table_name(table_name):
    if not table_name:
        return False
    return str(table_name).replace("_", "").isalnum() and not str(table_name)[0].isdigit()


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
        AND name NOT LIKE 'sqlite_%'
        AND name != '_chemvault_table_metadata'
        AND name != '_chemvault_operation_log'
        AND name != '_chemvault_harmonsmile_cache'
        AND name != 'compound_assays'
        AND name != 'compound_activities'
        ORDER BY name
    """)
    return [row[0] for row in cursor.fetchall()]


def ensure_main_table(connection):
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS "main" (
            primary_id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    ''')
    connection.commit()
