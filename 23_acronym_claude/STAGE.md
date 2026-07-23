# Stage 23 — Acronym Claude Scoring

**Pipeline:** D (Acronym QA)  
**Prompt:** `claude_acronym_prompt.md`  
**Export/import:** via `../21_acronym_setup/acronym_pipeline.py`

## Purpose

Third-judge pass for abbreviations. Unlike keywords, **927 rows fit in one Claude Code session** — no mandatory split step.

## Commands

```bash
cd ../21_acronym_setup
python acronym_pipeline.py export-for-claude
# → results_acronyms/acronyms_for_claude.csv
```

In Claude Code:

```
Read 23_acronym_claude/claude_acronym_prompt.md for the scoring instructions.
Score ALL acronyms in results_acronyms/acronyms_for_claude.csv
and save output as results_acronyms/claude_acronym_scored.csv
```

Then:

```bash
python acronym_pipeline.py import-claude --csv results_acronyms/claude_acronym_scored.csv
```

## What the prompt checks

1. **Expansion** — correct full name for this textbook context  
2. **Definition** — factually accurate  
3. **Relevance** — student reading cancer biology would benefit (broad, not cancer-only)

## Outputs

- Claude columns on `acronym_scores_v1`  
- Next: **Stage 24**
