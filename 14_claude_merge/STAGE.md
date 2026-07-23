# Stage 14 — Merge Claude Scores

**Pipeline:** C (Keyword QA)  
**Script:** `merge_claude_scores_v2.py`

## Purpose

Combine every `batch_*_scored.csv` into one file for Supabase import. Remaps common Claude column aliases and deduplicates by `slug`.

## Commands

```bash
cd 14_claude_merge
python merge_claude_scores_v2.py --input-dir ../13_claude_split/claude_batches_v2
python merge_claude_scores_v2.py --input-dir ../13_claude_split/claude_batches_v2 --output claude_all_scored_v2.csv
```

## Outputs

- `claude_all_scored_v2.csv` (`slug,claude_score,claude_tag,claude_issue`)  
- Printed score stats (avg / min / max / below 70)  
- Next: **Stage 15** (`15_claude_import/`)

## Notes

If a batch used `score` / `issue_tag` / `issue_detail` instead of the `claude_*` names, the merger remaps them automatically.
