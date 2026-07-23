#!/usr/bin/env python3
"""
acronym_pipeline.py — Ensemble verification for textbook acronym definitions.

Verifies 927 acronym definitions (CSC, FDA, MRI, VEGF, etc.) using 3 LLMs.
Checks: correct expansion, accurate definition, relevance to cancer textbook.

Usage:
    python acronym_pipeline.py setup --input keywords_abbrevs_enriched.jsonl
    python acronym_pipeline.py score --model mistral
    python acronym_pipeline.py score --model openai
    python acronym_pipeline.py export-for-claude
    python acronym_pipeline.py import-claude --csv claude_acronym_scored.csv
    python acronym_pipeline.py ensemble
    python acronym_pipeline.py status
    python acronym_pipeline.py report
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
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

TABLE = "acronym_scores_v1"

RESULTS_DIR = Path("results_acronyms")
DEBUG_DIR = RESULTS_DIR / "debug_responses"

DEFAULT_BATCH_SIZE = 10
DEFAULT_LIMIT = 0

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

SUPABASE_URL = (os.getenv("QA_SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")).rstrip("/")
SUPABASE_KEY = os.getenv("QA_SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
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
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": prefer,
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
    results, offset, limit = [], 0, 1000
    while True:
        sep = "&" if "?" in path else "?"
        batch = sb_request("GET", f"{path}{sep}limit={limit}&offset={offset}", prefer="count=none")
        if not batch:
            break
        results.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return results

def sb_upsert(table, rows):
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict=slug"
    headers = {**sb_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    data = json.dumps(rows).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        pass

def sb_update_row(table, pk_col, pk_val, updates):
    sb_upsert(table, [{pk_col: pk_val, **updates}])

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    acronym TEXT,
    expansion TEXT,
    category TEXT,
    definition TEXT,
    source_url TEXT DEFAULT '',
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

ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow anon read on {TABLE}"
    ON {TABLE} FOR SELECT TO anon USING (true);
"""


def make_slug(keyword):
    slug = keyword.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    return re.sub(r'-+', '-', slug).strip('-')


def extract_expansion(definition):
    """Try to extract the full name from the definition (e.g., 'Cancer stem cell (CSC) ...')."""
    # Match patterns like "Full Name (ACRONYM) ..."
    match = re.match(r'^([^(]+)\s*\([A-Z][A-Z0-9-]+\)', definition)
    if match:
        return match.group(1).strip()
    # Match "The Full Name (ACRONYM) ..."
    match = re.match(r'^(?:The\s+|An?\s+)?([^(]+)\s*\([A-Z][A-Z0-9-]+\)', definition)
    if match:
        return match.group(1).strip()
    return ""


def cmd_setup(args):
    check_supabase()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    # Read JSONL
    raw_rows = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_rows.append(json.loads(line))

    # Normalize
    rows = []
    for obj in raw_rows:
        keyword = obj.get("keyword", "").strip()
        if not keyword:
            continue
        definition = (obj.get("definition_short", "") or obj.get("definition_raw", "") or "").strip()
        slug = make_slug(keyword)
        expansion = extract_expansion(definition)
        rows.append({
            "slug":       slug,
            "acronym":    keyword,
            "expansion":  expansion,
            "category":   obj.get("category", "").strip(),
            "definition": definition,
            "source_url": obj.get("source_url", ""),
        })

    # Dedup
    seen = set()
    deduped = []
    for r in rows:
        if r["slug"] not in seen:
            seen.add(r["slug"])
            deduped.append(r)
    rows = deduped

    if args.limit > 0:
        rows = rows[:args.limit]

    print(f"\n{'='*60}")
    print(f"  SETUP: Loading {len(rows)} acronyms into {TABLE}")
    print(f"{'='*60}")

    # Show SQL
    print(f"\n[1/3] Run this SQL in Supabase Dashboard:\n")
    print(CREATE_TABLE_SQL)

    # Check table
    print(f"\n[2/3] Checking if {TABLE} exists...")
    try:
        existing = sb_request("GET", f"{TABLE}?select=id&limit=1", prefer="count=none")
        if existing is not None:
            all_existing = sb_fetch_all(f"{TABLE}?select=id")
            print(f"  Table exists with {len(all_existing)} rows.")
            if all_existing and not args.force:
                print(f"  Use --force to reload.")
                return
    except Exception as e:
        if "42P01" in str(e) or "does not exist" in str(e).lower() or "404" in str(e):
            print(f"  Table doesn't exist yet. Run the SQL above first.")
            return

    # Upload
    print(f"\n[3/3] Uploading {len(rows)} rows...")
    batch_size = 50
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = [r for r in rows[i:i + batch_size] if r["slug"]]
        if batch:
            for attempt in range(3):
                try:
                    sb_upsert(TABLE, batch)
                    inserted += len(batch)
                    print(f"\r  Inserted {inserted}/{len(rows)} rows...", end="", flush=True)
                    break
                except Exception as e:
                    if attempt < 2 and ("SSL" in str(e) or "timed out" in str(e)):
                        time.sleep(2 * (attempt + 1))
                    else:
                        print(f"\n  Error at row {i}: {e}")
                        break
            time.sleep(0.3)

    print(f"\n\n  Done! {inserted} rows loaded.")
    print(f"\n  Next: python acronym_pipeline.py score --model mistral")

# ─────────────────────────────────────────────────────────────────────────────
# Prompt (acronym-specific)
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """You are verifying acronym/abbreviation definitions for a cancer biology textbook titled "Cancer Biology: A Study of Cancer for the Upcoming AI Era." This is a BACHELOR-LEVEL university course covering cancer biology, nanomedicine, nanotechnology, and biotechnology.

These acronyms were found in the textbook content and definitions were generated from an oncology database. Your job is to verify THREE things for each entry:

1. EXPANSION — Does the acronym expand to the correct full name? (e.g., CSC = Cancer Stem Cell, not something else)
2. DEFINITION — Is the definition factually accurate and useful for students?
3. RELEVANCE — Does this acronym belong in a cancer biology textbook?

IMPORTANT: Relevance is BROAD. The acronym does NOT need to be directly about cancer or genes. If it's something a cancer biology student would encounter while reading the textbook, it's relevant. Examples:
  - WHO (World Health Organization) → relevant (students need to know this)
  - FDA (Food and Drug Administration) → relevant (drug approvals for cancer)
  - NIH (National Institutes of Health) → relevant (funds cancer research)
  - MRI (Magnetic Resonance Imaging) → relevant (cancer diagnostics)
  - PCR (Polymerase Chain Reaction) → relevant (lab technique used in cancer research)
  - NATO → NOT relevant (military alliance, no connection to cancer textbook)

Assign ONE of these 5 tags:

  "approved"          — Acronym expansion is CORRECT, definition is ACCURATE, and it is DIRECTLY relevant to cancer biology, oncology, nanomedicine, biotechnology, or foundational biomedical sciences.
                        Examples: CSC (Cancer Stem Cell), VEGF, BRAF, PD-1, CAR (Chimeric Antigen Receptor), TNM, FISH

  "supplementary"     — Acronym expansion is CORRECT, definition is ACCURATE, and it is INDIRECTLY relevant. Not cancer-specific, but students would encounter it in the textbook or benefit from knowing it.
                        Examples: WHO, FDA, NIH, DNA, RNA, PCR, MRI, CT, NCBI, ELISA, CRISPR

  "fix_definition"    — The acronym IS relevant to the textbook, BUT:
                        - The expansion is WRONG (acronym maps to wrong full name), OR
                        - The definition is inaccurate, misleading, or incomplete, OR
                        - The definition describes a different meaning of the acronym than intended

  "too_basic"         — The acronym is too common/basic for a bachelor student to need a popup (e.g., DNA if your audience already knows it), OR it's a real acronym but completely irrelevant to a cancer biology textbook.

  "junk"              — Not a real acronym, random letters, formatting artifact, or completely nonsensical entry.

Score each entry 0-100:
  90-100: Correct expansion, accurate definition, clearly relevant
  70-89:  Correct expansion, minor definition issues, relevant
  50-69:  Expansion may be off, or definition has notable issues
  30-49:  Wrong expansion or mostly irrelevant
  0-29:   Junk or completely wrong

EXAMPLES:
  {"slug": "csc", "score": 95, "issue_tag": "approved", "issue_detail": "none"}
  {"slug": "who", "score": 85, "issue_tag": "supplementary", "issue_detail": "none"}
  {"slug": "fda", "score": 88, "issue_tag": "supplementary", "issue_detail": "none"}
  {"slug": "vegf", "score": 95, "issue_tag": "approved", "issue_detail": "none"}
  {"slug": "ai", "score": 75, "issue_tag": "fix_definition", "issue_detail": "AI commonly means Artificial Intelligence; expansion as Aromatase Inhibitor needs context clarification"}
  {"slug": "xyz", "score": 10, "issue_tag": "junk", "issue_detail": "Not a recognized acronym"}

Respond with ONLY a JSON array. No markdown fences, no explanation.
Format: [{"slug": "...", "score": 85, "issue_tag": "approved", "issue_detail": "none"}]

Entries to review:

"""


def build_prompt(batch):
    lines = [PROMPT_TEMPLATE]
    for i, row in enumerate(batch, 1):
        lines.append(f"Entry {i}:")
        lines.append(f"  Slug: {row['slug']}")
        lines.append(f"  Acronym: {row.get('acronym', '')}")
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
        "temperature": 0.1, "max_tokens": 4096,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {MISTRAL_API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def call_openai(prompt):
    url = "https://api.openai.com/v1/chat/completions"
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1, "max_tokens": 4096,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


MODEL_CALLERS = {"mistral": call_mistral, "openai": call_openai}

# ─────────────────────────────────────────────────────────────────────────────
# JSON parser
# ─────────────────────────────────────────────────────────────────────────────

def extract_json_array(raw_text):
    text = raw_text.strip()
    for attempt_text in [text, re.sub(r"```(?:json)?\s*", "", re.sub(r"\s*```", "", text)).strip()]:
        try:
            parsed = json.loads(attempt_text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    start = text.find("[")
    if start == -1:
        return None
    depth, end, in_string, escape_next = 0, -1, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False; continue
        if ch == "\\":
            escape_next = True; continue
        if ch == '"':
            in_string = not in_string; continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i; break
    if end == -1:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def preflight_check(model_name):
    print(f"  Checking {model_name}...")
    key = MISTRAL_API_KEY if model_name == "mistral" else OPENAI_API_KEY
    if not key:
        print(f"  {model_name.upper()}_API_KEY not set!")
        return False
    try:
        resp = MODEL_CALLERS[model_name]("Respond with exactly: [{}]")
        print(f"  {model_name}: OK ({len(resp)} chars)")
        return True
    except Exception as e:
        print(f"  {model_name} FAILED: {e}")
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

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    debug_file = DEBUG_DIR / f"{model_name}_batch_{batch_idx:03d}.txt"
    debug_file.write_text(raw_response or "(empty)", encoding="utf-8")

    if not raw_response:
        return [{"slug": r["slug"], "score": -1, "issue_tag": "API_ERROR", "issue_detail": "No response"} for r in batch]

    parsed = extract_json_array(raw_response)
    if parsed is None:
        print(f"\n    [PARSE FAIL] See {debug_file.name}")
        return [{"slug": r["slug"], "score": -1, "issue_tag": "PARSE_ERROR", "issue_detail": f"See {debug_file.name}"} for r in batch]

    results = []
    for row in batch:
        matched = next((s for s in parsed if s.get("slug") == row["slug"]), None)
        if not matched:
            idx = batch.index(row)
            matched = parsed[idx] if idx < len(parsed) else None
        if matched:
            results.append({
                "slug": row["slug"], "score": matched.get("score", -1),
                "issue_tag": matched.get("issue_tag", "unknown"),
                "issue_detail": str(matched.get("issue_detail", ""))[:500],
            })
        else:
            results.append({"slug": row["slug"], "score": -1, "issue_tag": "MISSING_FROM_RESPONSE",
                            "issue_detail": f"Model returned {len(parsed)} items for {len(batch)} entries"})
    return results


def cmd_score(args):
    check_supabase()
    model_name = args.model
    batch_size = args.batch_size
    score_col, issue_col, tag_col = f"{model_name}_score", f"{model_name}_issue", f"{model_name}_tag"

    print(f"\n{'='*60}")
    print(f"  SCORING ACRONYMS: {model_name.upper()}")
    print(f"{'='*60}")

    if not preflight_check(model_name):
        return

    all_rows = sb_fetch_all(f"{TABLE}?select=slug,acronym,category,definition,{score_col}")
    unscored = [r for r in all_rows if r.get(score_col) in (-1, None)]
    print(f"\n  Total: {len(all_rows)} | Already scored: {len(all_rows) - len(unscored)} | To score: {len(unscored)}")

    if not unscored:
        print(f"  All rows already scored!")
        return

    caller = MODEL_CALLERS[model_name]
    delay = RATE_LIMITS.get(model_name, 2.0)
    total_batches = math.ceil(len(unscored) / batch_size)
    print(f"  Batches: {total_batches} | Batch size: {batch_size}\n")

    scored, errors, start_time = 0, 0, time.time()

    for batch_idx in range(total_batches):
        batch = unscored[batch_idx * batch_size:(batch_idx + 1) * batch_size]
        results = score_one_batch(model_name, caller, batch, batch_idx)

        for r in results:
            try:
                sb_update_row(TABLE, "slug", r["slug"], {
                    score_col: r["score"], issue_col: r["issue_detail"], tag_col: r["issue_tag"],
                    "scored_at": datetime.now(timezone.utc).isoformat(),
                })
                scored += 1
            except Exception as e:
                print(f"\n    [DB ERROR] {r['slug']}: {e}")
                errors += 1

        elapsed = time.time() - start_time
        pct = (batch_idx + 1) / total_batches * 100
        print(f"\r  [{batch_idx+1}/{total_batches}] {pct:.0f}% | {scored} scored | {errors} errors | {elapsed:.0f}s", end="", flush=True)

        if batch_idx < total_batches - 1:
            time.sleep(delay)

    print(f"\n\n  DONE: {scored} scored by {model_name} in {time.time() - start_time:.0f}s")

# ─────────────────────────────────────────────────────────────────────────────
# Claude: Export + Import
# ─────────────────────────────────────────────────────────────────────────────

def cmd_export_for_claude(args):
    check_supabase()
    RESULTS_DIR.mkdir(exist_ok=True)

    rows = sb_fetch_all(f"{TABLE}?select=slug,acronym,category,definition")
    csv_path = RESULTS_DIR / "acronyms_for_claude.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["slug", "acronym", "category", "definition"])
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in ["slug", "acronym", "category", "definition"]})

    print(f"\n  Exported {len(rows)} acronyms to {csv_path}")
    print(f"\n  Next: in Claude Code paste:")
    print(f"    Read claude_acronym_prompt.md for instructions. Score ALL keywords in {csv_path} and save output as claude_acronym_scored.csv")


def cmd_import_claude(args):
    check_supabase()
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found"); sys.exit(1)

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"\n{'='*60}")
    print(f"  IMPORTING CLAUDE SCORES: {len(rows)} rows")
    print(f"{'='*60}")

    scores = [int(r.get("claude_score", r.get("score", -1))) for r in rows
              if str(r.get("claude_score", r.get("score", ""))).lstrip("-").isdigit()]
    if scores:
        print(f"  Score range: {min(scores)} – {max(scores)} | Avg: {sum(scores)/len(scores):.1f}")

    if args.dry_run:
        print("\n  DRY RUN — no data written."); return

    batch_size, uploaded, errors = 100, 0, 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        payload = [{
            "slug": r["slug"],
            "claude_score": int(r.get("claude_score", r.get("score", -1))),
            "claude_tag": r.get("claude_tag", r.get("issue_tag", "")),
            "claude_issue": r.get("claude_issue", r.get("issue_detail", ""))[:500],
        } for r in batch]
        try:
            sb_upsert(TABLE, payload)
            uploaded += len(batch)
            print(f"\r  [{i//batch_size+1}] {uploaded}/{len(rows)} uploaded", end="", flush=True)
        except Exception as e:
            print(f"\n  ERROR at row {i}: {e}"); errors += 1

    print(f"\n\n  DONE: {uploaded} rows uploaded, {errors} errors")

# ─────────────────────────────────────────────────────────────────────────────
# Ensemble
# ─────────────────────────────────────────────────────────────────────────────

def cmd_ensemble(args):
    check_supabase()
    VALID_TAGS = {"approved", "supplementary", "too_basic", "fix_definition", "junk"}
    SHOW_TAGS = {"approved", "supplementary"}

    print(f"\n{'='*60}")
    print(f"  COMPUTING ACRONYM ENSEMBLE CONSENSUS")
    print(f"{'='*60}")

    rows = sb_fetch_all(f"{TABLE}?select=slug,mistral_score,openai_score,claude_score,mistral_tag,openai_tag,claude_tag")
    print(f"  {len(rows)} rows loaded")

    updated, flagged = 0, 0
    consensus_counts = {"ALL_PASS": 0, "ALL_FAIL": 0, "DISAGREE": 0, "NO_DATA": 0}
    action_counts = Counter()
    tag_agree, tag_disagree = 0, 0

    for row in rows:
        scores = {m: row.get(f"{m}_score") or -1 for m in ["mistral", "openai", "claude"]}
        valid_scores = [s for s in scores.values() if s >= 0]
        avg = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else -1

        if not valid_scores:
            consensus = "NO_DATA"
        else:
            pass_votes = sum(1 for s in valid_scores if s >= 70)
            consensus = "ALL_PASS" if pass_votes == len(valid_scores) else ("ALL_FAIL" if pass_votes == 0 else "DISAGREE")

        tags = [(row.get(f"{m}_tag") or "").strip().lower() for m in ["mistral", "openai", "claude"]]
        tags = [t for t in tags if t in VALID_TAGS]

        if not tags:
            tag_consensus, action = "NO_DATA", "REVIEW"
        elif len(set(tags)) == 1:
            tag_consensus, action = "AGREE", tags[0]
            tag_agree += 1
        else:
            tc = Counter(tags)
            top_tag, top_count = tc.most_common(1)[0]
            if top_count >= 2:
                tag_consensus, action = "MAJORITY", top_tag
                tag_agree += 1
            else:
                tag_consensus, action = "DISAGREE", "REVIEW"
                tag_disagree += 1

        flag = action not in SHOW_TAGS

        # Override: if avg score >= 75, auto-approve (resolve borderline cases)
        if avg >= 75 and action not in SHOW_TAGS:
            action = "approved"
            flag = False
        if flag: flagged += 1
        consensus_counts[consensus] += 1
        action_counts[action] += 1

        try:
            sb_update_row(TABLE, "slug", row["slug"], {
                "avg_score": avg, "consensus": consensus, "tag_consensus": tag_consensus,
                "action": action, "flag": flag,
            })
            updated += 1
        except Exception as e:
            print(f"  [ERROR] {row['slug']}: {e}")

    print(f"\n  Updated: {updated}/{len(rows)}")
    print(f"\n  SCORE CONSENSUS:")
    for label, count in consensus_counts.items():
        print(f"    {label:15s}: {count:4d} ({count/len(rows)*100:.1f}%)")
    print(f"\n  TAG AGREEMENT: {tag_agree} agree/majority, {tag_disagree} disagree ({tag_agree/(tag_agree+tag_disagree)*100:.1f}% agreement)" if tag_agree + tag_disagree else "")
    print(f"\n  ACTION BREAKDOWN:")
    for act, count in action_counts.most_common():
        print(f"    {act:20s}: {count:4d} ({count/len(rows)*100:.1f}%)")
    print(f"\n  Flagged: {flagged}/{len(rows)} ({flagged/len(rows)*100:.1f}%)")

# ─────────────────────────────────────────────────────────────────────────────
# Status + Report
# ─────────────────────────────────────────────────────────────────────────────

def cmd_status(args):
    check_supabase()
    print(f"\n{'='*60}")
    print(f"  ACRONYM SCORING STATUS — {TABLE}")
    print(f"{'='*60}")

    rows = sb_fetch_all(f"{TABLE}?select=slug,mistral_score,openai_score,claude_score,mistral_tag,openai_tag,claude_tag,action")
    if not rows:
        print(f"\n  No rows. Run 'setup' first."); return

    print(f"\n  Total: {len(rows)}")
    for model in ["mistral", "openai", "claude"]:
        col = f"{model}_score"
        valid = [r[col] for r in rows if (r.get(col) or -1) >= 0]
        print(f"\n  {model.upper():10s}: {len(valid)}/{len(rows)} scored")
        if valid:
            print(f"    Avg: {sum(valid)/len(valid):.1f} | Min: {min(valid)} | Max: {max(valid)} | Below 70: {sum(1 for s in valid if s < 70)}")
            tags = Counter(r.get(f"{model}_tag", "") for r in rows if r.get(f"{model}_tag"))
            print(f"    Tags: {', '.join(f'{t}={c}' for t, c in tags.most_common())}")

    actions = Counter(r.get("action", "") for r in rows if r.get("action"))
    if actions:
        print(f"\n  ACTIONS:")
        for act, count in actions.most_common():
            print(f"    {act:20s}: {count}")


def cmd_report(args):
    check_supabase()
    RESULTS_DIR.mkdir(exist_ok=True)

    rows = sb_fetch_all(f"{TABLE}?select=*")
    if not rows:
        print(f"  No data."); return

    csv_path = RESULTS_DIR / "acronym_report.csv"
    fields = ["id", "slug", "acronym", "expansion", "category", "definition",
              "mistral_score", "mistral_tag", "mistral_issue",
              "openai_score", "openai_tag", "openai_issue",
              "claude_score", "claude_tag", "claude_issue",
              "avg_score", "consensus", "tag_consensus", "action", "flag"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r.get("id", 0)):
            writer.writerow(row)

    print(f"\n  Report: {csv_path} ({len(rows)} rows)")

    # Summary
    total = len(rows)
    actions = Counter(r.get("action", "NOT_COMPUTED") for r in rows)
    print(f"\n  ACTION BREAKDOWN:")
    for act, count in actions.most_common():
        print(f"    {act:20s}: {count} ({count/total*100:.1f}%)")

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Acronym verification ensemble pipeline")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("setup")
    p.add_argument("--input", required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("score")
    p.add_argument("--model", required=True, choices=["mistral", "openai"])
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    sub.add_parser("export-for-claude")

    p = sub.add_parser("import-claude")
    p.add_argument("--csv", required=True)
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("ensemble")
    sub.add_parser("status")
    sub.add_parser("report")

    args = parser.parse_args()
    if not args.command:
        parser.print_help(); return

    RESULTS_DIR.mkdir(exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    {"setup": cmd_setup, "score": cmd_score, "export-for-claude": cmd_export_for_claude,
     "import-claude": cmd_import_claude, "ensemble": cmd_ensemble,
     "status": cmd_status, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()