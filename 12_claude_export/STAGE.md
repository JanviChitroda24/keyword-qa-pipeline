# Stage 12 — Export Keywords for Claude

**Pipeline:** C (Keyword QA)  
**Script:** `run_pipeline.py` → `export-for-claude`

## Purpose

Dump every keyword row into a CSV Claude Code can score offline. Claude is the third judge (alongside Mistral and OpenAI).

## Commands

```bash
cd 12_claude_export
python run_pipeline.py export-for-claude
```

## Outputs

- `results_v2/keywords_for_claude.csv` with columns `slug,term,category,definition`  
- Next: **Stage 13** (`13_claude_split/`)

## Notes

Working directory matters: the CLI writes `results_v2/` relative to the current working directory. Either run from this folder and pass the CSV path into Stage 13, or run the export from `10_keyword_setup/` and point Stage 13 at that path.
