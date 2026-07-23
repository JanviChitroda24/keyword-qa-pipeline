# Stage 19 — Definition Fix Loop

**Pipeline:** C (Keyword QA)  
**Scripts:** `update_fixed_definitions.py`, `ensemble_pipeline_prod.py`  
**Table:** `keyword_scores_production`

## Purpose

After Pipeline A regenerates definitions for `fix_definition` rows, load the new text, reset scores, and re-run the three-model gate on the production table only.

## Step A — load fixed definitions

```bash
cd 19_definition_fix_loop
python update_fixed_definitions.py --input fix_definitions_filled.jsonl --dry-run
python update_fixed_definitions.py --input fix_definitions_filled.jsonl
```

Updates `definition` and sets all model scores back to `-1` for those slugs.

## Step B — re-score with prod CLI

`ensemble_pipeline_prod.py` is the same workflow as v2, pointed at `keyword_scores_production` and `results_prod/`.

```bash
python ensemble_pipeline_prod.py score --model mistral
python ensemble_pipeline_prod.py score --model openai
python ensemble_pipeline_prod.py export-for-claude
# … Claude score the fix subset …
python ensemble_pipeline_prod.py import-claude --csv ...
python ensemble_pipeline_prod.py ensemble
python ensemble_pipeline_prod.py report
```

## Next

Re-run `../18_production_export/prepare_production.py export` when the fixed rows pass.
