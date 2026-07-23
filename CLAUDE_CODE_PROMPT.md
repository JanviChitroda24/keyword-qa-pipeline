# Claude Code Prompt — Keyword QA Pipeline App

Paste the "Prompt" section below into Claude Code to rebuild this as a standalone, reusable CLI for any textbook subject. Read the "Background" section first.

---

## Background (read this first)

This is the **quality-assurance half** of a keyword popup system. The other half (Wikipedia extract → LLM definitions → abbreviation scan → merge → upload) is stages `00`–`07` in the Keyword Popup Pipeline. This package is stages `10`–`25`:

- **Pipeline C** — three LLMs score every keyword definition; ensemble majority decides show / hide / regenerate / delete
- **Pipeline D** — same pattern for textbook abbreviations, with an extra check that expansions are correct

Judges: Mistral Small (API), OpenAI GPT-4o-mini (API), Claude (via Claude Code CSV batches). Results live in Supabase. Production CSVs feed back into the popup pipeline’s `filter_to_v5` / merge / upload path.

**The chain:**

```
keywords_new.jsonl (from Pipeline A)
  → setup → score mistral/openai → export → Claude batches → merge → import
  → ensemble → report → prepare_production → final_keywords.csv

keywords_abbrevs_enriched.jsonl (from Pipeline B)
  → acronym setup → score → Claude → ensemble → report
```

---

## What You'll Need Before Running

- Python 3.10+
- Mistral + OpenAI API keys
- Claude Code (or another way to run the third judge on CSV batches)
- Supabase project
- Input JSONL from the content-generation pipeline

---

## Prompt

Build a CLI app called `keyword-qa` that runs multi-model quality review on textbook keyword and acronym definition files. This is a packaging of an existing working pipeline (oncology textbook). Generalize prompts via a config file so any subject can swap domain name, category list, and examples.

### Subcommands

```
keyword-qa setup              # Stage 10 / 21: create table + load JSONL
keyword-qa score              # Stage 11 / 22: --model mistral|openai
keyword-qa export-claude      # Stage 12: write CSV for Claude
keyword-qa split-claude       # Stage 13: split into batches + write prompt
keyword-qa merge-claude       # Stage 14: merge scored batches
keyword-qa import-claude      # Stage 15: upload Claude scores
keyword-qa ensemble           # Stage 16 / 24: majority action tags
keyword-qa report             # Stage 17 / 24: CSV + summary
keyword-qa prepare-production # Stage 18: production table + export CSVs
keyword-qa status             # progress
```

Support a `--track keywords|acronyms` flag (default keywords) that switches table name, prompt file, and results directory.

### Tag system (required)

Exactly five tags: `approved`, `supplementary`, `too_basic`, `fix_definition`, `junk`.  
Ensemble `action` = majority of three tags; all different → `REVIEW`.  
`flag = true` unless action ∈ {approved, supplementary}.  
Score consensus uses threshold 70: ALL_PASS / ALL_FAIL / DISAGREE.

### Reference implementations

Adapt, don’t invent from scratch:

- `10_keyword_setup/ensemble_pipeline_v2.py`
- `13_claude_split/split_for_claude_v2.py`
- `14_claude_merge/merge_claude_scores_v2.py`
- `18_production_export/prepare_production.py`
- `21_acronym_setup/acronym_pipeline.py`
- Prompts in `13_claude_split/claude_scoring_prompt.md` and `23_acronym_claude/claude_acronym_prompt.md`

### README requirements

Document prerequisites, the relationship to stages `00`–`07`, the five-tag table, resumability of `score`, and the production handoff files (`final_keywords.csv`, `fix_definition.csv`). Include a `--limit` smoke-test path using `sample_data/`.
