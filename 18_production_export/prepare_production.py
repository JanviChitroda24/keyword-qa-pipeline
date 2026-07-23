#!/usr/bin/env python3
"""
prepare_production.py — Prepare keywords for textbook integration.

1. Creates keyword_scores_production table in Supabase
2. Copies approved + supplementary + fix_definition rows from keyword_scores_v2
3. Exports 2 CSVs:
   - approved_supplementary.csv  (ready for textbook integration)
   - fix_definition.csv          (needs Thejus to regenerate definitions)

Usage:
    python prepare_production.py create-table     # Show SQL to create table
    python prepare_production.py populate          # Copy rows from v2 to production
    python prepare_production.py export            # Export the 2 CSVs
    python prepare_production.py all               # Do all steps
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ─── Config ───
SOURCE_TABLE = "keyword_scores_v2"
PROD_TABLE = "keyword_scores_production"
EXPORT_DIR = Path("exports")

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

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Set QA_SUPABASE_URL and QA_SUPABASE_KEY in .env")
    sys.exit(1)


# ─── Supabase helpers ───
def sb_headers(prefer="return=minimal"):
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }

def sb_request(method, path, body=None, prefer="return=minimal"):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=sb_headers(prefer))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:500]
        raise Exception(f"HTTP {e.code}: {error_body}")

def sb_fetch_all(path):
    results = []
    offset = 0
    limit = 1000
    while True:
        sep = "&" if "?" in path else "?"
        page_path = f"{path}{sep}limit={limit}&offset={offset}"
        batch = sb_request("GET", page_path, prefer="count=none")
        if batch is None:
            break
        results.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return results

def sb_upsert(table, rows):
    import time
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict=slug"
    headers = {
        **sb_headers("return=minimal"),
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    # Upload in batches of 50 with delay
    batch_size = 50
    uploaded = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        data = json.dumps(batch).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    pass
                uploaded += len(batch)
                print(f"\r  Uploaded {uploaded}/{len(rows)} rows...", end="", flush=True)
                break
            except Exception as e:
                if attempt < 2 and ("SSL" in str(e) or "timed out" in str(e)):
                    time.sleep(2 * (attempt + 1))
                else:
                    raise
        time.sleep(0.3)
    print()


# ─── SQL ───
CREATE_TABLE_SQL = f"""
-- Production table: approved + supplementary + fix_definition keywords
-- Source: {SOURCE_TABLE} (kept as-is for auditing)

CREATE TABLE IF NOT EXISTS {PROD_TABLE} (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    term TEXT,
    category TEXT,
    definition TEXT,
    mistral_score INTEGER DEFAULT -1,
    mistral_issue TEXT DEFAULT '',
    mistral_tag TEXT DEFAULT '',
    openai_score INTEGER DEFAULT -1,
    openai_issue TEXT DEFAULT '',
    openai_tag TEXT DEFAULT '',
    claude_score INTEGER DEFAULT -1,
    claude_issue TEXT DEFAULT '',
    claude_tag TEXT DEFAULT '',
    avg_score FLOAT DEFAULT -1,
    consensus TEXT DEFAULT '',
    action TEXT DEFAULT '',
    tag_consensus TEXT DEFAULT '',
    flag BOOLEAN DEFAULT FALSE,
    scored_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE {PROD_TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow anon read on {PROD_TABLE}"
    ON {PROD_TABLE} FOR SELECT TO anon USING (true);
"""


# ─── Commands ───

def cmd_create_table(args):
    print(f"\n{'='*60}")
    print(f"  CREATE TABLE: {PROD_TABLE}")
    print(f"{'='*60}")
    print(f"\n  Run this SQL in Supabase Dashboard → SQL Editor:\n")
    print(CREATE_TABLE_SQL)
    print(f"  Then run: python prepare_production.py populate")


def cmd_populate(args):
    print(f"\n{'='*60}")
    print(f"  POPULATING {PROD_TABLE}")
    print(f"{'='*60}")

    # Fetch from source
    print(f"\n  Fetching from {SOURCE_TABLE}...")
    all_rows = sb_fetch_all(f"{SOURCE_TABLE}?select=*")
    print(f"  Total rows in {SOURCE_TABLE}: {len(all_rows)}")

    # Filter: approved + supplementary + fix_definition
    keep_actions = {"approved", "supplementary", "fix_definition", "too_basic"}
    filtered = [r for r in all_rows if r.get("action") in keep_actions]

    from collections import Counter
    action_counts = Counter(r["action"] for r in filtered)
    print(f"\n  Rows to copy:")
    for a, c in action_counts.most_common():
        print(f"    {a:20s}: {c}")
    print(f"    {'TOTAL':20s}: {len(filtered)}")

    # Check if production table exists and has data
    try:
        existing = sb_fetch_all(f"{PROD_TABLE}?select=id")
        if existing and not args.force:
            print(f"\n  {PROD_TABLE} already has {len(existing)} rows.")
            print(f"  Use --force to overwrite, or clear first:")
            print(f"    DELETE FROM {PROD_TABLE};")
            return
    except Exception as e:
        if "42P01" in str(e) or "does not exist" in str(e).lower():
            print(f"\n  Table {PROD_TABLE} doesn't exist yet.")
            print(f"  Run: python prepare_production.py create-table")
            return
        print(f"  Warning: {e}")

    # Prepare rows (remove id so serial auto-generates)
    clean_rows = []
    for r in filtered:
        row = {
            "slug": r["slug"],
            "term": r.get("term", ""),
            "category": r.get("category", ""),
            "definition": r.get("definition", ""),
            "mistral_score": r.get("mistral_score", -1),
            "mistral_issue": r.get("mistral_issue", ""),
            "mistral_tag": r.get("mistral_tag", ""),
            "openai_score": r.get("openai_score", -1),
            "openai_issue": r.get("openai_issue", ""),
            "openai_tag": r.get("openai_tag", ""),
            "claude_score": r.get("claude_score", -1),
            "claude_issue": r.get("claude_issue", ""),
            "claude_tag": r.get("claude_tag", ""),
            "avg_score": r.get("avg_score", -1),
            "consensus": r.get("consensus", ""),
            "action": r.get("action", ""),
            "tag_consensus": r.get("tag_consensus", ""),
            "flag": r.get("flag", False),
        }
        clean_rows.append(row)

    print(f"\n  Uploading {len(clean_rows)} rows to {PROD_TABLE}...")
    sb_upsert(PROD_TABLE, clean_rows)
    print(f"  Done! {len(clean_rows)} rows in {PROD_TABLE}")
    print(f"\n  Next: python prepare_production.py export")


def cmd_export(args):
    EXPORT_DIR.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  EXPORTING CSVs")
    print(f"{'='*60}")

    # Fetch from production table
    print(f"\n  Fetching from {PROD_TABLE}...")
    rows = sb_fetch_all(f"{PROD_TABLE}?select=*")
    print(f"  Total rows: {len(rows)}")

    approved_supp = [r for r in rows if r.get("action") in ("approved", "supplementary", "too_basic")]
    fix_def = [r for r in rows if r.get("action") == "fix_definition"]

    print(f"  Approved + Supplementary + Too Basic: {len(approved_supp)}")
    print(f"  Fix Definition: {len(fix_def)}")

    # CSV 1: approved + supplementary + too_basic (for integration)
    csv1_path = EXPORT_DIR / "approved_supplementary.csv"
    csv1_fields = ["slug", "term", "category", "definition", "action", "avg_score",
                   "mistral_tag", "openai_tag", "claude_tag", "tag_consensus"]
    with open(csv1_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv1_fields, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(approved_supp, key=lambda x: x.get("action", "")):
            writer.writerow(r)

    print(f"\n  CSV 1: {csv1_path}")
    print(f"    {len(approved_supp)} rows (approved + supplementary + too_basic)")
    print(f"    Columns: {', '.join(csv1_fields)}")

    # CSV 2: fix_definition (needs Thejus to regenerate)
    csv2_path = EXPORT_DIR / "fix_definition.csv"
    csv2_fields = ["slug", "term", "category", "definition", "avg_score",
                   "mistral_tag", "mistral_issue", "openai_tag", "openai_issue",
                   "claude_tag", "claude_issue"]
    with open(csv2_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv2_fields, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(fix_def, key=lambda x: x.get("slug", "")):
            writer.writerow(r)

    print(f"\n  CSV 2: {csv2_path}")
    print(f"    {len(fix_def)} rows (fix_definition)")
    print(f"    Columns: {', '.join(csv2_fields)}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  SHARE WITH THEJUS:")
    print(f"    1. {csv1_path} → integrate into textbook")
    print(f"    2. {csv2_path} → regenerate definitions, send back updated CSV")
    print(f"{'='*60}")


def cmd_all(args):
    cmd_create_table(args)
    print("\n\n  ⚠️  Run the SQL above first, then re-run with:")
    print("    python prepare_production.py populate")
    print("    python prepare_production.py export")


# ─── Main ───
def main():
    parser = argparse.ArgumentParser(description="Prepare keywords for production")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("create-table", help="Show SQL to create production table")

    p_pop = sub.add_parser("populate", help="Copy approved/supplementary/fix_definition rows")
    p_pop.add_argument("--force", action="store_true", help="Overwrite existing data")

    sub.add_parser("export", help="Export 2 CSVs for Thejus")

    sub.add_parser("all", help="Show full setup instructions")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    commands = {
        "create-table": cmd_create_table,
        "populate": cmd_populate,
        "export": cmd_export,
        "all": cmd_all,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()