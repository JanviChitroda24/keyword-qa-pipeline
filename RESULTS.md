# Oncology Build — Final QA Results

Final counts from the cancer biology textbook keyword/acronym QA run.  
Source of truth: Supabase tables listed below (session summary after production handoff).

---

## Keywords (`keyword_scores_production`)

**Total in production:** 8,161 rows

| Status | Count | % | Meaning |
|--------|------:|--:|---------|
| Approved | 3,758 | 46.0% | Directly cancer/biotech relevant — show popup |
| Supplementary | 3,101 | 38.0% | Supporting science terms — show popup |
| Too Basic | 1,194 | 14.6% | Elementary terms — **included** (professor requested) |
| REVIEW | 68 | 0.8% | Models could not agree — needs human review |
| Junk | 30 | 0.4% | Wikipedia artifacts/biographies — delete |
| Fix Definition | 10 | 0.1% | Still need definition regeneration |

**Ready for textbook:** **8,053** (approved + supplementary + too_basic)

### Audit table (do not modify)

| Table | Rows | Notes |
|-------|-----:|-------|
| `keyword_scores_v2` | 10,049 | Full audit run — kept untouched |
| `keyword_scores_production` | 8,161 | Filtered production set |

How v2 → production was filtered:

- Dropped **1,302 junk** entries identified in v2  
- Resolved most of the **586 REVIEW** items during the v2→production transition (68 REVIEW remain in production)  
- `too_basic` was **kept** for the textbook after professor feedback (not hidden)

---

## Acronyms (`acronym_scores_v1`)

**Total scored:** 927

| Status | Count | % |
|--------|------:|--:|
| Approved | 775 | 83.6% |
| Supplementary | 140 | 15.1% |
| REVIEW | 7 | 0.8% |
| Fix Definition | 5 | 0.5% |

**Ready for textbook:** **915** (approved + supplementary)

### Open acronym tails

**Fix definition (5)** — corrected definitions identified but not yet updated/re-scored:

`cd39`, `nca`, `pi3`, `dtp`, `hdi`

**REVIEW (7)** — needs human decision:

`atp`, `cns`, `adp`, `nf`, `rainbow`, `ve`, `tets`

---

## Combined Totals

| Category | Count |
|----------|------:|
| **Ready for textbook** | **8,968** (8,053 keywords + 915 acronyms) |
| Needs human review | 75 (68 keywords + 7 acronyms) |
| Needs definition fix | 15 (10 keywords + 5 acronyms) |
| Junk to delete | 30 keywords |

**Coverage:** ~**98.6%** of production keywords and ~**98.7%** of acronyms verified and ready, with a small tail of reviews and fixes still open.

---

## Supabase Tables

| Table | Rows | Purpose |
|-------|-----:|---------|
| `keyword_scores_v2` | 10,049 | Audit table — do not modify |
| `keyword_scores_production` | 8,161 | Production keywords |
| `acronym_scores_v1` | 927 | Acronym verification |

---

## Related artifacts

- V2 ensemble summary snapshot: `sample_data/summary_v2_example.txt` (pre-production audit breakdown)  
- Handoff CSVs from Stage 18: `exports/final_keywords.csv`, `approved_supplementary*.csv`, `fix_definition.csv`
