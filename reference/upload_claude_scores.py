#!/usr/bin/env python3
"""
upload_claude_scores.py — Upload Claude scoring results to Supabase.

Reads claude_all_scored.csv and updates the keyword_scores_claude table.

Usage:
    python upload_claude_scores.py
    python upload_claude_scores.py --csv claude_all_scored.csv
    python upload_claude_scores.py --dry-run   # preview without writing
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

# ─── .env loader ───
def load_dotenv():
    for p in [Path(__file__).resolve().parent / ".env", Path.cwd() / ".env"]:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            print(f"  .env loaded from {p}")
            return

load_dotenv()

SUPABASE_URL = (os.getenv("QA_SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")).rstrip("/")
SUPABASE_KEY = os.getenv("QA_SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
TABLE = "keyword_scores_claude"

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Set QA_SUPABASE_URL and QA_SUPABASE_KEY in .env")
    sys.exit(1)


def upsert_batch(rows):
    """Upsert a batch of rows using POST with on_conflict=slug."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?on_conflict=slug"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    data = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        pass


def main():
    parser = argparse.ArgumentParser(description="Upload Claude scores to Supabase")
    parser.add_argument("--csv", default="claude_all_scored.csv", help="Input CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--batch-size", type=int, default=100, help="Rows per upsert")
    args = parser.parse_args()

    # Read CSV
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        sys.exit(1)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"  Loaded {len(rows)} rows from {csv_path}")

    # Validate
    required = {"slug", "claude_score", "claude_tag", "claude_issue"}
    if rows:
        missing = required - set(rows[0].keys())
        if missing:
            print(f"ERROR: CSV missing columns: {missing}")
            sys.exit(1)

    # Preview
    scores = [int(r["claude_score"]) for r in rows if r["claude_score"].lstrip("-").isdigit()]
    print(f"  Score range: {min(scores)} – {max(scores)}")
    print(f"  Avg score: {sum(scores)/len(scores):.1f}")
    print(f"  Below 70: {sum(1 for s in scores if s < 70)}")

    if args.dry_run:
        print("\n  DRY RUN — no data written.")
        return

    # Upload in batches
    uploaded = 0
    errors = 0
    total_batches = (len(rows) + args.batch_size - 1) // args.batch_size

    for i in range(0, len(rows), args.batch_size):
        batch = rows[i:i + args.batch_size]
        payload = [
            {
                "slug": r["slug"],
                "claude_score": int(r["claude_score"]),
                "claude_tag": r["claude_tag"],
                "claude_issue": r["claude_issue"][:500],
            }
            for r in batch
        ]

        try:
            upsert_batch(payload)
            uploaded += len(batch)
            batch_num = i // args.batch_size + 1
            print(f"\r  [{batch_num}/{total_batches}] {uploaded}/{len(rows)} uploaded",
                  end="", flush=True)
        except Exception as e:
            print(f"\n  ERROR at row {i}: {e}")
            errors += 1

    print(f"\n\n  DONE: {uploaded} rows uploaded, {errors} errors")
    print(f"  Verify in Supabase:")
    print(f"    SELECT count(*) FROM {TABLE} WHERE claude_score != -1;")


if __name__ == "__main__":
    main()