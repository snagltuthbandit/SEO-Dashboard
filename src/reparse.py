"""Re-run the parser over stored raw responses, rebuilding the mentions table.

Raw API responses are stored in full precisely so detection logic can improve
without re-spending API calls (see build brief). Run this after changing
parser.py or the competitors config:

    python3 src/reparse.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, parser


def main() -> None:
    entities = parser.load_entities()
    conn = db.get_connection()
    try:
        runs = conn.execute(
            "SELECT id, raw_response, citations_json FROM runs"
        ).fetchall()
        conn.execute("DELETE FROM mentions")

        for run in runs:
            run_id, raw_response, citations_json = run
            citations = json.loads(citations_json) if citations_json else None
            mentions = parser.analyze(raw_response, entities, citations=citations)
            for m in mentions:
                conn.execute(
                    "INSERT INTO mentions (run_id, entity_name, mentioned, "
                    "position, is_recommended, mention_count) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        m["entity_name"],
                        m["mentioned"],
                        m["position"],
                        m["is_recommended"],
                        m["mention_count"],
                    ),
                )
        conn.commit()
        print(f"Re-parsed {len(runs)} stored responses.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
