# Stage 15 — Import Claude Scores

**Pipeline:** C (Keyword QA)  
**Script:** `run_pipeline.py` → `import-claude`

## Purpose

Write Claude’s scores/tags/issues onto matching `slug` rows in `keyword_scores_v2`.

## Commands

```bash
cd 15_claude_import
python run_pipeline.py import-claude --csv ../14_claude_merge/claude_all_scored_v2.csv --dry-run
python run_pipeline.py import-claude --csv ../14_claude_merge/claude_all_scored_v2.csv
```

## Outputs

- `claude_score`, `claude_tag`, `claude_issue` populated  
- Next: **Stage 16** (`16_ensemble_consensus/`)

## Notes

Always dry-run first on a large import. Upsert is safe to re-run.
