# Stage 10 — Keyword Setup

**Pipeline:** C (Keyword QA)  
**Script:** `ensemble_pipeline_v2.py`  
**Supabase table:** `keyword_scores_v2`

## Purpose

Create the scoring table and load Pipeline A’s keyword JSONL so every later stage can read/write scores by `slug`.

## Inputs

- `keywords_new.jsonl` or `keywords_v3.jsonl` from the Keyword Popup Pipeline  
- Or `../sample_data/sample_keywords.jsonl` for a 5-row smoke test

## Commands

```bash
cd 10_keyword_setup
python ensemble_pipeline_v2.py setup --input ../sample_data/sample_keywords.jsonl --limit 5
python ensemble_pipeline_v2.py setup --input /path/to/keywords_new.jsonl
python ensemble_pipeline_v2.py setup --input /path/to/keywords_new.jsonl --force
python ensemble_pipeline_v2.py status
```

On first run, copy the printed `CREATE TABLE` SQL into Supabase → SQL Editor (include the anon read policy for the dashboard).

## Field mapping

| JSONL | Column |
|-------|--------|
| `keyword` | `term` |
| slugified keyword | `slug` |
| `category` | `category` |
| `definition_short` | `definition` |

Unscored model columns start at `-1`.

## Outputs

- Rows in `keyword_scores_v2` (oncology: ~10,049–10,055)
- Next: **Stage 11** (`11_keyword_score_api/`)

## Notes

- This file is also the **main CLI** for stages 11–17 (`score`, `export-for-claude`, `import-claude`, `ensemble`, `report`, `status`). Other stage folders wrap it with `run_pipeline.py`.
- Requires `.env` with `QA_SUPABASE_URL` + `QA_SUPABASE_KEY` (service role).
