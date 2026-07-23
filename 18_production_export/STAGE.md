# Stage 18 — Production Export

**Pipeline:** C (Keyword QA)  
**Script:** `prepare_production.py`  
**Tables:** `keyword_scores_v2` → `keyword_scores_production`

## Purpose

Copy operational rows into a production scoring table and export CSVs for the Keyword Popup Pipeline owner (merge / `filter_to_v5` / upload).

## Commands

```bash
cd 18_production_export
python prepare_production.py create-table    # print SQL → run in Supabase
python prepare_production.py populate        # copy from v2
python prepare_production.py populate --force
python prepare_production.py export          # write CSVs under exports/
python prepare_production.py all             # print full setup instructions
```

## What gets copied

Rows whose `action` is one of: `approved`, `supplementary`, `fix_definition`, `too_basic`.

## Exports

| File | Who uses it |
|------|-------------|
| `exports/approved_supplementary.csv` | Integrate / filter into textbook popup set |
| `exports/fix_definition.csv` | Pipeline A regenerates definitions |
| `exports/final_keywords.csv` | Oncology shipping list for `filter_to_v5.py` |

## Oncology production results (final)

**Table:** `keyword_scores_production` — **8,161** rows  
(`keyword_scores_v2` = 10,049 audit rows, untouched.)

| Status | Count | % |
|--------|------:|--:|
| Approved | 3,758 | 46.0% |
| Supplementary | 3,101 | 38.0% |
| Too Basic | 1,194 | 14.6% |
| REVIEW | 68 | 0.8% |
| Junk | 30 | 0.4% |
| Fix Definition | 10 | 0.1% |

**Ready for textbook: 8,053** (approved + supplementary + too_basic).  
`too_basic` was kept because the professor asked to include elementary terms.

v2 → production: dropped 1,302 junk; resolved most of 586 REVIEW (68 remain).

Full combined totals (keywords + acronyms): [`RESULTS.md`](../RESULTS.md).

## Next

- If fix_definition rows return regenerated text → **Stage 19**  
- For interactive review → **Stage 20**  
- Otherwise → colleague stages `06_merge` / `07_upload`
