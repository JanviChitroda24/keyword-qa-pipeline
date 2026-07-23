#!/usr/bin/env python3
"""
ensemble_verify.py — Ensemble LLM verification of keyword definitions.

Reads keywords from your QA Supabase (keyword_scores table),
sends each to Gemini + Mistral (+ Llama when cluster is ready),
and writes confidence scores back to Supabase.

Usage:
    python ensemble_verify.py                          # run all available models
    python ensemble_verify.py --model gemini           # run only Gemini
    python ensemble_verify.py --model mistral          # run only Mistral
    python ensemble_verify.py --model llama            # run only Llama
    python ensemble_verify.py --batch-size 3           # custom batch size
    python ensemble_verify.py --ensemble-only          # just compute ensemble from existing scores
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def load_dotenv():
    for p in [Path(__file__).parent / ".env", Path.cwd() / ".env"]:
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
            return

load_dotenv()

# --- API Keys ---
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OLLAMA_URL      = os.getenv("OLLAMA_URL", "http://localhost:11434")

# --- QA Supabase (your own project for scoring) ---
QA_SUPABASE_URL = os.getenv("QA_SUPABASE_URL", "").rstrip("/")
QA_SUPABASE_KEY = os.getenv("QA_SUPABASE_KEY", "")

if not QA_SUPABASE_URL or not QA_SUPABASE_KEY:
    print("ERROR: Missing QA_SUPABASE_URL or QA_SUPABASE_KEY in .env", file=sys.stderr)
    sys.exit(1)

QA_HEADERS = {
    "apikey":        QA_SUPABASE_KEY,
    "Authorization": f"Bearer {QA_SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

BATCH_SIZE = 5

# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def supabase_fetch(endpoint: str) -> list[dict]:
    """Fetch all rows from a Supabase endpoint (handles pagination)."""
    results = []
    offset  = 0
    limit   = 1000
    while True:
        url = f"{QA_SUPABASE_URL}/rest/v1/{endpoint}&limit={limit}&offset={offset}"
        req = urllib.request.Request(url, headers={**QA_HEADERS, "Prefer": "count=none"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.loads(resp.read())
            results.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
    return results


def supabase_update(slug: str, updates: dict):
    """Update a single row in keyword_scores by slug."""
    url = f"{QA_SUPABASE_URL}/rest/v1/keyword_scores?slug=eq.{urllib.request.quote(slug)}"
    body = json.dumps(updates).encode()
    req = urllib.request.Request(url, data=body, method="PATCH", headers=QA_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        pass

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

VERIFICATION_PROMPT = """You are a scientific content reviewer for a cancer biology textbook.
For each keyword entry below, verify:
1. Is the TERM correctly named?
2. Is the CATEGORY appropriate? Valid categories: Biochemistry, Molecular Biology, Cell Biology, Oncology, Biomedical Science, Pharmacology, Biotechnology, Genetics, Diagnostics, Immunology, Nanotechnology, Chemistry, Anatomy, Nanomedicine
3. Is the DEFINITION accurate, complete, and well-written?

Score each entry from 0 to 100:
- 90-100: Correct term, right category, accurate and clear definition
- 70-89: Mostly correct, minor issues (e.g. slightly vague definition)
- 50-69: Notable issues (e.g. wrong category, incomplete definition)
- 0-49: Serious problems (e.g. wrong topic entirely, broken text, factually wrong)

Respond ONLY with a JSON array, one object per entry. No other text.
Example: [{"slug": "example-slug", "score": 85, "issue": "none"}]

If there is an issue, briefly describe it in the "issue" field.
If no issue, set "issue" to "none".

Here are the entries to verify:

"""

def build_prompt(batch: list[dict]) -> str:
    prompt = VERIFICATION_PROMPT
    for i, row in enumerate(batch, 1):
        prompt += f"Entry {i}:\n"
        prompt += f"  Slug: {row['slug']}\n"
        prompt += f"  Term: {row['term']}\n"
        prompt += f"  Category: {row['category']}\n"
        prompt += f"  Definition: {row['definition']}\n\n"
    return prompt

# ---------------------------------------------------------------------------
# Model callers
# ---------------------------------------------------------------------------

def call_gemini(prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_mistral(prompt: str) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"
    body = json.dumps({
        "model": "mistral-small-latest",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1024,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def call_llama(prompt: str) -> str:
    url = f"{OLLAMA_URL}/api/generate"
    body = json.dumps({
        "model": "llama3.1:8b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["response"]

# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_scores(response_text: str, batch: list[dict]) -> list[dict]:
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.replace("```json", "").replace("```", "").strip()

    try:
        scores = json.loads(text)
        if isinstance(scores, list):
            return scores
    except json.JSONDecodeError:
        pass

    return [{"slug": row["slug"], "score": -1, "issue": "PARSE_ERROR"} for row in batch]

# ---------------------------------------------------------------------------
# Batch processor
# ---------------------------------------------------------------------------

def process_model(model_name: str, caller, rows: list[dict],
                  score_col: str, issue_col: str,
                  rate_limit_delay: float, batch_size: int):
    """Process all rows through a single model, writing scores to Supabase."""
    unscored = [r for r in rows if r.get(score_col) == -1 or r.get(score_col) is None]
    total_batches = math.ceil(len(unscored) / batch_size) if unscored else 0
    errors = 0
    scored = 0

    print(f"\n{'='*60}")
    print(f"  Model: {model_name.upper()}")
    print(f"  Total rows: {len(rows)} | Already scored: {len(rows) - len(unscored)}")
    print(f"  To score: {len(unscored)} | Batch size: {batch_size} | Batches: {total_batches}")
    print(f"{'='*60}")

    if not unscored:
        print(f"  All rows already scored. Skipping.")
        return

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end   = min(start + batch_size, len(unscored))
        batch = unscored[start:end]

        prompt = build_prompt(batch)

        try:
            response = caller(prompt)
            scores   = parse_scores(response, batch)

            for row in batch:
                matched = next((s for s in scores if s.get("slug") == row["slug"]), None)
                if not matched:
                    idx_in_batch = batch.index(row)
                    matched = scores[idx_in_batch] if idx_in_batch < len(scores) else None

                if matched:
                    score = matched.get("score", -1)
                    issue = matched.get("issue", "unknown")
                else:
                    score = -1
                    issue = "MISSING_FROM_RESPONSE"

                try:
                    supabase_update(row["slug"], {
                        score_col: score,
                        issue_col: issue[:500],
                    })
                    scored += 1
                except Exception as e:
                    print(f"\n  [DB ERROR] {row['slug']}: {e}")
                    errors += 1

        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:200]
            print(f"\n  [API ERROR] Batch {batch_idx+1}: HTTP {e.code} — {error_body}")
            errors += 1
            if e.code == 429:
                print(f"  Rate limited. Waiting 60s...")
                time.sleep(60)

        except Exception as e:
            print(f"\n  [ERROR] Batch {batch_idx+1}: {e}")
            errors += 1

        pct = (batch_idx + 1) / total_batches * 100
        print(f"\r  Progress: {batch_idx+1}/{total_batches} batches ({pct:.1f}%) "
              f"| {scored} scored | {errors} errors", end="", flush=True)

        if rate_limit_delay > 0:
            time.sleep(rate_limit_delay)

    print(f"\n  Done: {scored} rows scored, {errors} errors")

# ---------------------------------------------------------------------------
# Ensemble calculation
# ---------------------------------------------------------------------------

def compute_ensemble():
    """Compute avg_score, consensus, and flag for all rows."""
    print(f"\n{'='*60}")
    print(f"  COMPUTING ENSEMBLE SCORES")
    print(f"{'='*60}")

    rows = supabase_fetch("keyword_scores?select=slug,gemini_score,mistral_score,llama_score")

    flagged = 0
    updated = 0

    for row in rows:
        g = row.get("gemini_score") or -1
        m = row.get("mistral_score") or -1
        l = row.get("llama_score") or -1

        valid = [s for s in [g, m, l] if s >= 0]
        avg = round(sum(valid) / len(valid), 1) if valid else -1

        good_votes = sum(1 for s in valid if s >= 70)
        if not valid:
            consensus = "NO_DATA"
        elif good_votes == len(valid):
            consensus = "ALL_PASS"
        elif good_votes == 0:
            consensus = "ALL_FAIL"
        else:
            consensus = "DISAGREE"

        flag = consensus != "ALL_PASS"
        if flag:
            flagged += 1

        try:
            supabase_update(row["slug"], {
                "avg_score": avg,
                "consensus": consensus,
                "flag": flag,
            })
            updated += 1
        except Exception as e:
            print(f"  [ERROR] {row['slug']}: {e}")

        if updated % 100 == 0 and updated > 0:
            print(f"\r  Updated {updated}/{len(rows)} rows...", end="", flush=True)

    print(f"\n\n  RESULTS:")
    print(f"  Total entries   : {len(rows)}")
    print(f"  Flagged entries : {flagged} ({flagged/len(rows)*100:.1f}%)")
    print(f"  Clean entries   : {len(rows)-flagged} ({(len(rows)-flagged)/len(rows)*100:.1f}%)")
    print(f"{'='*60}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Ensemble LLM verification of keywords.")
    p.add_argument("--model", choices=["gemini", "mistral", "llama", "all"],
                   default="all", help="Which model to run (default: all)")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                   help=f"Rows per API call (default: {BATCH_SIZE})")
    p.add_argument("--limit", type=int, default=0,
                   help="Only process first N rows (default: 0 = all rows)")
    p.add_argument("--ensemble-only", action="store_true",
                   help="Skip scoring, just compute ensemble from existing scores")
    return p.parse_args()


def main():
    args = parse_args()

    if args.ensemble_only:
        compute_ensemble()
        return

    print("Fetching keywords from Supabase...")
    rows = supabase_fetch(
        "keyword_scores?select=slug,term,category,definition,"
        "gemini_score,mistral_score,llama_score"
    )
    print(f"  {len(rows)} keywords loaded.")

    # Apply limit if specified
    if args.limit > 0:
        rows = rows[:args.limit]
        print(f"  Limited to first {args.limit} rows for testing.")

    if args.model in ("gemini", "all"):
        if not GEMINI_API_KEY:
            print("WARNING: GEMINI_API_KEY not set, skipping Gemini.", file=sys.stderr)
        else:
            process_model("gemini", call_gemini, rows,
                          "gemini_score", "gemini_issue",
                          rate_limit_delay=6.5,
                          batch_size=args.batch_size)

    if args.model in ("mistral", "all"):
        if not MISTRAL_API_KEY:
            print("WARNING: MISTRAL_API_KEY not set, skipping Mistral.", file=sys.stderr)
        else:
            process_model("mistral", call_mistral, rows,
                          "mistral_score", "mistral_issue",
                          rate_limit_delay=2.0,
                          batch_size=args.batch_size)

    if args.model in ("llama", "all"):
        process_model("llama", call_llama, rows,
                      "llama_score", "llama_issue",
                      rate_limit_delay=0,
                      batch_size=args.batch_size)

    compute_ensemble()


if __name__ == "__main__":
    main()