# Stage 24 — Acronym Ensemble + Report

**Pipeline:** D (Acronym QA)  
**Script:** `run_pipeline.py` → `../21_acronym_setup/acronym_pipeline.py`

## Purpose

Same consensus math as keyword Stage 16/17, on `acronym_scores_v1`.

## Commands

```bash
cd 24_acronym_ensemble_report
python run_pipeline.py ensemble
python run_pipeline.py status
python run_pipeline.py report
```

## Outputs

- `action`, `flag`, `tag_consensus`, `avg_score`, `consensus` on every acronym  
- Report files under `results_acronyms/`  
- Next: **Stage 25** for UI review; then feed approved/supplementary acronyms into popup merge (`06_merge`)

## Shipping rule of thumb

| Action | Merge into popups? |
|--------|--------------------|
| approved | Yes |
| supplementary | Yes |
| fix_definition | No until fixed |
| too_basic | No (for acronyms — unlike keywords, too_basic acronyms were not kept) |
| junk | No |
| REVIEW | Human decision |

## Oncology results (final)

**Table:** `acronym_scores_v1` — **927** rows

| Status | Count | % |
|--------|------:|--:|
| Approved | 775 | 83.6% |
| Supplementary | 140 | 15.1% |
| REVIEW | 7 | 0.8% |
| Fix Definition | 5 | 0.5% |

**Ready for textbook: 915** (approved + supplementary).

Open tails:

- Fix definition: `cd39`, `nca`, `pi3`, `dtp`, `hdi`  
- REVIEW: `atp`, `cns`, `adp`, `nf`, `rainbow`, `ve`, `tets`

See [`RESULTS.md`](../RESULTS.md) for combined keyword + acronym totals (**8,968** ready).
