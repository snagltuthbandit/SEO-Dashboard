"""SQLite connection + schema management."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "citations.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    run_date TEXT,
    prompt_id TEXT,
    prompt_text TEXT,
    engine TEXT,
    raw_response TEXT,
    citations_json TEXT
);

CREATE TABLE IF NOT EXISTS mentions (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES runs(id),
    entity_name TEXT,
    mentioned INTEGER,
    position TEXT,
    is_recommended INTEGER,
    mention_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_runs_date ON runs(run_date);
CREATE INDEX IF NOT EXISTS idx_mentions_run_id ON mentions(run_id);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_name);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized schema at {DB_PATH}")
