# Inter-Rater Agreement Metrics (`agreement_metrics.py`)

Lives in **`keyword-qa-pipeline`** (Pipeline C/D QA), not the popup content-generation repo.

## What this script does

Measures how consistently **three LLM reviewers** (Mistral, OpenAI, Claude) tag keyword definitions during Medhavi QA.

It reports:

| Metric | Meaning |
|--------|---------|
| **Fleiss' κ** (+ 95% CI) | Chance-corrected agreement across all 3 raters |
| **Pairwise Cohen's κ** | Agreement for each model pair |
| **Per-category agreement** | Stability of tags like `approved`, `junk`, … |
| **2/1 split distribution** | When two agree and one dissents, what were the tags? |
| **Per-model tag rates** | Whether one model is systematically stricter/looser |
| **κ by subject category** | Agreement within Oncology, Immunology, etc. |

## Why it exists

Raw “% agree” overstates reliability when most items are `approved`. Kappa corrects for chance. Use this after ensemble / before shipping, for papers/reports, and to decide which disagreements need human review.

## How it works (high level)

1. **Load** rows from Supabase, CSV, or JSONL.
2. **Filter** to items where all three models have a valid tag (`approved`, `supplementary`, `too_basic`, `false_definition`, `junk`).
3. **Build a ratings matrix** — for each keyword, count how many raters chose each tag (e.g. `{approved: 2, supplementary: 1}`).
4. **Compute** Fleiss / Cohen and **write a Markdown report** (default: `Final_Result/agreement_report.md`).
5. If the file only has `_review_consensus` / `_review_action` (no per-model tags), run a **limited** consensus report instead.

No extra pip packages are required (stdlib only). Supabase mode uses `urllib`.

---

## Execution steps

### 0. Go to the QA pipeline folder

```bash
cd "/Users/janvichitroda/Documents/Janvi/NEU/Humanitarin AI/popup_doc/keyword-qa-pipeline"
```

(Or `cd popup_doc/keyword-qa-pipeline` from the workspace root.)

### 1. Sanity-check the math (no data needed)

```bash
python3 agreement_metrics.py --demo
```

Writes `Final_Result/agreement_report.md`. Expect Fleiss κ roughly moderate–substantial for the synthetic 80%-accurate raters.

### 2. Run on shipping JSONL (`Final_Result/`)

`Final_Result/keywords_combined.jsonl` has `_review_action` and `_review_consensus`, but **not** `mistral_tag` / `openai_tag` / `claude_tag`. You get the **limited** report:

```bash
python3 agreement_metrics.py --jsonl Final_Result/keywords_combined.jsonl
```

Terminal shows only:

```text
Loaded 8976 rows from ...
Wrote report → Final_Result/agreement_report.md
```

Custom output path:

```bash
python3 agreement_metrics.py --jsonl Final_Result/keywords_combined.jsonl --out Final_Result/agreement_report_limited.md
```

### 3. Full kappa from CSV (recommended offline path)

Export the audit table (`keyword_scores_v2`) so each row has:

- `mistral_tag`, `openai_tag`, `claude_tag`
- ideally `category` (and `slug` if present)

Then:

```bash
python3 agreement_metrics.py --csv /path/to/keyword_scores_v2_export.csv
# optional:
python3 agreement_metrics.py --csv /path/to/keyword_scores_v2_export.csv --out Final_Result/agreement_full.md
```

### 4. Full kappa from Supabase

Same env vars as the rest of this QA repo (see `.env.example`):

```bash
# if not already in .env:
export QA_SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
export QA_SUPABASE_KEY="YOUR_SERVICE_ROLE_KEY"

python3 agreement_metrics.py --supabase
# or a specific table name:
python3 agreement_metrics.py --supabase keyword_scores_v2 --out Final_Result/agreement_supabase.md
```

---

## Output

| Flag | Behavior |
|------|----------|
| *(default)* | Writes `Final_Result/agreement_report.md` |
| `--out path.md` | Writes that path instead |

Stdout only confirms load + write path. Open the `.md` file for tables and metrics.

---

## Which mode should I use?

| Input | Command | What you get |
|-------|---------|--------------|
| Nothing / verify formulas | `--demo` | Full report on synthetic data |
| `Final_Result/keywords_combined.jsonl` | `--jsonl …` | Consensus + action only (no Fleiss/Cohen) |
| CSV with per-model tags | `--csv …` | Full Fleiss / Cohen / splits |
| Live audit table | `--supabase` | Same as CSV, pulled from DB |

---

## Interpreting Fleiss / Cohen κ (Landis & Koch)

| κ range | Label |
|---------|--------|
| ≥ 0.81 | almost perfect |
| 0.61–0.80 | substantial |
| 0.41–0.60 | moderate |
| 0.21–0.40 | fair |
| 0.00–0.20 | slight |
| < 0 | poor (below chance) |

Also look at:

- **P(observed)** — raw agreement before chance correction  
- **2/1 splits** — e.g. many `approved` vs `supplementary` is milder than `approved` vs `junk`  
- **Dissenter frequency** — which model is the minority most often  

---

## Required columns

### Full analysis (`--supabase`, `--csv`, or JSONL with tags)

| Column | Role |
|--------|------|
| `mistral_tag` | Mistral’s tag |
| `openai_tag` | OpenAI’s tag |
| `claude_tag` | Claude’s tag |
| `category` | Subject category (for section 6) |

Valid tag values: `approved`, `supplementary`, `too_basic`, `false_definition`, `junk`.

### Limited analysis (`--jsonl` shipping file)

| Column | Role |
|--------|------|
| `_review_consensus` | e.g. `AGREE`, `MAJORITY` |
| `_review_action` | e.g. `approved`, … |
| `category` | Subject category |

---

## File location

```
popup_doc/keyword-qa-pipeline/
├── agreement_metrics.py              ← run this
├── AGREEMENT_METRICS.md              ← this guide
└── Final_Result/
    ├── keywords_combined.jsonl       ← typical --jsonl input
    └── agreement_report.md           ← generated report (default --out)
```

Inline comments in `agreement_metrics.py` use **WHAT / WHY / HOW** on each major function for code-level documentation.
