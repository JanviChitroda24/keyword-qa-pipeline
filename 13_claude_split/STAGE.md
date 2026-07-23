# Stage 13 — Split Claude Batches

**Pipeline:** C (Keyword QA)  
**Scripts:** `split_for_claude_v2.py`, `claude_scoring_prompt.md`

## Purpose

~10K rows is too large for one reliable Claude Code session. This stage splits the export CSV into fixed-size batches and writes the scoring prompt Claude must follow.

## Commands

```bash
cd 13_claude_split
python split_for_claude_v2.py /path/to/keywords_for_claude.csv
python split_for_claude_v2.py /path/to/keywords_for_claude.csv --batch-size 300
```

Default batch size: **500**.

## Outputs

```
claude_batches_v2/
  batch_001.csv
  batch_002.csv
  ...
  claude_scoring_prompt.md
```

## Scoring each batch

```bash
claude -p "Read claude_batches_v2/claude_scoring_prompt.md for instructions. \
Score the keywords in claude_batches_v2/batch_001.csv \
Save output as claude_batches_v2/batch_001_scored.csv"
```

Required scored columns: `slug,claude_score,claude_tag,claude_issue`.

## Next

**Stage 14** (`14_claude_merge/`) after all `batch_*_scored.csv` files exist.
