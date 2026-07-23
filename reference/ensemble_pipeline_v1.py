#!/usr/bin/env python3
"""
ensemble_pipeline.py — Complete ensemble verification pipeline.

This script handles the FULL workflow:
  1. Create a test table (keyword_scores_test) in Supabase
  2. Copy first 50 records from the articles table into it
  3. Run each model (Gemini, Mistral, Llama) one at a time
  4. Write scores back to the test table
  5. Compute ensemble consensus
  6. Generate a local report

Usage:
    python ensemble_pipeline.py setup                        # Step 1+2: create table, load 50 rows
    python ensemble_pipeline.py score --model gemini         # Step 3: score with Gemini
    python ensemble_pipeline.py score --model mistral        # Step 3: score with Mistral
    python ensemble_pipeline.py score --model llama          # Step 3: score with Llama
    python ensemble_pipeline.py ensemble                     # Step 4: compute consensus
    python ensemble_pipeline.py report                       # Step 5: generate comparison report
    python ensemble_pipeline.py status                       # Check progress at any time

    python ensemble_pipeline.py setup --limit 10             # Test with only 10 rows first
    python ensemble_pipeline.py score --model gemini --batch-size 3   # Smaller batches
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TEST_TABLE = "keyword_scores_test"   # safe test table — won't touch production
SOURCE_TABLE = "articles"            # where keyword definitions live

RESULTS_DIR = Path("results")
DEBUG_DIR = RESULTS_DIR / "debug_responses"

DEFAULT_BATCH_SIZE = 5
DEFAULT_LIMIT = 50

RATE_LIMITS = {
    "gemini":  6.5,
    "mistral": 2.0,
    "llama":   0.5,
}

# ─────────────────────────────────────────────────────────────────────────────
# .env loader
# ─────────────────────────────────────────────────────────────────────────────

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
    print("  No .env found — using environment variables")

load_dotenv()

# We use ONE Supabase project — the same one that has the articles table.
# The test table (keyword_scores_test) goes in the same project.
SUPABASE_URL = (
    os.getenv("QA_SUPABASE_URL")
    or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
).rstrip("/")

SUPABASE_KEY = (
    os.getenv("QA_SUPABASE_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
)

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OLLAMA_URL      = os.getenv("OLLAMA_URL", "http://localhost:11434")


def check_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Missing Supabase credentials.")
        print("  Set either QA_SUPABASE_URL + QA_SUPABASE_KEY")
        print("  or NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY")
        print("  in your .env file.")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────────────────────────────────────

def sb_headers(prefer="return=minimal"):
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        prefer,
    }


def sb_request(method, path, body=None, prefer="return=minimal"):
    """Make an HTTP request to Supabase REST API."""
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
    """Fetch all rows with pagination."""
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
    """Insert or update rows (upsert on primary key)."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        **sb_headers("return=minimal"),
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    data = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        pass


def sb_update_row(table, pk_col, pk_val, updates):
    """Update a single row by primary key."""
    encoded = urllib.parse.quote(str(pk_val))
    path = f"{table}?{pk_col}=eq.{encoded}"
    sb_request("PATCH", path, body=updates)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Setup — Create test table and load data
# ─────────────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TEST_TABLE} (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    term TEXT,
    category TEXT,
    definition TEXT,
    gemini_score INTEGER DEFAULT -1,
    gemini_issue TEXT DEFAULT '',
    gemini_tag TEXT DEFAULT '',
    mistral_score INTEGER DEFAULT -1,
    mistral_issue TEXT DEFAULT '',
    mistral_tag TEXT DEFAULT '',
    llama_score INTEGER DEFAULT -1,
    llama_issue TEXT DEFAULT '',
    llama_tag TEXT DEFAULT '',
    avg_score FLOAT DEFAULT -1,
    consensus TEXT DEFAULT '',
    flag BOOLEAN DEFAULT FALSE,
    scored_at TIMESTAMP DEFAULT NOW()
);
"""


def cmd_setup(args):
    """Create the test table and load rows from articles."""
    check_supabase()
    limit = args.limit

    print(f"\n{'='*60}")
    print(f"  SETUP: Creating {TEST_TABLE} with {limit} rows")
    print(f"{'='*60}")

    # ── Step 1: Create table via Supabase SQL ──
    # NOTE: Supabase REST API can't run DDL (CREATE TABLE).
    # You need to run the SQL in the Supabase Dashboard.
    print(f"\n[1/3] Table creation")
    print(f"  The REST API cannot create tables directly.")
    print(f"  Go to your Supabase Dashboard → SQL Editor → paste this:\n")
    print(f"  {'-'*50}")
    print(CREATE_TABLE_SQL)
    print(f"  {'-'*50}")
    print(f"\n  After running that SQL, come back and re-run this command.")
    print(f"  (If the table already exists, this is fine — we'll just load data.)")

    # ── Step 2: Check if table exists by trying to read from it ──
    print(f"\n[2/3] Checking if {TEST_TABLE} exists...")
    try:
        existing = sb_request("GET", f"{TEST_TABLE}?select=id&limit=1", prefer="count=none")
        if existing is not None:
            print(f"  Table exists!")
            # Check how many rows already
            all_rows = sb_fetch_all(f"{TEST_TABLE}?select=id")
            print(f"  Current rows: {len(all_rows)}")
            if len(all_rows) >= limit:
                print(f"  Already has {len(all_rows)} rows (>= {limit}). Skipping load.")
                print(f"  To reload, delete rows first in Supabase Dashboard:")
                print(f"    DELETE FROM {TEST_TABLE};")
                return
    except Exception as e:
        if "404" in str(e) or "does not exist" in str(e).lower() or "42P01" in str(e):
            print(f"  Table does NOT exist yet.")
            print(f"  → Run the CREATE TABLE SQL above in Supabase Dashboard first.")
            return
        else:
            print(f"  Unexpected error: {e}")
            print(f"  Trying to continue anyway...")

    # ── Step 3: Fetch from articles and insert into test table ──
    print(f"\n[3/3] Loading {limit} rows from '{SOURCE_TABLE}' → '{TEST_TABLE}'...")
    try:
        source_rows = sb_request(
            "GET",
            f"{SOURCE_TABLE}?select=slug,term,category,definition&limit={limit}",
            prefer="count=none"
        )
    except Exception as e:
        print(f"  ERROR reading from {SOURCE_TABLE}: {e}")
        print(f"  Make sure the '{SOURCE_TABLE}' table exists with columns: slug, term, category, definition")
        return

    if not source_rows:
        print(f"  No rows found in {SOURCE_TABLE}!")
        return

    print(f"  Fetched {len(source_rows)} rows from {SOURCE_TABLE}")

    # Insert in batches of 50
    batch_size = 50
    inserted = 0
    for i in range(0, len(source_rows), batch_size):
        batch = source_rows[i:i + batch_size]
        # Only include the columns we need (no 'id' — let SERIAL handle it)
        clean_batch = [
            {
                "slug": r["slug"],
                "term": r.get("term", ""),
                "category": r.get("category", ""),
                "definition": r.get("definition", ""),
            }
            for r in batch
        ]
        try:
            sb_upsert(TEST_TABLE, clean_batch)
            inserted += len(clean_batch)
            print(f"  Inserted {inserted}/{len(source_rows)} rows...", end="\r")
        except Exception as e:
            print(f"\n  Error inserting batch at row {i}: {e}")
            break

    print(f"\n  Done! {inserted} rows loaded into {TEST_TABLE}")
    print(f"\n  Next: python ensemble_pipeline.py score --model gemini")

# ─────────────────────────────────────────────────────────────────────────────
# Prompt (same as before — identical for all models)
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """You are a scientific content reviewer for a cancer biology textbook.

For each keyword entry below, evaluate:
1. Is the TERM correctly named for biomedical/scientific use?
2. Is the CATEGORY appropriate? Valid categories: Biochemistry, Molecular Biology, Cell Biology, Oncology, Biomedical Science, Pharmacology, Biotechnology, Genetics, Diagnostics, Immunology, Nanotechnology, Chemistry, Anatomy, Nanomedicine
3. Is the DEFINITION accurate, complete, and relevant to a cancer biology textbook?

Score each entry 0-100:
  90-100: Correct term, right category, accurate definition
  70-89:  Mostly correct, minor issues
  50-69:  Notable issues (wrong category, incomplete/vague definition)
  0-49:   Serious problems (wrong topic, broken text, factually wrong)

For each entry also provide an "issue_tag" from this list:
  "none"                  - no issues found
  "incorrect_term"        - the term name itself is wrong or doesn't exist
  "incorrect_category"    - definition is fine but category is wrong
  "incorrect_definition"  - term and category OK but definition is wrong/broken
  "low_relevance"         - real term but not relevant to cancer biology textbook
  "off_topic"             - completely unrelated to biomedical science

Respond with ONLY a JSON array. No markdown fences, no explanation, no other text.
Format: [{"slug": "...", "score": 85, "issue_tag": "none", "issue_detail": "none"}]

If there's an issue, put a brief explanation in "issue_detail".

Entries to review:

"""


def build_prompt(batch):
    lines = [PROMPT_TEMPLATE]
    for i, row in enumerate(batch, 1):
        lines.append(f"Entry {i}:")
        lines.append(f"  Slug: {row['slug']}")
        lines.append(f"  Term: {row['term']}")
        lines.append(f"  Category: {row['category']}")
        # Truncate very long definitions to keep prompt reasonable
        defn = (row.get("definition") or "")[:500]
        lines.append(f"  Definition: {defn}")
        lines.append("")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Model callers
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini(prompt):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_mistral(prompt):
    url = "https://api.mistral.ai/v1/chat/completions"
    body = json.dumps({
        "model": "mistral-small-latest",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2048,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def call_llama(prompt):
    url = f"{OLLAMA_URL}/api/generate"
    body = json.dumps({
        "model": "llama3.1:8b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2048},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    return data["response"]


MODEL_CALLERS = {
    "gemini":  call_gemini,
    "mistral": call_mistral,
    "llama":   call_llama,
}

# ─────────────────────────────────────────────────────────────────────────────
# JSON parser (robust — handles markdown fences, preamble, etc.)
# ─────────────────────────────────────────────────────────────────────────────

def extract_json_array(raw_text):
    """Extract a JSON array from model output, handling various formatting issues."""
    text = raw_text.strip()

    # Strategy 1: direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"\s*```", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Strategy 3: bracket matching — find outermost [ ... ]
    start = text.find("[")
    if start == -1:
        return None

    depth = 0
    end = -1
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return None

    try:
        parsed = json.loads(text[start:end + 1])
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        return None

    return None

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Score — Run a model and write results to Supabase
# ─────────────────────────────────────────────────────────────────────────────

def preflight_check(model_name):
    """Verify API key and connectivity."""
    if model_name == "gemini":
        if not GEMINI_API_KEY:
            print(f"  GEMINI_API_KEY not set — skipping")
            return False
        try:
            resp = call_gemini("Respond with exactly: [{}]")
            print(f"  Gemini: OK (response: {len(resp)} chars)")
            return True
        except Exception as e:
            print(f"  Gemini FAILED: {e}")
            return False

    elif model_name == "mistral":
        if not MISTRAL_API_KEY:
            print(f"  MISTRAL_API_KEY not set — skipping")
            return False
        try:
            resp = call_mistral("Respond with exactly: [{}]")
            print(f"  Mistral: OK (response: {len(resp)} chars)")
            return True
        except Exception as e:
            print(f"  Mistral FAILED: {e}")
            return False

    elif model_name == "llama":
        try:
            resp = call_llama("Respond with exactly: [{}]")
            print(f"  Llama/Ollama: OK (response: {len(resp)} chars)")
            return True
        except urllib.error.URLError:
            print(f"  Llama/Ollama NOT REACHABLE at {OLLAMA_URL}")
            return False
        except Exception as e:
            print(f"  Llama FAILED: {e}")
            return False

    return False


def score_one_batch(model_name, caller, batch, batch_idx):
    """Send one batch to a model, return per-keyword score dicts."""
    prompt = build_prompt(batch)
    raw_response = ""

    try:
        raw_response = caller(prompt)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:300]
        print(f"\n    [API {e.code}] {error_body[:100]}")
        if e.code == 429:
            print(f"    Rate limited — waiting 60s...")
            time.sleep(60)
            try:
                raw_response = caller(prompt)
            except Exception:
                pass
    except Exception as e:
        print(f"\n    [ERROR] {type(e).__name__}: {e}")

    # Save raw response for debugging
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    debug_file = DEBUG_DIR / f"{model_name}_batch_{batch_idx:03d}.txt"
    debug_file.write_text(raw_response or "(empty)", encoding="utf-8")

    if not raw_response:
        return [
            {"slug": r["slug"], "score": -1, "issue_tag": "API_ERROR", "issue_detail": "No response"}
            for r in batch
        ]

    parsed = extract_json_array(raw_response)
    if parsed is None:
        print(f"\n    [PARSE FAIL] See {debug_file.name}")
        return [
            {"slug": r["slug"], "score": -1, "issue_tag": "PARSE_ERROR",
             "issue_detail": f"See {debug_file.name}"}
            for r in batch
        ]

    results = []
    for row in batch:
        matched = next((s for s in parsed if s.get("slug") == row["slug"]), None)
        if not matched:
            idx = batch.index(row)
            matched = parsed[idx] if idx < len(parsed) else None

        if matched:
            results.append({
                "slug":         row["slug"],
                "score":        matched.get("score", -1),
                "issue_tag":    matched.get("issue_tag", "unknown"),
                "issue_detail": str(matched.get("issue_detail", ""))[:500],
            })
        else:
            results.append({
                "slug":         row["slug"],
                "score":        -1,
                "issue_tag":    "MISSING_FROM_RESPONSE",
                "issue_detail": f"Model returned {len(parsed)} items for {len(batch)} entries",
            })

    return results


def cmd_score(args):
    """Run a single model on all unscored rows and write results to Supabase."""
    check_supabase()
    model_name = args.model
    batch_size = args.batch_size

    score_col = f"{model_name}_score"
    issue_col = f"{model_name}_issue"
    tag_col   = f"{model_name}_tag"

    print(f"\n{'='*60}")
    print(f"  SCORING: {model_name.upper()}")
    print(f"{'='*60}")

    # Pre-flight
    print(f"\nPre-flight check:")
    if not preflight_check(model_name):
        return

    # Fetch rows that haven't been scored by this model yet
    print(f"\nFetching unscored rows from {TEST_TABLE}...")
    all_rows = sb_fetch_all(
        f"{TEST_TABLE}?select=slug,term,category,definition,{score_col}"
    )

    # Filter to unscored (score == -1 or null)
    unscored = [r for r in all_rows if r.get(score_col) in (-1, None)]
    already = len(all_rows) - len(unscored)

    print(f"  Total rows: {len(all_rows)}")
    print(f"  Already scored by {model_name}: {already}")
    print(f"  To score: {len(unscored)}")

    if not unscored:
        print(f"  All rows already scored! Use 'status' command to check.")
        return

    caller = MODEL_CALLERS[model_name]
    delay = RATE_LIMITS.get(model_name, 2.0)
    total_batches = math.ceil(len(unscored) / batch_size)

    print(f"  Batch size: {batch_size} | Batches: {total_batches}")
    print(f"  Rate limit delay: {delay}s\n")

    scored = 0
    errors = 0
    start_time = time.time()

    for batch_idx in range(total_batches):
        b_start = batch_idx * batch_size
        b_end = min(b_start + batch_size, len(unscored))
        batch = unscored[b_start:b_end]

        results = score_one_batch(model_name, caller, batch, batch_idx)

        # Write each result back to Supabase
        for r in results:
            try:
                sb_update_row(TEST_TABLE, "slug", r["slug"], {
                    score_col: r["score"],
                    issue_col: r["issue_detail"],
                    tag_col:   r["issue_tag"],
                    "scored_at": datetime.utcnow().isoformat(),
                })
                scored += 1
            except Exception as e:
                print(f"\n    [DB ERROR] {r['slug']}: {e}")
                errors += 1

        elapsed = time.time() - start_time
        pct = (batch_idx + 1) / total_batches * 100
        print(f"\r  [{batch_idx+1}/{total_batches}] {pct:.0f}% | "
              f"{scored} scored | {errors} errors | {elapsed:.0f}s",
              end="", flush=True)

        if batch_idx < total_batches - 1:
            time.sleep(delay)

    elapsed = time.time() - start_time
    print(f"\n\n  DONE: {scored} rows scored by {model_name} in {elapsed:.0f}s")
    if errors:
        print(f"  Errors: {errors}")
    print(f"\n  Next: score another model, or run 'ensemble' to compute consensus")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Ensemble — Compute consensus from all model scores
# ─────────────────────────────────────────────────────────────────────────────

def cmd_ensemble(args):
    """Compute avg_score, consensus, and flag for all rows."""
    check_supabase()

    print(f"\n{'='*60}")
    print(f"  COMPUTING ENSEMBLE CONSENSUS")
    print(f"{'='*60}")

    rows = sb_fetch_all(
        f"{TEST_TABLE}?select=slug,gemini_score,mistral_score,llama_score"
    )
    print(f"  {len(rows)} rows loaded")

    updated = 0
    flagged = 0
    consensus_counts = {"ALL_PASS": 0, "ALL_FAIL": 0, "DISAGREE": 0, "NO_DATA": 0}

    for row in rows:
        g = row.get("gemini_score") or -1
        m = row.get("mistral_score") or -1
        l = row.get("llama_score") or -1

        valid = [s for s in [g, m, l] if s >= 0]
        avg = round(sum(valid) / len(valid), 1) if valid else -1

        if not valid:
            consensus = "NO_DATA"
        else:
            pass_votes = sum(1 for s in valid if s >= 70)
            if pass_votes == len(valid):
                consensus = "ALL_PASS"
            elif pass_votes == 0:
                consensus = "ALL_FAIL"
            else:
                consensus = "DISAGREE"

        flag = consensus != "ALL_PASS"
        if flag:
            flagged += 1
        consensus_counts[consensus] += 1

        try:
            sb_update_row(TEST_TABLE, "slug", row["slug"], {
                "avg_score":  avg,
                "consensus":  consensus,
                "flag":       flag,
            })
            updated += 1
        except Exception as e:
            print(f"  [ERROR] {row['slug']}: {e}")

    print(f"\n  Updated: {updated}/{len(rows)} rows")
    print(f"\n  CONSENSUS BREAKDOWN:")
    for label, count in consensus_counts.items():
        pct = count / len(rows) * 100 if rows else 0
        print(f"    {label:15s}: {count:4d} ({pct:.1f}%)")
    print(f"\n  Flagged: {flagged}/{len(rows)} ({flagged/len(rows)*100:.1f}%)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Status — Check scoring progress
# ─────────────────────────────────────────────────────────────────────────────

def cmd_status(args):
    """Show current scoring progress for all models."""
    check_supabase()

    print(f"\n{'='*60}")
    print(f"  SCORING STATUS — {TEST_TABLE}")
    print(f"{'='*60}")

    rows = sb_fetch_all(
        f"{TEST_TABLE}?select=slug,gemini_score,mistral_score,llama_score,consensus,flag"
    )

    if not rows:
        print(f"\n  No rows in {TEST_TABLE}. Run 'setup' first.")
        return

    print(f"\n  Total rows: {len(rows)}")

    for model in ["gemini", "mistral", "llama"]:
        col = f"{model}_score"
        scored = sum(1 for r in rows if (r.get(col) or -1) >= 0)
        unscored = len(rows) - scored
        valid_scores = [r[col] for r in rows if (r.get(col) or -1) >= 0]
        avg = sum(valid_scores) / len(valid_scores) if valid_scores else 0

        status = "DONE" if unscored == 0 else f"{unscored} remaining"
        print(f"\n  {model.upper():10s}: {scored}/{len(rows)} scored ({status})")
        if valid_scores:
            print(f"    Avg: {avg:.1f} | Min: {min(valid_scores)} | Max: {max(valid_scores)}")
            below_70 = sum(1 for s in valid_scores if s < 70)
            print(f"    Below 70: {below_70}")

    # Consensus stats
    with_consensus = [r for r in rows if r.get("consensus")]
    if with_consensus:
        from collections import Counter
        cons = Counter(r["consensus"] for r in with_consensus)
        print(f"\n  CONSENSUS ({len(with_consensus)} rows computed):")
        for label, count in cons.most_common():
            print(f"    {label:15s}: {count}")
    else:
        print(f"\n  Consensus not yet computed. Run 'ensemble' after scoring.")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Report — Generate local comparison CSV and summary
# ─────────────────────────────────────────────────────────────────────────────

def cmd_report(args):
    """Download all scores and generate local report files."""
    check_supabase()
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  GENERATING REPORT")
    print(f"{'='*60}")

    rows = sb_fetch_all(f"{TEST_TABLE}?select=*")
    if not rows:
        print(f"  No data in {TEST_TABLE}.")
        return

    # CSV export
    csv_path = RESULTS_DIR / "comparison_report.csv"
    fields = [
        "id", "slug", "term", "category",
        "gemini_score", "gemini_tag", "gemini_issue",
        "mistral_score", "mistral_tag", "mistral_issue",
        "llama_score", "llama_tag", "llama_issue",
        "avg_score", "consensus", "flag",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r.get("id", 0)):
            writer.writerow(row)

    print(f"  CSV: {csv_path}")

    # Summary
    total = len(rows)
    summary = []
    summary.append(f"Ensemble Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    summary.append(f"Table: {TEST_TABLE} | Rows: {total}")
    summary.append("=" * 60)

    for model in ["gemini", "mistral", "llama"]:
        col = f"{model}_score"
        valid = [r[col] for r in rows if (r.get(col) or -1) >= 0]
        errs = total - len(valid)
        if valid:
            summary.append(f"\n{model.upper()}: {len(valid)}/{total} scored (errors: {errs})")
            summary.append(f"  Avg: {sum(valid)/len(valid):.1f} | "
                           f"Min: {min(valid)} | Max: {max(valid)}")
            summary.append(f"  Below 70: {sum(1 for s in valid if s < 70)}")
        else:
            summary.append(f"\n{model.upper()}: not scored yet")

    from collections import Counter
    cons = Counter(r.get("consensus", "NOT_COMPUTED") for r in rows)
    summary.append(f"\nCONSENSUS:")
    for label, count in cons.most_common():
        summary.append(f"  {label:15s}: {count} ({count/total*100:.1f}%)")

    flagged = sum(1 for r in rows if r.get("flag"))
    summary.append(f"\nFlagged for review: {flagged}/{total}")

    # Disagreements
    summary.append(f"\nDISAGREEMENTS (score spread > 25):")
    for row in rows:
        scores = []
        for m in ["gemini", "mistral", "llama"]:
            s = row.get(f"{m}_score") or -1
            if s >= 0:
                scores.append((m, s))
        if len(scores) >= 2:
            vals = [s for _, s in scores]
            spread = max(vals) - min(vals)
            if spread > 25:
                detail = ", ".join(f"{m}={s}" for m, s in scores)
                summary.append(f"  {row['slug']:40s} | {detail} | spread={spread}")

    summary_text = "\n".join(summary)
    summary_path = RESULTS_DIR / "summary.txt"
    summary_path.write_text(summary_text, encoding="utf-8")

    print(f"  Summary: {summary_path}")
    print(f"\n{summary_text}")

# ─────────────────────────────────────────────────────────────────────────────
# Main — command dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ensemble keyword verification pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  setup     Create test table and load keywords from articles
  score     Run a model (gemini/mistral/llama) on unscored rows
  ensemble  Compute consensus from all model scores
  status    Check scoring progress
  report    Generate comparison CSV and summary

Typical workflow:
  python ensemble_pipeline.py setup                    # create table + load 50 rows
  python ensemble_pipeline.py score --model gemini     # score with Gemini
  python ensemble_pipeline.py score --model mistral    # score with Mistral
  python ensemble_pipeline.py ensemble                 # compute consensus
  python ensemble_pipeline.py report                   # generate report
        """
    )

    sub = parser.add_subparsers(dest="command")

    # setup
    p_setup = sub.add_parser("setup", help="Create test table and load data")
    p_setup.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                         help=f"Rows to load (default: {DEFAULT_LIMIT})")

    # score
    p_score = sub.add_parser("score", help="Run a model on unscored rows")
    p_score.add_argument("--model", required=True,
                         choices=["gemini", "mistral", "llama"])
    p_score.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                         help=f"Keywords per API call (default: {DEFAULT_BATCH_SIZE})")

    # ensemble
    sub.add_parser("ensemble", help="Compute consensus from model scores")

    # status
    sub.add_parser("status", help="Check scoring progress")

    # report
    sub.add_parser("report", help="Generate comparison report")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    RESULTS_DIR.mkdir(exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    commands = {
        "setup":    cmd_setup,
        "score":    cmd_score,
        "ensemble": cmd_ensemble,
        "status":   cmd_status,
        "report":   cmd_report,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()