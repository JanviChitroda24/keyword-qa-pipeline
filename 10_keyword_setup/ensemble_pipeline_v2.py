#!/usr/bin/env python3
"""
ensemble_pipeline_v2.py — Ensemble verification pipeline (Round 2).

Scores regenerated keywords using Mistral + OpenAI (API), then Claude (via Claude Code).
Loads keywords from a LOCAL CSV file, uploads to a new Supabase table, scores, computes consensus.

Usage:
    python ensemble_pipeline_v2.py setup --input keywords_new.jsonl           # Create table + load JSONL
    python ensemble_pipeline_v2.py score --model mistral                  # Score with Mistral
    python ensemble_pipeline_v2.py score --model openai                   # Score with OpenAI
    python ensemble_pipeline_v2.py export-for-claude                      # Export CSV for Claude Code
    python ensemble_pipeline_v2.py import-claude --csv claude_all_scored.csv  # Import Claude scores
    python ensemble_pipeline_v2.py ensemble                               # Compute 3-model consensus
    python ensemble_pipeline_v2.py status                                 # Check progress
    python ensemble_pipeline_v2.py report                                 # Generate report

    python ensemble_pipeline_v2.py setup --input keywords_new.jsonl --limit 10   # Test with 10 rows
    python ensemble_pipeline_v2.py score --model mistral --batch-size 3      # Smaller batches
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

TABLE = "keyword_scores_v2"   # new table for regenerated keywords

RESULTS_DIR = Path("results_v2")
DEBUG_DIR = RESULTS_DIR / "debug_responses"

DEFAULT_BATCH_SIZE = 10
DEFAULT_LIMIT = 0   # 0 = load all rows from CSV

RATE_LIMITS = {
    "mistral": 2.0,
    "openai":  1.0,
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

SUPABASE_URL = (
    os.getenv("QA_SUPABASE_URL")
    or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
).rstrip("/")

SUPABASE_KEY = (
    os.getenv("QA_SUPABASE_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")


def check_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Missing Supabase credentials.")
        print("  Set QA_SUPABASE_URL + QA_SUPABASE_KEY in your .env file.")
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
    """POST upsert (works with Discovery cluster proxy)."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict=slug"
    headers = {
        **sb_headers("return=minimal"),
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    data = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        pass


def sb_update_row(table, pk_col, pk_val, updates):
    """Update via POST upsert (avoids PATCH proxy issues)."""
    row = {pk_col: pk_val, **updates}
    sb_upsert(table, [row])

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Setup — Create table and load from CSV
# ─────────────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
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

-- RLS policy so dashboard (anon key) can read
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow anon read on {TABLE}"
    ON {TABLE} FOR SELECT TO anon USING (true);
"""


def make_slug(keyword):
    """Generate a URL-safe slug from a keyword string."""
    slug = keyword.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)   # remove special chars
    slug = re.sub(r'[\s]+', '-', slug)            # spaces to hyphens
    slug = re.sub(r'-+', '-', slug).strip('-')    # collapse multiple hyphens
    return slug


def load_input_file(file_path):
    """Load keywords from CSV or JSONL file. Returns list of dicts with slug/term/category/definition."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".jsonl":
        return load_jsonl(path)
    elif ext in (".csv", ".tsv"):
        return load_csv(path)
    elif ext == ".json":
        # Could be a JSON array or JSONL — try both
        with open(path, "r", encoding="utf-8") as f:
            first_char = f.read(1)
        if first_char == "[":
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return normalize_json_rows(raw)
        else:
            return load_jsonl(path)
    else:
        print(f"ERROR: Unsupported file type '{ext}'. Use .csv, .json, or .jsonl")
        sys.exit(1)


def load_jsonl(path):
    """Load JSONL file — one JSON object per line."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  Warning: skipping line {line_num} (invalid JSON): {e}")
                continue
            rows.append(obj)
    return normalize_json_rows(rows)


def normalize_json_rows(raw_rows):
    """Convert raw JSON objects (from Thejus's format) into our standard format."""
    results = []
    no_def_count = 0
    skipped_no_keyword = 0

    for obj in raw_rows:
        keyword = obj.get("keyword", "").strip()
        if not keyword:
            skipped_no_keyword += 1
            continue

        # Use definition_short for popups, fall back to definition_raw, then definition
        definition = (
            obj.get("definition_short", "")
            or obj.get("definition_raw", "")
            or obj.get("definition", "")
        ).strip()

        if not definition:
            no_def_count += 1
            # Still load it — let the models decide if it's junk or needs a definition

        # Generate slug from keyword if no slug field
        slug = obj.get("slug", "").strip() or make_slug(keyword)

        category = obj.get("category", "").strip()

        results.append({
            "slug":       slug,
            "term":       keyword,
            "category":   category,
            "definition": definition,
        })

    if no_def_count:
        print(f"  {no_def_count} entries have no definition (models will evaluate term/category only)")
    if skipped_no_keyword:
        print(f"  Skipped {skipped_no_keyword} entries with no keyword")

    # Deduplicate by slug (keep first)
    seen = set()
    deduped = []
    for r in results:
        if r["slug"] not in seen:
            seen.add(r["slug"])
            deduped.append(r)
        else:
            pass  # skip duplicate

    if len(deduped) < len(results):
        print(f"  Deduplicated: {len(results)} → {len(deduped)} unique slugs")

    return deduped


def load_csv(path):
    """Load CSV file with auto-detected column mapping."""
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    if not all_rows:
        return []

    # Detect column names
    sample = all_rows[0]
    col_map = {}
    for key in sample.keys():
        lk = key.lower().strip()
        if lk in ("slug", "keyword_slug"):
            col_map["slug"] = key
        elif lk in ("term", "keyword", "keyword_term", "name"):
            col_map["term"] = key
        elif lk in ("category", "keyword_category"):
            col_map["category"] = key
        elif lk in ("definition", "keyword_definition", "description",
                     "definition_short"):
            col_map["definition"] = key

    print(f"  CSV column mapping: {col_map}")

    results = []
    for r in all_rows:
        term = r.get(col_map.get("term", "term"), "").strip()
        slug = r.get(col_map.get("slug", "slug"), "").strip()
        if not slug and term:
            slug = make_slug(term)
        if not slug:
            continue
        results.append({
            "slug":       slug,
            "term":       term,
            "category":   r.get(col_map.get("category", "category"), "").strip(),
            "definition": r.get(col_map.get("definition", "definition"), "").strip(),
        })

    return results


def cmd_setup(args):
    """Create the table and load rows from a CSV or JSONL file."""
    check_supabase()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    print(f"\n  Loading {input_path} ({input_path.suffix})...")
    all_rows = load_input_file(input_path)

    if not all_rows:
        print(f"ERROR: No valid keyword entries found in {input_path}")
        sys.exit(1)

    # Apply limit
    limit = args.limit
    rows = all_rows[:limit] if limit > 0 else all_rows

    print(f"\n{'='*60}")
    print(f"  SETUP: Loading {len(rows)} keywords into {TABLE}")
    print(f"{'='*60}")

    # ── Step 1: Show create table SQL ──
    print(f"\n[1/3] Table creation")
    print(f"  Run this SQL in Supabase Dashboard → SQL Editor:\n")
    print(f"  {'-'*50}")
    print(CREATE_TABLE_SQL)
    print(f"  {'-'*50}")

    # ── Step 2: Check if table exists ──
    print(f"\n[2/3] Checking if {TABLE} exists...")
    try:
        existing = sb_request("GET", f"{TABLE}?select=id&limit=1", prefer="count=none")
        if existing is not None:
            all_existing = sb_fetch_all(f"{TABLE}?select=id")
            print(f"  Table exists with {len(all_existing)} rows.")
            if len(all_existing) > 0 and not args.force:
                print(f"  Table already has data. Use --force to reload, or clear first:")
                print(f"    DELETE FROM {TABLE};")
                return
    except Exception as e:
        if "404" in str(e) or "does not exist" in str(e).lower() or "42P01" in str(e):
            print(f"  Table does NOT exist yet.")
            print(f"  → Run the CREATE TABLE SQL above first, then re-run this command.")
            return
        else:
            print(f"  Warning: {e}")
            print(f"  Trying to continue...")

    # ── Step 3: Insert rows ──
    print(f"\n[3/3] Uploading {len(rows)} rows to {TABLE}...")
    batch_size = 50    # smaller batches to avoid SSL drops
    inserted = 0
    errors = 0
    max_retries = 3

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        batch = [r for r in batch if r["slug"]]

        if not batch:
            continue

        # Retry loop for transient SSL/network errors
        for attempt in range(1, max_retries + 1):
            try:
                sb_upsert(TABLE, batch)
                inserted += len(batch)
                print(f"\r  Inserted {inserted}/{len(rows)} rows...", end="", flush=True)
                break  # success — exit retry loop
            except Exception as e:
                err_str = str(e)
                if attempt < max_retries and ("SSL" in err_str or "timed out" in err_str
                                               or "Connection" in err_str):
                    wait = attempt * 2  # 2s, 4s, 6s
                    print(f"\n  Retry {attempt}/{max_retries} after {wait}s (row {i}): {err_str[:80]}")
                    time.sleep(wait)
                else:
                    print(f"\n  Error at row {i} (attempt {attempt}): {err_str[:120]}")
                    errors += 1
                    break  # give up on this batch, move to next

        # Small delay between batches to avoid throttling
        time.sleep(0.3)

    print(f"\n\n  Done! {inserted} rows loaded into {TABLE}")
    if errors:
        print(f"  Failed batches: {errors} (re-run with --force to retry)")
    print(f"\n  Next steps:")
    print(f"    python ensemble_pipeline_v2.py score --model mistral")
    print(f"    python ensemble_pipeline_v2.py score --model openai")

# ─────────────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """You are a scientific content reviewer for a cancer biology textbook used in a BACHELOR-LEVEL university course.
This textbook covers cancer biology, nanomedicine, biomedical science, and biotechnology.

Your job is to decide what happens to each keyword popup in the textbook. Students see these as clickable popups while reading — so each keyword must be USEFUL to a bachelor student studying cancer biology.

For each keyword entry, assign ONE of these 5 tags:

  "approved"          — Directly relevant to cancer biology or the textbook topics. Term is correct, definition is accurate. SHOW this popup to students.
                        Examples: apoptosis, metastasis, oncogene, tumor suppressor, angiogenesis, chemotherapy

  "supplementary"     — NOT specifically about cancer, but a supporting science term a bachelor student may need a refresher on while reading. Term is correct, definition is accurate. SHOW this popup.
                        Examples: DNA, mitosis, pH, enzyme, protein, ribosome, amino acid, antibody

  "too_basic"         — Too elementary for bachelor-level students (they already know this), OR too irrelevant to the textbook content to justify a popup. Do NOT show.
                        Examples: water, cell, atom, human, brain, temperature, science, hospital

  "fix_definition"    — The term IS relevant and belongs in the textbook, but the definition is wrong, incomplete, broken, or is a disambiguation list ("X can refer to:"). Needs regeneration before showing.
                        Examples: a real cancer term with a Wikipedia disambiguation snippet, a truncated definition, factually incorrect explanation

  "junk"              — Not a real keyword. Wikipedia category pages ("categorynitrogen-cycle"), slugs with formatting artifacts, completely unrelated to science, or nonsense entries. DELETE.
                        Examples: categorynitrogen-cycle, list-of-chemistry-topics, random non-scientific text

DECISION RULES (follow in order):
  1. Is it junk or a formatting artifact? → "junk"
  2. Is the definition EMPTY or MISSING? If the term is valid and relevant, tag as "fix_definition" (it needs a definition written). If the term itself is junk or too basic, tag accordingly.
  3. Is the definition broken, wrong, or a disambiguation list? → "fix_definition"
  4. Is the term too basic for bachelor students OR completely irrelevant to the textbook? → "too_basic"
  5. Is it directly about cancer biology / nanomedicine / biotech / pharmacology? → "approved"
  6. Is it a valid science term that supports understanding of the textbook? → "supplementary"

Also score each entry 0-100 to indicate confidence:
  90-100: Perfect entry, no issues
  70-89:  Good, minor quibbles
  50-69:  Borderline — definition is okay but has issues
  30-49:  Significant problems
  0-29:   Junk or completely broken

EXAMPLES:
  {"slug": "apoptosis", "score": 95, "issue_tag": "approved", "issue_detail": "none"}
  {"slug": "dna", "score": 88, "issue_tag": "supplementary", "issue_detail": "none"}
  {"slug": "water", "score": 30, "issue_tag": "too_basic", "issue_detail": "Too elementary for bachelor-level students"}
  {"slug": "ctl", "score": 35, "issue_tag": "fix_definition", "issue_detail": "Definition is a disambiguation list, not an actual definition"}
  {"slug": "categorynitrogen-cycle", "score": 5, "issue_tag": "junk", "issue_detail": "Wikipedia category page, not a real keyword"}
  {"slug": "antioxidant", "score": 82, "issue_tag": "supplementary", "issue_detail": "none"}
  {"slug": "tumor-microenvironment", "score": 94, "issue_tag": "approved", "issue_detail": "none"}
  {"slug": "cell-cycle", "score": 40, "issue_tag": "fix_definition", "issue_detail": "No definition provided — term is relevant, needs definition generated"}

Respond with ONLY a JSON array. No markdown fences, no explanation, no other text.
Format: [{"slug": "...", "score": 85, "issue_tag": "approved", "issue_detail": "none"}]

If there's an issue, put a brief explanation in "issue_detail" (keep under 200 chars).

Entries to review:

"""


def build_prompt(batch):
    lines = [PROMPT_TEMPLATE]
    for i, row in enumerate(batch, 1):
        lines.append(f"Entry {i}:")
        lines.append(f"  Slug: {row['slug']}")
        lines.append(f"  Term: {row.get('term', '')}")
        lines.append(f"  Category: {row.get('category', '')}")
        defn = (row.get("definition") or "")[:1000]
        lines.append(f"  Definition: {defn}")
        lines.append("")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Model callers
# ─────────────────────────────────────────────────────────────────────────────

def call_mistral(prompt):
    url = "https://api.mistral.ai/v1/chat/completions"
    body = json.dumps({
        "model": "mistral-small-latest",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def call_openai(prompt):
    url = "https://api.openai.com/v1/chat/completions"
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


MODEL_CALLERS = {
    "mistral": call_mistral,
    "openai":  call_openai,
}

# ─────────────────────────────────────────────────────────────────────────────
# JSON parser (robust)
# ─────────────────────────────────────────────────────────────────────────────

def extract_json_array(raw_text):
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

    # Strategy 3: bracket matching
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
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def preflight_check(model_name):
    print(f"  Checking {model_name}...")
    if model_name == "mistral":
        if not MISTRAL_API_KEY:
            print(f"  MISTRAL_API_KEY not set!")
            return False
        try:
            resp = call_mistral("Respond with exactly: [{}]")
            print(f"  Mistral: OK ({len(resp)} chars)")
            return True
        except Exception as e:
            print(f"  Mistral FAILED: {e}")
            return False

    elif model_name == "openai":
        if not OPENAI_API_KEY:
            print(f"  OPENAI_API_KEY not set!")
            return False
        try:
            resp = call_openai("Respond with exactly: [{}]")
            print(f"  OpenAI: OK ({len(resp)} chars)")
            return True
        except Exception as e:
            print(f"  OpenAI FAILED: {e}")
            return False

    return False


def score_one_batch(model_name, caller, batch, batch_idx):
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
    """Run Mistral or OpenAI on all unscored rows."""
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

    # Fetch unscored rows
    print(f"\nFetching unscored rows from {TABLE}...")
    all_rows = sb_fetch_all(
        f"{TABLE}?select=slug,term,category,definition,{score_col}"
    )

    unscored = [r for r in all_rows if r.get(score_col) in (-1, None)]
    already = len(all_rows) - len(unscored)

    print(f"  Total rows: {len(all_rows)}")
    print(f"  Already scored by {model_name}: {already}")
    print(f"  To score: {len(unscored)}")

    if not unscored:
        print(f"  All rows already scored!")
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

        for r in results:
            try:
                sb_update_row(TABLE, "slug", r["slug"], {
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

# ─────────────────────────────────────────────────────────────────────────────
# Claude Code: Export + Import
# ─────────────────────────────────────────────────────────────────────────────

def cmd_export_for_claude(args):
    """Export all keywords as CSV for Claude Code scoring."""
    check_supabase()
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  EXPORTING FOR CLAUDE CODE")
    print(f"{'='*60}")

    rows = sb_fetch_all(f"{TABLE}?select=slug,term,category,definition")
    if not rows:
        print(f"  No rows in {TABLE}.")
        return

    csv_path = RESULTS_DIR / "keywords_for_claude.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["slug", "term", "category", "definition"])
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "slug":       r.get("slug", ""),
                "term":       r.get("term", ""),
                "category":   r.get("category", ""),
                "definition": r.get("definition", ""),
            })

    print(f"  Exported {len(rows)} rows to {csv_path}")
    print(f"\n  Next: split into batches for Claude Code:")
    print(f"    python split_for_claude_v2.py {csv_path}")


def cmd_import_claude(args):
    """Import Claude scores from CSV into Supabase."""
    check_supabase()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        sys.exit(1)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"\n{'='*60}")
    print(f"  IMPORTING CLAUDE SCORES: {len(rows)} rows")
    print(f"{'='*60}")

    # Validate columns
    required = {"slug", "claude_score", "claude_tag", "claude_issue"}
    if rows:
        missing = required - set(rows[0].keys())
        if missing:
            # Try alternate column names
            alt_map = {}
            for key in rows[0].keys():
                lk = key.lower().strip()
                if "score" in lk:
                    alt_map["claude_score"] = key
                elif "tag" in lk:
                    alt_map["claude_tag"] = key
                elif "issue" in lk or "detail" in lk:
                    alt_map["claude_issue"] = key
            if alt_map:
                print(f"  Auto-mapped columns: {alt_map}")
            else:
                print(f"ERROR: CSV missing columns: {missing}")
                print(f"  Expected: slug, claude_score, claude_tag, claude_issue")
                print(f"  Found: {list(rows[0].keys())}")
                sys.exit(1)

    scores = [int(r.get("claude_score", r.get("score", -1))) for r in rows
              if str(r.get("claude_score", r.get("score", ""))).lstrip("-").isdigit()]
    if scores:
        print(f"  Score range: {min(scores)} – {max(scores)}")
        print(f"  Avg: {sum(scores)/len(scores):.1f}")
        print(f"  Below 70: {sum(1 for s in scores if s < 70)}")

    if args.dry_run:
        print("\n  DRY RUN — no data written.")
        return

    # Upload in batches
    batch_size = 100
    uploaded = 0
    errors = 0
    total_batches = (len(rows) + batch_size - 1) // batch_size

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        payload = []
        for r in batch:
            payload.append({
                "slug":        r["slug"],
                "claude_score": int(r.get("claude_score", r.get("score", -1))),
                "claude_tag":   r.get("claude_tag", r.get("issue_tag", "")),
                "claude_issue": r.get("claude_issue", r.get("issue_detail", ""))[:500],
            })

        try:
            sb_upsert(TABLE, payload)
            uploaded += len(batch)
            batch_num = i // batch_size + 1
            print(f"\r  [{batch_num}/{total_batches}] {uploaded}/{len(rows)} uploaded",
                  end="", flush=True)
        except Exception as e:
            print(f"\n  ERROR at row {i}: {e}")
            errors += 1

    print(f"\n\n  DONE: {uploaded} rows uploaded, {errors} errors")

# ─────────────────────────────────────────────────────────────────────────────
# Ensemble — 3-model consensus (Mistral + OpenAI + Claude)
# ─────────────────────────────────────────────────────────────────────────────

def cmd_ensemble(args):
    check_supabase()
    from collections import Counter

    VALID_TAGS = {"approved", "supplementary", "too_basic", "fix_definition", "junk"}
    # Tags that mean "show the popup"
    SHOW_TAGS = {"approved", "supplementary"}

    print(f"\n{'='*60}")
    print(f"  COMPUTING ENSEMBLE CONSENSUS")
    print(f"{'='*60}")

    rows = sb_fetch_all(
        f"{TABLE}?select=slug,mistral_score,openai_score,claude_score,mistral_tag,openai_tag,claude_tag"
    )
    print(f"  {len(rows)} rows loaded")

    updated = 0
    flagged = 0
    consensus_counts = {"ALL_PASS": 0, "ALL_FAIL": 0, "DISAGREE": 0, "NO_DATA": 0}
    action_counts = Counter()
    tag_agree = 0
    tag_disagree = 0

    for row in rows:
        mi = row.get("mistral_score") or -1
        op = row.get("openai_score") or -1
        cl = row.get("claude_score") or -1

        valid_scores = [s for s in [mi, op, cl] if s >= 0]
        avg = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else -1

        # Score-based consensus (same as before)
        if not valid_scores:
            consensus = "NO_DATA"
        else:
            pass_votes = sum(1 for s in valid_scores if s >= 70)
            if pass_votes == len(valid_scores):
                consensus = "ALL_PASS"
            elif pass_votes == 0:
                consensus = "ALL_FAIL"
            else:
                consensus = "DISAGREE"

        # Tag-based consensus — majority vote on the tag
        tags = []
        for m in ["mistral", "openai", "claude"]:
            t = (row.get(f"{m}_tag") or "").strip().lower()
            if t in VALID_TAGS:
                tags.append(t)

        if not tags:
            tag_consensus = "NO_DATA"
            action = "REVIEW"
        elif len(set(tags)) == 1:
            # All models agree on the tag
            tag_consensus = "AGREE"
            tag_agree += 1
            action = tags[0]  # unanimous tag IS the action
        else:
            # Majority vote (2 of 3)
            tag_counts = Counter(tags)
            most_common_tag, most_common_count = tag_counts.most_common(1)[0]
            if most_common_count >= 2:
                tag_consensus = "MAJORITY"
                tag_agree += 1
                action = most_common_tag  # 2/3 agree → use majority tag
            else:
                # All 3 different tags — needs human review
                tag_consensus = "DISAGREE"
                tag_disagree += 1
                action = "REVIEW"

        flag = action not in SHOW_TAGS
        if flag:
            flagged += 1
        consensus_counts[consensus] += 1
        action_counts[action] += 1

        try:
            sb_update_row(TABLE, "slug", row["slug"], {
                "avg_score":      avg,
                "consensus":      consensus,
                "tag_consensus":  tag_consensus,
                "action":         action,
                "flag":           flag,
            })
            updated += 1
        except Exception as e:
            print(f"  [ERROR] {row['slug']}: {e}")

    print(f"\n  Updated: {updated}/{len(rows)} rows")

    print(f"\n  SCORE CONSENSUS:")
    for label, count in consensus_counts.items():
        pct = count / len(rows) * 100 if rows else 0
        print(f"    {label:15s}: {count:4d} ({pct:.1f}%)")

    print(f"\n  TAG AGREEMENT:")
    total_tagged = tag_agree + tag_disagree
    if total_tagged:
        print(f"    Agree/Majority: {tag_agree} ({tag_agree/total_tagged*100:.1f}%)")
        print(f"    Disagree:       {tag_disagree} ({tag_disagree/total_tagged*100:.1f}%)")

    print(f"\n  ACTION BREAKDOWN (what to do with each keyword):")
    for act, count in action_counts.most_common():
        pct = count / len(rows) * 100 if rows else 0
        label = {
            "approved": "SHOW popup",
            "supplementary": "SHOW popup (supporting term)",
            "too_basic": "HIDE (too basic/irrelevant)",
            "fix_definition": "REGENERATE definition",
            "junk": "DELETE",
            "REVIEW": "HUMAN REVIEW (models disagree)",
        }.get(act, act)
        print(f"    {act:20s}: {count:4d} ({pct:.1f}%) — {label}")

    print(f"\n  Flagged (won't show popup): {flagged}/{len(rows)} ({flagged/len(rows)*100:.1f}%)")

# ─────────────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────────────

def cmd_status(args):
    check_supabase()

    print(f"\n{'='*60}")
    print(f"  SCORING STATUS — {TABLE}")
    print(f"{'='*60}")

    rows = sb_fetch_all(
        f"{TABLE}?select=slug,mistral_score,openai_score,claude_score,mistral_tag,openai_tag,claude_tag,consensus,action,flag"
    )

    if not rows:
        print(f"\n  No rows in {TABLE}. Run 'setup' first.")
        return

    print(f"\n  Total rows: {len(rows)}")

    for model in ["mistral", "openai", "claude"]:
        col = f"{model}_score"
        tag_col = f"{model}_tag"
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

        # Tag distribution for this model
        from collections import Counter
        tags = Counter(r.get(tag_col, "") for r in rows if r.get(tag_col))
        if tags:
            tag_str = ", ".join(f"{t}={c}" for t, c in tags.most_common())
            print(f"    Tags: {tag_str}")

    # Consensus / action stats
    with_action = [r for r in rows if r.get("action")]
    if with_action:
        from collections import Counter
        actions = Counter(r["action"] for r in with_action)
        print(f"\n  ACTIONS ({len(with_action)} rows computed):")
        for act, count in actions.most_common():
            print(f"    {act:20s}: {count}")
    else:
        print(f"\n  Actions not yet computed. Run 'ensemble' after all 3 models are done.")

# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def cmd_report(args):
    check_supabase()
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  GENERATING REPORT")
    print(f"{'='*60}")

    rows = sb_fetch_all(f"{TABLE}?select=*")
    if not rows:
        print(f"  No data in {TABLE}.")
        return

    csv_path = RESULTS_DIR / "comparison_report_v2.csv"
    fields = [
        "id", "slug", "term", "category",
        "mistral_score", "mistral_tag", "mistral_issue",
        "openai_score", "openai_tag", "openai_issue",
        "claude_score", "claude_tag", "claude_issue",
        "avg_score", "consensus", "tag_consensus", "action", "flag",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r.get("id", 0)):
            writer.writerow(row)

    print(f"  CSV: {csv_path}")

    total = len(rows)
    summary = []
    summary.append(f"Ensemble Report V2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    summary.append(f"Table: {TABLE} | Rows: {total}")
    summary.append("=" * 60)

    for model in ["mistral", "openai", "claude"]:
        col = f"{model}_score"
        tag_col = f"{model}_tag"
        valid = [r[col] for r in rows if (r.get(col) or -1) >= 0]
        errs = total - len(valid)
        if valid:
            summary.append(f"\n{model.upper()}: {len(valid)}/{total} scored (errors: {errs})")
            summary.append(f"  Avg: {sum(valid)/len(valid):.1f} | "
                           f"Min: {min(valid)} | Max: {max(valid)}")
            summary.append(f"  Below 70: {sum(1 for s in valid if s < 70)}")
            # Tag distribution
            from collections import Counter
            tags = Counter(r.get(tag_col, "") for r in rows if r.get(tag_col))
            tag_str = ", ".join(f"{t}={c}" for t, c in tags.most_common())
            summary.append(f"  Tags: {tag_str}")
        else:
            summary.append(f"\n{model.upper()}: not scored yet")

    from collections import Counter
    cons = Counter(r.get("consensus", "NOT_COMPUTED") for r in rows)
    summary.append(f"\nSCORE CONSENSUS:")
    for label, count in cons.most_common():
        summary.append(f"  {label:15s}: {count} ({count/total*100:.1f}%)")

    actions = Counter(r.get("action", "NOT_COMPUTED") for r in rows)
    summary.append(f"\nACTION BREAKDOWN:")
    for act, count in actions.most_common():
        summary.append(f"  {act:20s}: {count} ({count/total*100:.1f}%)")

    flagged = sum(1 for r in rows if r.get("flag"))
    summary.append(f"\nFlagged (won't show popup): {flagged}/{total}")

    summary.append(f"\nTAG DISAGREEMENTS (all 3 models gave different tags):")
    for row in rows:
        tags = []
        for m in ["mistral", "openai", "claude"]:
            t = row.get(f"{m}_tag") or ""
            if t:
                tags.append((m, t))
        if len(tags) == 3 and len(set(t for _, t in tags)) == 3:
            detail = ", ".join(f"{m}={t}" for m, t in tags)
            summary.append(f"  {row['slug']:40s} | {detail}")

    summary_text = "\n".join(summary)
    summary_path = RESULTS_DIR / "summary_v2.txt"
    summary_path.write_text(summary_text, encoding="utf-8")

    print(f"  Summary: {summary_path}")
    print(f"\n{summary_text}")

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ensemble keyword verification pipeline V2.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  setup              Load keywords from CSV into Supabase table
  score              Run a model (mistral/openai) on unscored rows
  export-for-claude  Export keywords CSV for Claude Code batching
  import-claude      Import Claude scores from CSV
  ensemble           Compute 3-model consensus
  status             Check scoring progress
  report             Generate comparison report

Typical workflow:
  python ensemble_pipeline_v2.py setup --input keywords_new.jsonl
  python ensemble_pipeline_v2.py score --model mistral
  python ensemble_pipeline_v2.py score --model openai
  python ensemble_pipeline_v2.py export-for-claude
  # ... run split_for_claude_v2.py + Claude Code + merge ...
  python ensemble_pipeline_v2.py import-claude --csv claude_all_scored_v2.csv
  python ensemble_pipeline_v2.py ensemble
  python ensemble_pipeline_v2.py report
        """
    )

    sub = parser.add_subparsers(dest="command")

    # setup
    p_setup = sub.add_parser("setup", help="Create table and load CSV/JSONL")
    p_setup.add_argument("--input", required=True,
                         help="Path to keywords file (.csv, .json, or .jsonl)")
    p_setup.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                         help="Max rows to load (0 = all)")
    p_setup.add_argument("--force", action="store_true",
                         help="Overwrite existing data in table")

    # score
    p_score = sub.add_parser("score", help="Run a model on unscored rows")
    p_score.add_argument("--model", required=True, choices=["mistral", "openai"])
    p_score.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                         help=f"Keywords per API call (default: {DEFAULT_BATCH_SIZE})")

    # export-for-claude
    sub.add_parser("export-for-claude", help="Export CSV for Claude Code")

    # import-claude
    p_import = sub.add_parser("import-claude", help="Import Claude scores from CSV")
    p_import.add_argument("--csv", required=True, help="Claude scores CSV file")
    p_import.add_argument("--dry-run", action="store_true", help="Preview without writing")

    # ensemble
    sub.add_parser("ensemble", help="Compute 3-model consensus")

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
        "setup":            cmd_setup,
        "score":            cmd_score,
        "export-for-claude": cmd_export_for_claude,
        "import-claude":    cmd_import_claude,
        "ensemble":         cmd_ensemble,
        "status":           cmd_status,
        "report":           cmd_report,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()