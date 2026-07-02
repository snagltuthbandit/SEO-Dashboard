"""Orchestrates prompt x engine calls, stores raw responses + parsed mentions.

Run weekly via cron (see run.sh). Safe to re-run: each invocation just
appends a new run_date's worth of rows.
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, parser
from src.engines import anthropic_client, gemini_client, openai_client, perplexity_client

ENGINES = {
    "openai": openai_client,
    "anthropic": anthropic_client,
    "gemini": gemini_client,
    "perplexity": perplexity_client,
}

# Seconds to wait between calls to the same engine. Gemini's free tier allows
# 5 requests/minute, so pace it at 15s; the paid APIs don't need pacing.
ENGINE_DELAY = {"gemini": 15}

RETRY_DELAYS = [20, 45, 90]  # seconds; handles transient 429/503 responses


def _call_with_retry(client, engine_name: str, prompt_text: str) -> dict:
    last_exc = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay:
            print(f"  retrying {engine_name} in {delay}s...", file=sys.stderr)
            time.sleep(delay)
        try:
            return client.call(prompt_text)
        except Exception as exc:
            last_exc = exc
            print(f"  attempt {attempt + 1} failed: {exc}", file=sys.stderr)
    raise last_exc


def run(engines: list = None, run_date: str = None):
    load_dotenv()
    db.init_db()

    engines = engines or list(ENGINES.keys())
    run_date = run_date or date.today().isoformat()

    prompts = parser.load_prompts()
    entities = parser.load_entities()

    conn = db.get_connection()
    try:
        last_call_at = {}  # engine_name -> monotonic time of last call
        for prompt in prompts:
            for engine_name in engines:
                client = ENGINES[engine_name]

                # Idempotent re-runs: skip prompt x engine combos already
                # collected for this run_date (e.g. after a partial failure).
                existing = conn.execute(
                    "SELECT 1 FROM runs WHERE run_date = ? AND prompt_id = ? "
                    "AND engine = ?",
                    (run_date, prompt["id"], engine_name),
                ).fetchone()
                if existing:
                    print(f"[{run_date}] {engine_name} :: {prompt['id']} (already collected, skipping)")
                    continue

                # Pace rate-limited engines (Gemini free tier: 5 req/min).
                delay = ENGINE_DELAY.get(engine_name, 0)
                if delay and engine_name in last_call_at:
                    wait = delay - (time.monotonic() - last_call_at[engine_name])
                    if wait > 0:
                        time.sleep(wait)

                print(f"[{run_date}] {engine_name} :: {prompt['id']}")
                last_call_at[engine_name] = time.monotonic()
                try:
                    result = _call_with_retry(client, engine_name, prompt["text"])
                except Exception as exc:
                    # Skip failed calls entirely — recording them would count
                    # as "not mentioned" and skew the mention rate.
                    print(f"  giving up on {engine_name}: {exc}", file=sys.stderr)
                    continue

                citations = result.get("citations")
                cur = conn.execute(
                    "INSERT INTO runs (run_date, prompt_id, prompt_text, engine, "
                    "raw_response, citations_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_date,
                        prompt["id"],
                        prompt["text"],
                        engine_name,
                        result["raw_response"],
                        json.dumps(citations) if citations else None,
                    ),
                )
                run_id = cur.lastrowid

                mentions = parser.analyze(
                    result["raw_response"], entities, citations=citations
                )
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
    finally:
        conn.close()

    print(f"Done. Run date: {run_date}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run AI citation tracker prompts across engines")
    ap.add_argument(
        "--engines",
        nargs="+",
        choices=list(ENGINES.keys()),
        help="Subset of engines to run (default: all)",
    )
    ap.add_argument("--run-date", help="Override run_date (ISO format), default today")
    args = ap.parse_args()
    run(engines=args.engines, run_date=args.run_date)
