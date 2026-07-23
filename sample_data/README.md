# Sample Data

Tiny inputs for smoke-testing without burning API credits on the full oncology set.

| File | Use |
|------|-----|
| `sample_keywords.jsonl` | Stage 10 — 5 keywords covering approved / too_basic / fix_definition / junk shapes |
| `sample_acronyms.jsonl` | Stage 21 — 3 acronyms (CSC, FDA, MRI) |
| `summary_v2_example.txt` | Snapshot of Stage 17 oncology **audit** summary on `keyword_scores_v2` (10,049 rows) |
| [`../RESULTS.md`](../RESULTS.md) | **Final** production + acronym counts (8,161 / 927 → 8,968 ready) |

## Smoke-test commands

```bash
cd 10_keyword_setup
python ensemble_pipeline_v2.py setup --input ../sample_data/sample_keywords.jsonl --limit 5

cd ../21_acronym_setup
python acronym_pipeline.py setup --input ../sample_data/sample_acronyms.jsonl
```

Do not commit real `.env` keys. Full result CSVs and `debug_responses/` folders are gitignored — regenerate them by running the stages.
