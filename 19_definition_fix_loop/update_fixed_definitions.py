#!/usr/bin/env python3
"""
update_fixed_definitions.py — Update definitions from Thejus's JSONL and reset scores for re-scoring.

Reads fix_definitions_filled.jsonl, updates the definition column in keyword_scores_production,
and resets all model scores to -1 so the ensemble pipeline re-scores just those rows.

Usage:
    python update_fixed_definitions.py --input fix_definitions_filled.jsonl
    python update_fixed_definitions.py --input fix_definitions_filled.jsonl --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
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
TABLE = "keyword_scores_production"


def make_slug(keyword):
    slug = keyword.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    return re.sub(r'-+', '-', slug).strip('-')


def sb_upsert(rows):
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
    parser = argparse.ArgumentParser(description="Update fixed definitions and reset scores")
    parser.add_argument("--input", required=True, help="Path to fix_definitions_filled.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set QA_SUPABASE_URL and QA_SUPABASE_KEY in .env")
        sys.exit(1)

    # Read JSONL
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: {input_path} not found")
        sys.exit(1)

    rows = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    print(f"\n{'='*60}")
    print(f"  UPDATING FIXED DEFINITIONS IN {TABLE}")
    print(f"{'='*60}")
    print(f"  Input: {input_path} ({len(rows)} rows)")

    # Build update payloads — new definition + reset all scores
    updates = []
    no_def = 0
    for r in rows:
        keyword = r.get("keyword", "").strip()
        if not keyword:
            continue

        slug = r.get("slug", "").strip() or make_slug(keyword)
        definition = (r.get("definition_short", "") or r.get("definition_raw", "") or "").strip()

        if not definition:
            no_def += 1

        updates.append({
            "slug": slug,
            "definition": definition,
            # Reset all model scores so pipeline re-scores them
            "mistral_score": -1,
            "mistral_tag": "",
            "mistral_issue": "",
            "openai_score": -1,
            "openai_tag": "",
            "openai_issue": "",
            "claude_score": -1,
            "claude_tag": "",
            "claude_issue": "",
            # Reset consensus
            "avg_score": -1,
            "consensus": "",
            "action": "fix_definition",  # keep action until re-scored
            "tag_consensus": "",
            "flag": True,
        })

    print(f"  Keywords to update: {len(updates)}")
    print(f"  With new definition: {len(updates) - no_def}")
    print(f"  Still no definition: {no_def}")

    if args.dry_run:
        print(f"\n  DRY RUN — no data written.")
        print(f"\n  Sample updates:")
        for u in updates[:5]:
            print(f"    {u['slug']:30s} | def: {u['definition'][:60]}...")
        return

    # Upload in batches
    batch_size = 50
    uploaded = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        try:
            sb_upsert(batch)
            uploaded += len(batch)
            print(f"\r  Updated {uploaded}/{len(updates)} rows...", end="", flush=True)
        except Exception as e:
            print(f"\n  Error at row {i}: {e}")
        time.sleep(0.3)

    print(f"\n\n  DONE! {uploaded} definitions updated, scores reset to -1")
    print(f"\n  Next steps:")
    print(f"    python ensemble_pipeline_v2.py score --model mistral")
    print(f"    python ensemble_pipeline_v2.py score --model openai")
    print(f"    (then Claude Code for 336 rows)")
    print(f"    python ensemble_pipeline_v2.py ensemble")


if __name__ == "__main__":
    main()