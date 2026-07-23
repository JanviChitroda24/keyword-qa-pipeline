# Stage 21 — Acronym Setup

**Pipeline:** D (Acronym QA)  
**Script:** `acronym_pipeline.py`  
**Supabase table:** `acronym_scores_v1`

## Purpose

Load Pipeline B’s enriched abbreviation JSONL into a dedicated scoring table. This is the **additional feature** track alongside keyword QA: same ensemble pattern, acronym-specific prompt (expansion correctness).

## Inputs

- `keywords_abbrevs_enriched.jsonl` from Keyword Popup Pipeline stage `05`  
- Or `../sample_data/sample_acronyms.jsonl` for a smoke test

## Commands

```bash
cd 21_acronym_setup
python acronym_pipeline.py setup --input ../sample_data/sample_acronyms.jsonl
python acronym_pipeline.py setup --input /path/to/keywords_abbrevs_enriched.jsonl
python acronym_pipeline.py status
```

Run the printed `CREATE TABLE` SQL in Supabase on first use (include anon read policy for Stage 25).

## Outputs

- Rows in `acronym_scores_v1` (oncology: **927**)  
- Next: **Stage 22**

## Notes

This CLI also owns later acronym commands (`score`, `export-for-claude`, `import-claude`, `ensemble`, `report`). Stages 22 and 24 wrap it with `run_pipeline.py`. A copy of `claude_acronym_prompt.md` lives here for convenience; the canonical prompt for Claude Code is also in `23_acronym_claude/`.
