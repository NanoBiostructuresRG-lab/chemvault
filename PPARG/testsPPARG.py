import sqlite3
import pandas as pd

def query_to_dataframe(db_path, query):
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query(query, con)
    con.close()
    return df


# Ejemplo de uso
print(query_to_dataframe("5468_PPARG",
"""
SELECT Bioactivity_ID, Activity, Activity_Type, Activity_Value 
FROM main LIMIT 500
"""
))