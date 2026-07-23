# Stage 16 — Ensemble Consensus

**Pipeline:** C (Keyword QA)  
**Script:** `run_pipeline.py` → `ensemble`

## Purpose

Combine three judges into one shipping decision per keyword.

## Rules

1. **`avg_score`** — mean of scores ≥ 0  
2. **`consensus`** — `ALL_PASS` / `ALL_FAIL` / `DISAGREE` / `NO_DATA` using threshold 70  
3. **`tag_consensus`** — `AGREE` (3/3) / `MAJORITY` (2/3) / `DISAGREE` (all different)  
4. **`action`** — majority tag; if all three tags differ → `REVIEW`  
5. **`flag`** — `true` unless `action` ∈ {`approved`, `supplementary`}

## Commands

```bash
cd 16_ensemble_consensus
python run_pipeline.py ensemble
python run_pipeline.py status
```

## Outputs

- Ensemble columns written on every row  
- Next: **Stage 17** (`17_report/`)

## Oncology reference (V2 audit — 10,049 rows)

From the Stage 17 summary on `keyword_scores_v2` (kept as audit; do not modify):

| Action | Count | % |
|--------|------:|--:|
| approved | 3,727 | 37.1% |
| supplementary | 2,994 | 29.8% |
| junk | 1,302 | 13.0% |
| too_basic | 1,102 | 11.0% |
| REVIEW | 586 | 5.8% |
| fix_definition | 338 | 3.4% |

**Final shipping numbers** live on `keyword_scores_production` after Stage 18 — see [`RESULTS.md`](../RESULTS.md) (8,161 production rows → **8,053** ready for textbook).
