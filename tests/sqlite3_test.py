import sqlite3

# Connect (creates file if it doesn't exist)
conn = sqlite3.connect("../SQL/example.db")

# Create a cursor to execute commands
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    age INTEGER
)
""")


cursor.execute("INSERT INTO users (name, age) VALUES (?, ?)", ("Alice", 25))

users = [("Bob", 30), ("Charlie", 22)]
cursor.executemany("INSERT INTO users (name, age) VALUES (?, ?)", users)

conn.commit()

cursor.execute("SELECT * FROM users")
rows = cursor.fetchall()

for row in rows:
    print(row)