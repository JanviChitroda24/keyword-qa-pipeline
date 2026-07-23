# Stage 17 — Report

**Pipeline:** C (Keyword QA)  
**Script:** `run_pipeline.py` → `report`

## Purpose

Export a full comparison CSV and a human-readable summary after ensemble.

## Commands

```bash
cd 17_report
python run_pipeline.py report
```

## Outputs

| File | Contents |
|------|----------|
| `results_v2/comparison_report_v2.csv` | Per-row scores, tags, consensus, action, flag |
| `results_v2/summary_v2.txt` | Totals, histograms, sample tag disagreements |

A real oncology summary snapshot is in `../sample_data/summary_v2_example.txt`.

## Next

**Stage 18** (`18_production_export/`) to build handoff CSVs for the popup pipeline.
