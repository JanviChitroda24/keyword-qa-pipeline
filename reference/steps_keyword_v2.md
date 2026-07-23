# Keyword QA Pipeline V2 — Step-by-Step Guide

## Overview
Re-score Thejus's regenerated keywords using 3-model ensemble:
- **Mistral Small** (API) — via ensemble_pipeline_v2.py
- **OpenAI GPT-4o-mini** (API) — via ensemble_pipeline_v2.py
- **Claude** (Claude Code CLI) — via split/merge scripts

New table: `keyword_scores_v2` in Supabase.

---

## Files You Need
| File | Where to run | Purpose |
|------|-------------|---------|
| `ensemble_pipeline_v2.py` | Discovery cluster | Main pipeline (setup, score, ensemble, report) |
| `split_for_claude_v2.py` | Laptop | Split CSV into 500-row batches for Claude Code |
| `merge_claude_scores_v2.py` | Laptop | Merge Claude batch outputs into one CSV |
| `.env` | Both | API keys and Supabase credentials |

## .env File (same as before, just make sure these are set)
```
QA_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
QA_SUPABASE_KEY=eyJhbG...    # service_role key (starts with eyJ)
MISTRAL_API_KEY=your_mistral_key
OPENAI_API_KEY=your_openai_key
```

---

## Tag System (5 tags)

Each model assigns one of these tags to every keyword:

| Tag | Meaning | Action |
|-----|---------|--------|
| `approved` | Core cancer biology term, correct definition | ✅ Show popup |
| `supplementary` | Not cancer-specific but useful for students (DNA, pH, protein) | ✅ Show popup |
| `too_basic` | Too elementary for bachelor level OR irrelevant | ❌ Hide |
| `fix_definition` | Good term but definition is broken/wrong | 🔄 Regenerate |
| `junk` | Wikipedia artifact, garbage, not a real keyword | 🗑️ Delete |

The `ensemble` command computes:
- **consensus** — score-based (ALL_PASS/ALL_FAIL/DISAGREE)
- **tag_consensus** — AGREE (3/3 same tag), MAJORITY (2/3 same), DISAGREE (all different)
- **action** — the majority tag (what to DO with the keyword). If all 3 disagree → REVIEW

---

## Step 1: Create Supabase Table

Go to **Supabase Dashboard → SQL Editor** and run:

```sql
CREATE TABLE IF NOT EXISTS keyword_scores_v2 (
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

-- Allow dashboard (anon key) to read
ALTER TABLE keyword_scores_v2 ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow anon read on keyword_scores_v2"
    ON keyword_scores_v2 FOR SELECT TO anon USING (true);
```

---

## Step 2: Upload Keywords from JSONL

```bash
# The input file is keywords_new.jsonl (10,055 entries, ALL loaded)
# Auto-detects JSONL, maps fields, generates slugs
# 1,322 entries have no definition — models will evaluate and tag them
python ensemble_pipeline_v2.py setup --input keywords_new.jsonl
```

To test with a small subset first:
```bash
python ensemble_pipeline_v2.py setup --input keywords_new.jsonl --limit 20
```

If the table already has data and you want to reload:
```bash
# Option A: clear in Supabase SQL Editor first
#   DELETE FROM keyword_scores_v2;
# Then re-run setup

# Option B: force overwrite (upserts on slug)
python ensemble_pipeline_v2.py setup --input keywords_new.jsonl --force
```

**Field mapping from JSONL:**

| JSONL field | Table column | Notes |
|-------------|-------------|-------|
| `keyword` | `term` | Display name |
| (auto-generated) | `slug` | Lowercase, hyphenated from keyword |
| `category` | `category` | As-is |
| `definition_short` | `definition` | Used for popup + scoring (avg 271 chars) |
| `relevant=False` | (loaded with empty definition) | 1,322 entries — models will tag as junk/too_basic/fix_definition |

---

## Step 3: Score with Mistral (on Discovery cluster)

```bash
python ensemble_pipeline_v2.py score --model mistral
```

Default batch size is 5 keywords per API call. Adjust if needed:
```bash
python ensemble_pipeline_v2.py score --model mistral --batch-size 10
```

Check progress anytime:
```bash
python ensemble_pipeline_v2.py status
```

---

## Step 4: Score with OpenAI (on Discovery cluster)

```bash
python ensemble_pipeline_v2.py score --model openai
```

---

## Step 5: Score with Claude (on laptop via Claude Code)

### 5a. Export keywords for Claude
```bash
python ensemble_pipeline_v2.py export-for-claude
# Creates: results_v2/keywords_for_claude.csv
```

### 5b. Split into batches
```bash
python split_for_claude_v2.py results_v2/keywords_for_claude.csv
# Creates: claude_batches_v2/batch_001.csv, batch_002.csv, ...
# Also creates: claude_batches_v2/claude_scoring_prompt.md
```

### 5c. Run Claude Code on each batch
For each batch file, run:
```bash
claude -p "Read claude_batches_v2/claude_scoring_prompt.md for instructions. \
Score the keywords in claude_batches_v2/batch_001.csv \
Save output as claude_batches_v2/batch_001_scored.csv"
```

Repeat for batch_002, batch_003, etc. You can script this:
```bash
for i in $(ls claude_batches_v2/batch_*.csv | grep -v scored); do
    batch_name=$(basename "$i" .csv)
    echo "Scoring $batch_name..."
    claude -p "Read claude_batches_v2/claude_scoring_prompt.md for instructions. \
Score the keywords in $i \
Save output as claude_batches_v2/${batch_name}_scored.csv"
done
```

### 5d. Merge Claude results
```bash
python merge_claude_scores_v2.py
# Creates: claude_all_scored_v2.csv
```

### 5e. Upload Claude scores to Supabase
```bash
# Preview first
python ensemble_pipeline_v2.py import-claude --csv claude_all_scored_v2.csv --dry-run

# Upload
python ensemble_pipeline_v2.py import-claude --csv claude_all_scored_v2.csv
```

---

## Step 6: Compute Ensemble Consensus

```bash
python ensemble_pipeline_v2.py ensemble
```

This computes for each keyword:
- **avg_score** — average of all valid model scores
- **consensus** — ALL_PASS (all ≥70), ALL_FAIL (all <70), DISAGREE (mixed)
- **flag** — true if not ALL_PASS

---

## Step 7: Generate Report

```bash
python ensemble_pipeline_v2.py report
# Creates: results_v2/comparison_report_v2.csv
#          results_v2/summary_v2.txt
```

---

## Quick Reference

```bash
# Full happy-path workflow:
python ensemble_pipeline_v2.py setup --input keywords_new.jsonl
python ensemble_pipeline_v2.py score --model mistral
python ensemble_pipeline_v2.py score --model openai
python ensemble_pipeline_v2.py export-for-claude
python split_for_claude_v2.py results_v2/keywords_for_claude.csv
# ... Claude Code scoring ...
python merge_claude_scores_v2.py
python ensemble_pipeline_v2.py import-claude --csv claude_all_scored_v2.csv
python ensemble_pipeline_v2.py ensemble
python ensemble_pipeline_v2.py status
python ensemble_pipeline_v2.py report
```