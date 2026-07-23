# Keyword QA Pipeline — Full Documentation

## What This Builds

A **multi-model quality gate** for textbook keyword popups. After the Keyword Popup Pipeline (stages `00`–`07`) writes definitions from Wikipedia and from textbook abbreviations, this pipeline decides — for every entry — whether students should see it, hide it, delete it, or send it back for a regenerated definition.

There are two parallel tracks:

- **Pipeline C — Keyword QA** (`10_`–`20_`) — scores the bulk keyword set from Pipeline A (Wikipedia → LLM rewrite). Oncology build: **10,049** audit rows in `keyword_scores_v2` → **8,161** in `keyword_scores_production` → **8,053** ready for textbook.
- **Pipeline D — Acronym QA** (`21_`–`25_`) — scores the abbreviation set from Pipeline B (MDX scan → LLM enrich). Oncology build: **927** acronyms → **915** ready for textbook.

Combined ready set: **8,968** popups. See **[RESULTS.md](./RESULTS.md)** for the full breakdown and open tails.

Both tracks use the **same five tags**, the **same three judges** (Mistral Small API, OpenAI GPT-4o-mini API, Claude via Claude Code), and the **same ensemble rules**. Pipeline D’s prompt adds an explicit check that the acronym’s **expansion** is correct (e.g. `AI` as Aromatase Inhibitor vs Artificial Intelligence).

**Why a separate QA pipeline exists:** a single LLM rewrite (Pipeline A stage 3) is necessary but not sufficient for a published textbook. Different models disagree on edge cases — too-basic science terms, disambiguation leftovers, Wikipedia category-page junk, supporting vs core relevance. Three independent votes plus a majority `action` tag is the gate that produced the oncology project’s shipping keyword list.

If you are starting from zero, read this document top to bottom once before running anything. Stages are resumable: if stage 14 crashes, stages 10–13 do not need to be redone.

**Building or adapting this for a new textbook?** Read [`DESIGN.md`](./DESIGN.md) first — it explains *why* the system is shaped this way (three models, five tags, audit vs production, separate acronym track) so you can change the right knobs without undoing the intent.

---

## What You Need Before Starting

| Requirement | Why | Where to get it |
|---|---|---|
| Python 3.10+ | All scripts are Python (stdlib only) | python.org |
| Mistral API key | Stage 11 / 22 scoring (`mistral-small-latest`) | console.mistral.ai |
| OpenAI API key | Stage 11 / 22 scoring (`gpt-4o-mini`) | platform.openai.com |
| Claude Code CLI (or equivalent) | Third judge for stages 13–15 / 23 | Claude Code / Anthropic |
| Supabase project | Stores scoring tables | supabase.com — free tier is enough |
| Pipeline A output JSONL | Input for Pipeline C | `keywords_new.jsonl` or `keywords_v3.jsonl` from stages `00`–`07` |
| Pipeline B output JSONL | Input for Pipeline D | `keywords_abbrevs_enriched.jsonl` from stage `05` |

You do **not** need extra Python packages for the core CLIs — they use `urllib` only. Dashboards are static HTML that talk to Supabase from the browser (anon key + RLS read policy).

---

## Complete Chain (accurate, real script names)

Numbering continues from the Keyword Popup Pipeline (`00`–`07`).

```
Keyword Popup Pipeline (colleague) — content generation
───────────────────────────────────────────────────────
enwiki + textbook MDX
  → … stages 00–03 … → keywords_v3.jsonl / keywords_new.jsonl
  → … stages 04–05 … → keywords_abbrevs_enriched.jsonl
  → … stages 06–07 … → keywords_combined.jsonl → Supabase articles + keywords.json

Pipeline C — Keyword QA (this folder, stages 10–20)
───────────────────────────────────────────────────
keywords_new.jsonl
  └─► ensemble_pipeline_v2.py setup          Stage 10 — table + load
          └─► keyword_scores_v2
                  └─► score --model mistral   Stage 11a
                  └─► score --model openai    Stage 11b
                  └─► export-for-claude       Stage 12
                          └─► keywords_for_claude.csv
                                  └─► split_for_claude_v2.py   Stage 13
                                          └─► claude_batches_v2/batch_*.csv
                                                  └─► Claude Code scoring
                                                          └─► batch_*_scored.csv
                                                                  └─► merge_claude_scores_v2.py  Stage 14
                                                                          └─► claude_all_scored_v2.csv
                                                                                  └─► import-claude  Stage 15
                                                                                          └─► ensemble       Stage 16
                                                                                          └─► report         Stage 17
                                                                                                  └─► prepare_production.py  Stage 18
                                                                                                          └─► final_keywords.csv /
                                                                                                              approved_supplementary.csv /
                                                                                                              fix_definition.csv
                                                                                                  └─► (optional) fix loop Stage 19
                                                                                                  └─► HTML dashboard Stage 20

Pipeline D — Acronym QA (this folder, stages 21–25)
───────────────────────────────────────────────────
keywords_abbrevs_enriched.jsonl
  └─► acronym_pipeline.py setup              Stage 21
          └─► acronym_scores_v1
                  └─► score mistral/openai   Stage 22
                  └─► export + Claude Code   Stage 23
                  └─► import-claude
                  └─► ensemble + report      Stage 24
                  └─► HTML dashboard         Stage 25
```

**The short version:** run Pipeline C through `ensemble` + `report`, then `prepare_production.py export`. Hand `final_keywords.csv` (or the approved export) to whoever runs `filter_to_v5.py` / merge / upload. Run Pipeline D the same way on abbreviations whenever Pipeline B produces a new enriched file.

---

## Shared Concepts

### Five tags

Every model assigns **exactly one** tag per entry:

| Tag | Meaning | What happens to the popup |
|-----|---------|---------------------------|
| `approved` | Directly relevant to the textbook domain; definition accurate | **Show** |
| `supplementary` | Not core domain, but a supporting term students benefit from | **Show** |
| `too_basic` | Too elementary for bachelor level, or too irrelevant to justify a popup | **Hide** |
| `fix_definition` | Term belongs in the book, but definition is wrong, empty, truncated, or a disambiguation list | **Regenerate**, then re-score |
| `junk` | Not a real keyword — Wikipedia category pages, markup artifacts, books/films, nonsense | **Delete** |

Decision order baked into the prompt (keywords):

1. Junk / formatting artifact? → `junk`
2. Empty definition on a valid term? → `fix_definition`
3. Broken / wrong / disambiguation definition? → `fix_definition`
4. Too basic or irrelevant? → `too_basic`
5. Directly about domain topics? → `approved`
6. Valid supporting science? → `supplementary`

Acronym prompt adds: wrong expansion → `fix_definition` even if the prose sounds fine.

### Score rubric (0–100)

| Range | Meaning |
|------:|---------|
| 90–100 | Perfect entry |
| 70–89 | Good, minor quibbles |
| 50–69 | Borderline |
| 30–49 | Significant problems |
| 0–29 | Junk or completely broken |

Pass threshold used by score-consensus: **≥ 70**.

### Ensemble outputs (per row)

After Stage 16 / 24:

| Field | How it’s computed |
|-------|-------------------|
| `avg_score` | Mean of all model scores that are ≥ 0 |
| `consensus` | `ALL_PASS` (all ≥70) / `ALL_FAIL` (all <70) / `DISAGREE` (mixed) / `NO_DATA` |
| `tag_consensus` | `AGREE` (3/3 same tag) / `MAJORITY` (2/3) / `DISAGREE` (all different) / `NO_DATA` |
| `action` | Majority tag; if all three differ → `REVIEW` |
| `flag` | `true` when `action` is not in `{approved, supplementary}` |

Only `approved` and `supplementary` are intended to show as student popups.

### Models used

| Role | Model | How it’s called |
|------|-------|-----------------|
| Judge 1 | `mistral-small-latest` | HTTPS API from `ensemble_pipeline_v2.py` / `acronym_pipeline.py` |
| Judge 2 | `gpt-4o-mini` | HTTPS API from the same CLIs |
| Judge 3 | Claude (Claude Code) | Offline CSV batches; human/CLI runs the prompt; scores imported back |

Temperature is `0.1` for API judges. Default batch size is **10** keywords per API call (adjust with `--batch-size`). Rate-limit sleeps: Mistral ~2s, OpenAI ~1s between batches.

---

## Pipeline C — Keyword QA (Stages 10–20)

### Stage 10 — `10_keyword_setup/` — load keywords into Supabase

**Script:** `ensemble_pipeline_v2.py`  
**Table:** `keyword_scores_v2`

**What it does:**

1. Prints (or assumes) a `CREATE TABLE` for `keyword_scores_v2` with per-model score/tag/issue columns plus ensemble fields.
2. Reads a local JSONL or CSV of keywords.
3. Maps fields into the scoring table and upserts on `slug`.

**Field mapping from Pipeline A JSONL:**

| JSONL field | Table column | Notes |
|-------------|--------------|-------|
| `keyword` | `term` | Display name |
| (derived) | `slug` | Lowercase, hyphenated |
| `category` | `category` | As-is |
| `definition_short` | `definition` | Scored text (tooltip-length) |
| `relevant=false` / empty def | still loaded | Models tag these as junk / too_basic / fix_definition |

**Run it:**

```bash
cd 10_keyword_setup
python ensemble_pipeline_v2.py setup --input ../sample_data/sample_keywords.jsonl --limit 5
python ensemble_pipeline_v2.py setup --input /path/to/keywords_new.jsonl
python ensemble_pipeline_v2.py setup --input /path/to/keywords_new.jsonl --force   # upsert overwrite
```

**Oncology reference:** ~10,055 rows loaded; ~1,322 had empty definitions and were left for models to classify.

**RLS:** enable row-level security and allow `anon` SELECT so the Stage 20 dashboard can read scores with the anon key.

**Output:** populated `keyword_scores_v2`. Next: Stage 11.

---

### Stage 11 — `11_keyword_score_api/` — Mistral + OpenAI

**Script:** `run_pipeline.py` → `ensemble_pipeline_v2.py score`

**What it does:** Pulls rows that still have `mistral_score = -1` (or OpenAI equivalent), builds the shared review prompt, calls the API in batches, parses JSON array responses, writes `*_score`, `*_tag`, `*_issue` back to Supabase. Unparseable responses are saved under `results_v2/debug_responses/` for inspection.

**Run it:**

```bash
cd 11_keyword_score_api
python run_pipeline.py score --model mistral
python run_pipeline.py score --model openai
python run_pipeline.py score --model mistral --batch-size 5
python run_pipeline.py status
```

**Resumability:** re-running `score` only processes unscored rows. Safe after crashes or rate limits.

**Oncology reference averages:** Mistral ~64.8, OpenAI ~76.2 (Claude later ~56.3) — models are calibrated differently; **tags**, not raw scores, drive the shipping `action`.

**Output:** API columns filled on `keyword_scores_v2`. Next: Stage 12.

---

### Stage 12 — `12_claude_export/` — export for Claude

**Command:** `export-for-claude`

Writes `results_v2/keywords_for_claude.csv` with `slug, term, category, definition` for every row (or every row still needing Claude, depending on script version — the v2 export dumps the full set for offline scoring).

```bash
cd 12_claude_export
python run_pipeline.py export-for-claude
```

**Output:** `results_v2/keywords_for_claude.csv`. Next: Stage 13.

---

### Stage 13 — `13_claude_split/` — batch for Claude Code

**Scripts:** `split_for_claude_v2.py`, `claude_scoring_prompt.md`

Splits the export CSV into batches (default **500** rows) under `claude_batches_v2/`, and writes a copy of the scoring instructions Claude Code should follow.

```bash
cd 13_claude_split
python split_for_claude_v2.py /path/to/keywords_for_claude.csv
python split_for_claude_v2.py /path/to/keywords_for_claude.csv --batch-size 300
```

**Claude Code pattern (per batch):**

```bash
claude -p "Read claude_batches_v2/claude_scoring_prompt.md for instructions. \
Score the keywords in claude_batches_v2/batch_001.csv \
Save output as claude_batches_v2/batch_001_scored.csv"
```

Expected scored columns: `slug,claude_score,claude_tag,claude_issue`.

**Why batches:** ~10K rows is too large for one reliable Claude Code session; 500-row chunks keep context and output stable.

**Output:** `claude_batches_v2/batch_NNN.csv` + `batch_NNN_scored.csv` after scoring. Next: Stage 14.

---

### Stage 14 — `14_claude_merge/` — merge Claude CSVs

**Script:** `merge_claude_scores_v2.py`

Merges all `batch_*_scored.csv` files, remaps common alternate column names (`score` → `claude_score`, etc.), deduplicates by slug (last wins), writes `claude_all_scored_v2.csv`.

```bash
cd 14_claude_merge
python merge_claude_scores_v2.py --input-dir ../13_claude_split/claude_batches_v2
```

**Output:** `claude_all_scored_v2.csv`. Next: Stage 15.

---

### Stage 15 — `15_claude_import/` — upload Claude scores

**Command:** `import-claude`

```bash
cd 15_claude_import
python run_pipeline.py import-claude --csv ../14_claude_merge/claude_all_scored_v2.csv --dry-run
python run_pipeline.py import-claude --csv ../14_claude_merge/claude_all_scored_v2.csv
```

Upserts `claude_score`, `claude_tag`, `claude_issue` onto matching slugs. `--dry-run` previews without writing.

**Output:** Claude columns filled. Next: Stage 16.

---

### Stage 16 — `16_ensemble_consensus/` — majority action

**Command:** `ensemble`

Computes `avg_score`, `consensus`, `tag_consensus`, `action`, and `flag` for every row using the rules in “Shared Concepts” above.

```bash
cd 16_ensemble_consensus
python run_pipeline.py ensemble
```

**Oncology V2 audit breakdown** (`keyword_scores_v2`, 10,049 rows — see `sample_data/summary_v2_example.txt`): approved 37.1%, supplementary 29.8%, junk 13.0%, too_basic 11.0%, REVIEW 5.8%, fix_definition 3.4%. Flagged: 33.1%.

After Stage 18 production filtering, the live shipping table looks different — see **[RESULTS.md](./RESULTS.md)** and Stage 18 below.

**Output:** ensemble columns on `keyword_scores_v2`. Next: Stage 17.

---

### Stage 17 — `17_report/` — local artifacts

**Command:** `report`

```bash
cd 17_report
python run_pipeline.py report
```

**Output:**

- `results_v2/comparison_report_v2.csv` — full per-row dump for spreadsheets / further filtering
- `results_v2/summary_v2.txt` — human-readable totals, tag histograms, disagreement examples

An example summary from the oncology run is checked in as `sample_data/summary_v2_example.txt`.

---

### Stage 18 — `18_production_export/` — handoff CSVs

**Script:** `prepare_production.py`  
**Tables:** reads `keyword_scores_v2` → writes `keyword_scores_production`

**What it does:**

1. `create-table` — prints SQL for `keyword_scores_production`
2. `populate` — copies rows whose `action` is in `{approved, supplementary, fix_definition, too_basic}` (junk / REVIEW handling depends on your ops choice; the script keeps the four non-junk operational actions)
3. `export` — writes CSVs for the content pipeline owner (Thejus / Pipeline A–B maintainer)

```bash
cd 18_production_export
python prepare_production.py create-table
python prepare_production.py populate
python prepare_production.py export
```

**Exports (typical):**

| File | Purpose |
|------|---------|
| `exports/approved_supplementary.csv` (or `approved_supplementary_toobasic.csv`) | Candidates for textbook integration / filtering |
| `exports/fix_definition.csv` | Send back to Pipeline A for regenerated definitions |
| `exports/final_keywords.csv` | Oncology shipping list used by `filter_to_v5.py` |

`final_keywords.csv` columns in the oncology handoff include:  
`slug, term, category, definition, action, avg_score, mistral_tag, openai_tag, claude_tag, tag_consensus`.

### Oncology production table (final)

**Table:** `keyword_scores_production` — **8,161** rows  
(`keyword_scores_v2` with 10,049 rows kept as an untouched audit copy.)

| Status | Count | % | Notes |
|--------|------:|--:|-------|
| Approved | 3,758 | 46.0% | Show popup |
| Supplementary | 3,101 | 38.0% | Show popup |
| Too Basic | 1,194 | 14.6% | **Kept** — professor asked to include elementary terms |
| REVIEW | 68 | 0.8% | Still needs human review |
| Junk | 30 | 0.4% | Delete |
| Fix Definition | 10 | 0.1% | Still needs regeneration |

**Ready for textbook: 8,053** (approved + supplementary + too_basic).

v2 → production transition dropped the **1,302 junk** rows from the audit run and resolved most of the **586 REVIEW** items (68 remain).

**This is the bridge back to stages `06`–`07`:** the popup pipeline’s optional review layer consumes these CSVs to build `keywords_v5.jsonl` before merge/upload.

---

### Stage 19 — `19_definition_fix_loop/` — regenerate and re-score

When `fix_definition.csv` comes back with new text (e.g. `fix_definitions_filled.jsonl` from Pipeline A):

1. **`update_fixed_definitions.py`** — upserts new `definition` values into `keyword_scores_production` and resets model scores to `-1` for those slugs so they are re-scored.
2. **`ensemble_pipeline_prod.py`** — same CLI shape as v2, but pointed at `keyword_scores_production` / `results_prod/`.

```bash
cd 19_definition_fix_loop
python update_fixed_definitions.py --input fix_definitions_filled.jsonl --dry-run
python update_fixed_definitions.py --input fix_definitions_filled.jsonl
python ensemble_pipeline_prod.py score --model mistral
python ensemble_pipeline_prod.py score --model openai
# Claude export/score/import on the fix subset, then:
python ensemble_pipeline_prod.py ensemble
```

**Output:** updated production scores; re-export from Stage 18 when ready.

---

### Stage 20 — `20_keyword_dashboard/` — human review UI

Static HTML dashboards that read `keyword_scores_v2` (or production) via Supabase REST with the **anon** key (requires the SELECT policy from Stage 10).

| File | Role |
|------|------|
| `keyword-qa-dashboard-v2.html` | Primary V2 QA UI — filter by action, consensus, flag, search |
| `dashboard.html` | Alternate / earlier dashboard layout |

Open the HTML file in a browser; configure project URL + anon key in the page’s settings fields (do not commit real keys).

Use this for:

- Spot-checking `REVIEW` rows (all three models disagreed)
- Sampling `fix_definition` before sending to Pipeline A
- Sanity-checking that `junk` really looks like junk

---

## Pipeline D — Acronym QA (Stages 21–25)

### Why a separate track

Pipeline B’s abbreviations are a different failure mode than Wikipedia keywords:

- Wrong **expansion** (`AI` → Artificial Intelligence vs Aromatase Inhibitor in oncology pharmacology context)
- Correct expansion but definition copied the wrong sense
- Organizations and tools that are relevant (`FDA`, `WHO`, `MRI`) vs irrelevant (`NATO`)
- Noise from the uppercase regex (`AND`, trial IDs, etc. — ideally already filtered in Pipeline B, but QA still catches stragglers)

Pipeline D reuses the five tags and ensemble math, with an acronym-specific system prompt.

### Stage 21 — `21_acronym_setup/`

**Script:** `acronym_pipeline.py`  
**Table:** `acronym_scores_v1`

```bash
cd 21_acronym_setup
python acronym_pipeline.py setup --input /path/to/keywords_abbrevs_enriched.jsonl
python acronym_pipeline.py setup --input ../sample_data/sample_acronyms.jsonl
```

First run prints `CREATE TABLE` SQL — run it in Supabase, then re-run setup.

Maps abbreviation JSONL fields (`keyword` / expansion / `definition_short`) into scoring rows. Oncology reference: **927** rows.

### Stage 22 — `22_acronym_score_api/`

```bash
cd 22_acronym_score_api
python run_pipeline.py score --model mistral
python run_pipeline.py score --model openai
python run_pipeline.py status
```

~93 batches at batch size 10 for 927 rows; roughly 15–20 minutes per model depending on rate limits.

### Stage 23 — `23_acronym_claude/`

**Prompt file:** `claude_acronym_prompt.md`

```bash
cd 21_acronym_setup
python acronym_pipeline.py export-for-claude
# → results_acronyms/acronyms_for_claude.csv
```

927 rows is small enough for **one** Claude Code session (no mandatory split, unlike keywords). Paste/use `23_acronym_claude/claude_acronym_prompt.md`, save `claude_acronym_scored.csv`, then:

```bash
python acronym_pipeline.py import-claude --csv results_acronyms/claude_acronym_scored.csv
```

### Stage 24 — `24_acronym_ensemble_report/`

```bash
cd 24_acronym_ensemble_report
python run_pipeline.py ensemble
python run_pipeline.py status
python run_pipeline.py report
```

Same consensus fields as keywords. Use `action` to decide which abbreviations merge into the final popup set (typically keep `approved` + `supplementary`).

### Oncology acronym results (final)

**Table:** `acronym_scores_v1` — **927** rows

| Status | Count | % |
|--------|------:|--:|
| Approved | 775 | 83.6% |
| Supplementary | 140 | 15.1% |
| REVIEW | 7 | 0.8% |
| Fix Definition | 5 | 0.5% |

**Ready for textbook: 915** (approved + supplementary).

Open tails:

- **Fix definition (5):** `cd39`, `nca`, `pi3`, `dtp`, `hdi` — corrected text identified but not yet updated/re-scored  
- **REVIEW (7):** `atp`, `cns`, `adp`, `nf`, `rainbow`, `ve`, `tets`

Full combined keyword + acronym totals: **[RESULTS.md](./RESULTS.md)**.

### Stage 25 — `25_acronym_dashboard/`

**File:** `acronym-qa-dashboard.html` — same idea as Stage 20, bound to `acronym_scores_v1`.

---

## Supabase Table Schemas

### `keyword_scores_v2` / `keyword_scores_production` / `acronym_scores_v1`

Core shape (acronym table may name the display column `acronym` + `expansion` instead of only `term` — see script SQL output):

```sql
CREATE TABLE IF NOT EXISTS keyword_scores_v2 (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    term TEXT,
    category TEXT,
    definition TEXT,
    mistral_score INTEGER DEFAULT -1,
    mistral_issue TEXT DEFAULT '',
    mistral_tag TEXT DEFAULT '',
    openai_score INTEGER DEFAULT -1,
    openai_issue TEXT DEFAULT '',
    openai_tag TEXT DEFAULT '',
    claude_score INTEGER DEFAULT -1,
    claude_issue TEXT DEFAULT '',
    claude_tag TEXT DEFAULT '',
    avg_score FLOAT DEFAULT -1,
    consensus TEXT DEFAULT '',
    action TEXT DEFAULT '',
    tag_consensus TEXT DEFAULT '',
    flag BOOLEAN DEFAULT FALSE,
    scored_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE keyword_scores_v2 ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow anon read on keyword_scores_v2"
    ON keyword_scores_v2 FOR SELECT TO anon USING (true);
```

Score sentinel: **`-1` means “not yet scored.”** Ensemble ignores `-1` when averaging.

---

## Environment Variables

| Variable | Used by | Notes |
|----------|---------|-------|
| `QA_SUPABASE_URL` | All DB stages | Prefer this over Next.js public URL |
| `QA_SUPABASE_KEY` | All DB stages | **service_role** key for writes |
| `MISTRAL_API_KEY` | Stage 11 / 22 | Required for Mistral scoring |
| `OPENAI_API_KEY` | Stage 11 / 22 | Required for OpenAI scoring |
| `NEXT_PUBLIC_SUPABASE_URL` | Fallback only | Used if `QA_SUPABASE_URL` unset |
| `SUPABASE_SERVICE_ROLE_KEY` | Fallback only | Used if `QA_SUPABASE_KEY` unset |

Copy `.env.example` → `.env` at the repo root of this package (or next to the script you run). Scripts search script-dir then cwd.

---

## Adapting to a New Textbook / Domain — Checklist

| Step | What to change |
|------|----------------|
| Prompts | Domain name and examples in `ensemble_pipeline_v2.py` (`PROMPT_TEMPLATE`), `13_claude_split/claude_scoring_prompt.md`, `23_acronym_claude/claude_acronym_prompt.md`, and the acronym prompt inside `acronym_pipeline.py` |
| Categories listed in prompts | Swap oncology category list for your subject’s labels |
| Input files | Point `setup --input` at your Pipeline A/B JSONL |
| Table names | Change `TABLE = ...` at the top of the CLIs if you need a fresh run alongside an old one |
| Pass threshold | `70` is hardcoded in ensemble — adjust only if you recalibrate deliberately |
| SHOW_TAGS | Default `{approved, supplementary}` — change only if product policy changes |

Everything else (slug upsert, batching, merge, dashboards’ REST pattern) is domain-agnostic.

---

## Handoff Checklist (Keyword QA → Popup Upload)

1. Pipeline C `ensemble` + `report` completed; spot-check `REVIEW` in the dashboard  
2. `prepare_production.py export` produced `final_keywords.csv` / approved + fix_definition CSVs  
3. `fix_definition` rows sent to Pipeline A; filled JSONL returned through Stage 19 if needed  
4. Approved slug list fed into `filter_to_v5.py` (or treat approved export as v5-equivalent)  
5. Pipeline D actions applied to abbreviation merge (drop `junk` / `too_basic`, fix or drop `fix_definition`)  
6. Stage `06_merge` + `07_upload` run as documented in the Keyword Popup Pipeline  
7. Optional: stratified spot-check with `reference/sample_for_review.py` against live `articles`

---

## File Reference

| File | Pipeline | Purpose |
|------|----------|---------|
| `10_keyword_setup/ensemble_pipeline_v2.py` | C, 10–17 | Main keyword QA CLI (setup, score, export, import, ensemble, status, report) |
| `11_keyword_score_api/run_pipeline.py` | C, 11 | Wrapper → score API models |
| `12_claude_export/run_pipeline.py` | C, 12 | Wrapper → export-for-claude |
| `13_claude_split/split_for_claude_v2.py` | C, 13 | Split CSV into Claude Code batches |
| `13_claude_split/claude_scoring_prompt.md` | C, 13 | Instructions pasted into Claude Code |
| `14_claude_merge/merge_claude_scores_v2.py` | C, 14 | Merge `batch_*_scored.csv` |
| `15_claude_import/run_pipeline.py` | C, 15 | Wrapper → import-claude |
| `16_ensemble_consensus/run_pipeline.py` | C, 16 | Wrapper → ensemble |
| `17_report/run_pipeline.py` | C, 17 | Wrapper → report |
| `18_production_export/prepare_production.py` | C, 18 | Production table + handoff CSVs |
| `19_definition_fix_loop/update_fixed_definitions.py` | C, 19 | Load regenerated defs, reset scores |
| `19_definition_fix_loop/ensemble_pipeline_prod.py` | C, 19 | Re-score against `keyword_scores_production` |
| `20_keyword_dashboard/*.html` | C, 20 | Browser QA UI |
| `21_acronym_setup/acronym_pipeline.py` | D, 21–24 | Main acronym QA CLI |
| `22_acronym_score_api/run_pipeline.py` | D, 22 | Wrapper → acronym score |
| `23_acronym_claude/claude_acronym_prompt.md` | D, 23 | Claude Code acronym instructions |
| `24_acronym_ensemble_report/run_pipeline.py` | D, 24 | Wrapper → ensemble/report |
| `25_acronym_dashboard/acronym-qa-dashboard.html` | D, 25 | Acronym browser QA UI |
| `sample_data/sample_keywords.jsonl` | C | 5-row smoke-test input |
| `sample_data/sample_acronyms.jsonl` | D | 3-row smoke-test input |
| `sample_data/summary_v2_example.txt` | C | Real oncology summary snapshot |
| `reference/ensemble_pipeline_v1.py` | — | Earlier Gemini/Mistral/Llama prototype |
| `reference/ensemble_verify.py` | — | Early verification helper |
| `reference/steps_keyword_v2.md` | — | Original operator step notes for V2 |
| `reference/STEPS_ACRONYMS.md` | — | Original operator step notes for acronyms |

---

## Final Oncology Results (canonical)

See **[RESULTS.md](./RESULTS.md)** for the authoritative post-production counts. Short version:

| Category | Count |
|----------|------:|
| Keywords ready (`approved` + `supplementary` + `too_basic`) | 8,053 |
| Acronyms ready (`approved` + `supplementary`) | 915 |
| **Combined ready for textbook** | **8,968** |
| Still needs human review | 75 |
| Still needs definition fix | 15 |
| Junk to delete | 30 |

Tables: `keyword_scores_v2` (10,049 audit) · `keyword_scores_production` (8,161) · `acronym_scores_v1` (927).  
Coverage: ≈ **98.6%** keywords and **98.7%** acronyms verified and ready.

---

## Relationship to Keyword Popup Pipeline Docs

In `KEYWORD_PIPELINE_DOCS.md` (colleague package), the section **“Optional — Multi-Model Quality Review”** describes this process at a high level and notes that the harness did not live in that folder. **This package is that harness**, with real scripts, stage numbers `10`–`25`, and the oncology final counts in **[RESULTS.md](./RESULTS.md)** (8,053 keywords + 915 acronyms ready ≈ **8,968** popups).
