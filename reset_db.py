import sqlite3
from pathlib import Path

DB_PATH = Path("fee.db")

# Delete old file if exists
if DB_PATH.exists():
    DB_PATH.unlink()
    print("Old database removed.")

# Create new database + table
conn = sqlite3.connect(DB_PATH)
conn.execute("""
CREATE TABLE students (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    total_amount REAL NOT NULL,
    balance_amount REAL NOT NULL,
    password_hash TEXT NOT NULL
);
""")
conn.commit()
conn.close()
print("✅ New database created successfully with 'students' table.")
