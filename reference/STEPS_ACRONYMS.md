# Acronym QA Pipeline — Step-by-Step Guide

## Overview
Verify 927 acronym definitions from the cancer biology textbook using 3-model ensemble:
- **Mistral Small** (API)
- **OpenAI GPT-4o-mini** (API)
- **Claude** (Claude Code)

Table: `acronym_scores_v1` in Supabase.

---

## Folder Setup
Create a new folder and add these files:
```
acronym_qa/
  acronym_pipeline.py          # Main pipeline
  claude_acronym_prompt.md     # Claude Code instructions
  keywords_abbrevs_enriched.jsonl  # Input data (from Thejus)
  .env                         # Copy from your keyword pipeline
```

## .env File (same keys as before)
```
QA_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
QA_SUPABASE_KEY=eyJhbG...
MISTRAL_API_KEY=your_mistral_key
OPENAI_API_KEY=your_openai_key
```

---

## Step 1: Create Supabase Table

```bash
python acronym_pipeline.py setup --input keywords_abbrevs_enriched.jsonl
```

Copy the SQL it prints and run it in **Supabase Dashboard → SQL Editor**. Then re-run the same command.

---

## Step 2: Score with Mistral + OpenAI

```bash
python acronym_pipeline.py score --model mistral
python acronym_pipeline.py score --model openai
```

927 rows at batch size 10 = ~93 batches each. Should take ~15-20 min per model.

Check progress:
```bash
python acronym_pipeline.py status
```

---

## Step 3: Score with Claude (Claude Code)

```bash
python acronym_pipeline.py export-for-claude
```

Then in Claude Code paste:
```
Read claude_acronym_prompt.md for the scoring instructions. Score ALL acronyms in results_acronyms/acronyms_for_claude.csv and save output as claude_acronym_scored.csv
```

927 rows is small enough for one Claude Code session.

---

## Step 4: Import Claude + Compute Consensus

```bash
python acronym_pipeline.py import-claude --csv claude_acronym_scored.csv
python acronym_pipeline.py ensemble
python acronym_pipeline.py status
python acronym_pipeline.py report
```

---

## Quick Reference
```bash
# Full workflow:
python acronym_pipeline.py setup --input keywords_abbrevs_enriched.jsonl
python acronym_pipeline.py score --model mistral
python acronym_pipeline.py score --model openai
python acronym_pipeline.py export-for-claude
# ... Claude Code scoring ...
python acronym_pipeline.py import-claude --csv claude_acronym_scored.csv
python acronym_pipeline.py ensemble
python acronym_pipeline.py status
python acronym_pipeline.py report
```

---

## Tag System (same 5 tags, acronym context)

| Tag | Meaning | Action |
|-----|---------|--------|
| `approved` | Correct expansion, accurate definition, directly relevant | ✅ Show popup |
| `supplementary` | Correct expansion, accurate definition, indirectly relevant (WHO, FDA) | ✅ Show popup |
| `too_basic` | Too common or irrelevant to textbook | ❌ Hide |
| `fix_definition` | Wrong expansion or inaccurate definition | 🔄 Fix |
| `junk` | Not a real acronym, noise | 🗑️ Delete |
