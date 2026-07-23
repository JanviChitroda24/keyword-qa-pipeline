# Keyword QA Pipeline

Takes the keyword and abbreviation definitions produced by the **Keyword Popup Pipeline** (stages `00`–`07`) and runs a three-model quality gate over them: Mistral, OpenAI, and Claude each score and tag every entry; an ensemble step computes consensus; production exports hand the approved set back to the popup upload path.

This is **Pipeline C** (keyword QA) and **Pipeline D** (acronym QA). It starts at stage `10_` so the numbering continues cleanly after your colleague’s `00_`–`07_` content-generation stages.

- **Pipeline C (`10_`–`20_`)** — verify the bulk Wikipedia/LLM keyword set (~10K terms in the oncology build)
- **Pipeline D (`21_`–`25_`)** — verify the textbook abbreviation set (~927 terms in the oncology build) that Pipeline B produced

Both pipelines share the same five-tag system, the same Supabase scoring pattern, and the same “API models first, Claude Code second, then ensemble” workflow. The difference is the input file, the Supabase table, and a slightly tighter prompt for acronyms (expansion correctness matters).

---

## Folder Layout

```
keyword-qa-pipeline/
├── .env.example                      ← copy to .env and fill in keys
├── requirements.txt                  ← stdlib only (Python 3.10+)
├── README.md                         ← you are here
├── DESIGN.md                         ← what / why / how (read this to rebuild)
├── KEYWORD_QA_PIPELINE_DOCS.md       ← full deep documentation
├── RESULTS.md                        ← final oncology keyword + acronym counts
├── CLAUDE_CODE_PROMPT.md             ← optional rebuild-as-CLI prompt
│
├── 10_keyword_setup/                 Stage 10 — create table + load JSONL
│   └── ensemble_pipeline_v2.py         main Keyword QA CLI (all C commands)
├── 11_keyword_score_api/             Stage 11 — score with Mistral + OpenAI
│   └── run_pipeline.py                 thin wrapper → 10_ CLI
├── 12_claude_export/                 Stage 12 — export CSV for Claude Code
│   └── run_pipeline.py
├── 13_claude_split/                  Stage 13 — split into Claude batches
│   ├── split_for_claude_v2.py
│   └── claude_scoring_prompt.md
├── 14_claude_merge/                  Stage 14 — merge scored Claude batches
│   └── merge_claude_scores_v2.py
├── 15_claude_import/                 Stage 15 — upload Claude scores to Supabase
│   └── run_pipeline.py
├── 16_ensemble_consensus/            Stage 16 — 3-model consensus + action tags
│   └── run_pipeline.py
├── 17_report/                        Stage 17 — CSV + text report
│   └── run_pipeline.py
├── 18_production_export/             Stage 18 — production table + CSVs for merge
│   └── prepare_production.py
├── 19_definition_fix_loop/         Stage 19 — re-import fixed defs + re-score
│   ├── update_fixed_definitions.py
│   └── ensemble_pipeline_prod.py
├── 20_keyword_dashboard/             Stage 20 — HTML review UI
│   ├── keyword-qa-dashboard-v2.html
│   └── dashboard.html
│
├── 21_acronym_setup/                 Stage 21 — acronym table + load JSONL
│   └── acronym_pipeline.py             main Acronym QA CLI (all D commands)
├── 22_acronym_score_api/             Stage 22 — Mistral + OpenAI on acronyms
│   └── run_pipeline.py
├── 23_acronym_claude/                Stage 23 — Claude Code scoring prompt
│   └── claude_acronym_prompt.md
├── 24_acronym_ensemble_report/       Stage 24 — ensemble + report for acronyms
│   └── run_pipeline.py
├── 25_acronym_dashboard/             Stage 25 — acronym HTML review UI
│   └── acronym-qa-dashboard.html
│
├── reference/                        earlier v1 scripts + original step notes
└── sample_data/                      tiny JSONL samples for smoke tests
```

Stages that share one CLI use a thin `run_pipeline.py` wrapper so you can stay inside that stage folder. The real logic lives in `10_keyword_setup/ensemble_pipeline_v2.py` (keywords) and `21_acronym_setup/acronym_pipeline.py` (acronyms).

---

## How This Connects to the Keyword Popup Pipeline

```
Colleague stages 00–07 (content generation)
───────────────────────────────────────────
Wikipedia + textbook MDX
  → keywords_v3.jsonl / keywords_new.jsonl     ← Pipeline A usable output
  → keywords_abbrevs_enriched.jsonl            ← Pipeline B usable output
  → (optional) keywords_combined.jsonl         ← after merge

Your stages 10–25 (quality gate)
────────────────────────────────
keywords_new.jsonl
  → 10–17 Keyword QA → keyword_scores_v2
  → 18 production export → keyword_scores_production (8,161) / final_keywords.csv
  → 8,053 ready for textbook → feeds filter_to_v5 / merge / upload

keywords_abbrevs_enriched.jsonl
  → 21–24 Acronym QA → acronym_scores_v1 (927)
  → 915 ready for textbook → merge with keyword set (combined ≈ 8,968)
```

The colleague docs describe this layer as the **“optional multi-model quality review.”** This folder is that review, packaged the same way as stages `00`–`07`.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Python 3.10+ | All scripts are Python (stdlib `urllib` only — no `pip` packages required for the core CLIs) |
| Mistral API key | Stage 11 / 22 scoring |
| OpenAI API key | Stage 11 / 22 scoring (`gpt-4o-mini`) |
| Claude Code (or Claude API access via CLI) | Stages 13–15 / 23 — third judge |
| A Supabase project | Stores `keyword_scores_v2`, `keyword_scores_production`, `acronym_scores_v1` |
| Input JSONL from Pipeline A/B | `keywords_new.jsonl` (or `keywords_v3.jsonl`) and/or `keywords_abbrevs_enriched.jsonl` |

---

## Step-by-Step: Pipeline C — Keyword QA

### 0. Set up

```bash
cd keyword-qa-pipeline
cp .env.example .env
# edit .env: QA_SUPABASE_URL, QA_SUPABASE_KEY, MISTRAL_API_KEY, OPENAI_API_KEY
```

### 1. Stage 10 — create table + load keywords

```bash
cd 10_keyword_setup
python ensemble_pipeline_v2.py setup --input ../sample_data/sample_keywords.jsonl --limit 5   # smoke test
python ensemble_pipeline_v2.py setup --input /path/to/keywords_new.jsonl                     # full run
```

The script prints SQL for `keyword_scores_v2` on first run — paste it into Supabase SQL Editor, then re-run `setup` if needed.

**Output:** rows in `keyword_scores_v2` (oncology build: ~10,049–10,055).

### 2. Stage 11 — score with Mistral + OpenAI

```bash
cd ../11_keyword_score_api
python run_pipeline.py score --model mistral
python run_pipeline.py score --model openai
python run_pipeline.py status
```

Safe to re-run — already-scored rows are skipped.

### 3. Stages 12–15 — Claude Code path

```bash
cd ../12_claude_export
python run_pipeline.py export-for-claude
# → results_v2/keywords_for_claude.csv

cd ../13_claude_split
python split_for_claude_v2.py ../12_claude_export/results_v2/keywords_for_claude.csv
# (run from wherever the CSV landed; default export dir is results_v2/ next to the CLI cwd)
# → claude_batches_v2/batch_001.csv ... + claude_scoring_prompt.md

# Score each batch with Claude Code, then:

cd ../14_claude_merge
python merge_claude_scores_v2.py --input-dir ../13_claude_split/claude_batches_v2
# → claude_all_scored_v2.csv

cd ../15_claude_import
python run_pipeline.py import-claude --csv ../14_claude_merge/claude_all_scored_v2.csv
```

### 4. Stages 16–17 — ensemble + report

```bash
cd ../16_ensemble_consensus
python run_pipeline.py ensemble

cd ../17_report
python run_pipeline.py report
# → results_v2/comparison_report_v2.csv + summary_v2.txt
```

### 5. Stage 18 — production handoff

```bash
cd ../18_production_export
python prepare_production.py create-table   # print SQL, run in Supabase
python prepare_production.py populate
python prepare_production.py export
# → exports/approved_supplementary.csv
# → exports/fix_definition.csv
# (oncology build also produced final_keywords.csv ≈ 8,054 rows)
```

### 6. Stage 19 — optional fix-definition loop

When Pipeline A regenerates broken definitions:

```bash
cd ../19_definition_fix_loop
python update_fixed_definitions.py --input fix_definitions_filled.jsonl
python ensemble_pipeline_prod.py score --model mistral   # re-score only reset rows
python ensemble_pipeline_prod.py score --model openai
# … Claude path on the fix subset, then ensemble again
```

### 7. Stage 20 — dashboard review

Open `20_keyword_dashboard/keyword-qa-dashboard-v2.html` in a browser. Point it at your Supabase project (anon key + URL) to filter by tag, consensus, and flag.

---

## Step-by-Step: Pipeline D — Acronym QA

Same shape, smaller input (`keywords_abbrevs_enriched.jsonl`, ~927 rows), table `acronym_scores_v1`.

```bash
cd 21_acronym_setup
python acronym_pipeline.py setup --input /path/to/keywords_abbrevs_enriched.jsonl

cd ../22_acronym_score_api
python run_pipeline.py score --model mistral
python run_pipeline.py score --model openai

cd ../21_acronym_setup
python acronym_pipeline.py export-for-claude
# Score results_acronyms/acronyms_for_claude.csv with Claude Code
# using 23_acronym_claude/claude_acronym_prompt.md

python acronym_pipeline.py import-claude --csv results_acronyms/claude_acronym_scored.csv

cd ../24_acronym_ensemble_report
python run_pipeline.py ensemble
python run_pipeline.py status
python run_pipeline.py report
```

Open `25_acronym_dashboard/acronym-qa-dashboard.html` for review.

---

## Tag System (shared by C and D)

| Tag | Meaning | Popup action |
|-----|---------|--------------|
| `approved` | Core / directly relevant, accurate definition | Show |
| `supplementary` | Supporting science term students still need | Show |
| `too_basic` | Too elementary or off-topic for bachelor level | Hide |
| `fix_definition` | Term belongs, definition is broken/wrong/empty | Regenerate |
| `junk` | Not a real keyword (wiki category pages, noise) | Delete |

Ensemble `action` = majority tag (2 of 3). If all three tags differ → `REVIEW`.  
`flag = true` when action is not `approved` or `supplementary`.

---

## Oncology Build — Final Results

Full detail: **[`RESULTS.md`](./RESULTS.md)**. Summary:

### Keywords (`keyword_scores_production` — 8,161 rows)

| Status | Count | % |
|--------|------:|--:|
| Approved | 3,758 | 46.0% |
| Supplementary | 3,101 | 38.0% |
| Too Basic | 1,194 | 14.6% |
| REVIEW | 68 | 0.8% |
| Junk | 30 | 0.4% |
| Fix Definition | 10 | 0.1% |

**Ready for textbook: 8,053** (approved + supplementary + too_basic — professor asked to keep too_basic).

Audit table `keyword_scores_v2` (10,049 rows) was left untouched. Production dropped v2’s 1,302 junk entries and resolved most of the 586 REVIEW items.

### Acronyms (`acronym_scores_v1` — 927 rows)

| Status | Count | % |
|--------|------:|--:|
| Approved | 775 | 83.6% |
| Supplementary | 140 | 15.1% |
| REVIEW | 7 | 0.8% |
| Fix Definition | 5 | 0.5% |

**Ready for textbook: 915** (approved + supplementary).

Open tails: fix defs `cd39, nca, pi3, dtp, hdi` · REVIEW `atp, cns, adp, nf, rainbow, ve, tets`.

### Combined

| Category | Count |
|----------|------:|
| **Ready for textbook** | **8,968** |
| Needs human review | 75 |
| Needs definition fix | 15 |
| Junk to delete | 30 |

≈ **98.6%** keywords and **98.7%** acronyms verified and ready.

---

## Verification

- Run Stage 10 with `sample_data/sample_keywords.jsonl --limit 5` before a full load
- Run Stage 21 with `sample_data/sample_acronyms.jsonl` before a full acronym load
- `python -m py_compile` on every `.py` file in this folder — all stage scripts are self-contained Python 3
- `--dry-run` on `import-claude` and `update_fixed_definitions.py` / `prepare_production` where supported

**Not free:** real Mistral/OpenAI scoring and Claude Code sessions cost money/time. Always smoke-test with `--limit` first.

---

## Read Next

- **`DESIGN.md`** — decision design: what / why / how (start here if rebuilding for a new textbook)
- **`RESULTS.md`** — final oncology keyword + acronym counts and open tails
- **`KEYWORD_QA_PIPELINE_DOCS.md`** — full per-stage documentation, schemas, consensus rules, handoff checklist
- **`CLAUDE_CODE_PROMPT.md`** — prompt to rebuild this as a single CLI (mirrors the colleague’s rebuild prompt)
- **`reference/`** — v1 ensemble (Gemini/Mistral/Llama), original step notes, older dashboards
