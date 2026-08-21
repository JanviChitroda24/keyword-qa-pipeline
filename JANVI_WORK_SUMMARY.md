# Janvi Chitroda — Medhavi Keyword/Acronym QA Pipeline  
## Comprehensive Work Summary

**Role:** AI Data Engineer — Quality Gate (Pipelines C–D)  
**Project:** Medhavi cancer biology textbook — keyword popup feature  
**Repos:** https://github.com/JanviChitroda24/keyword-qa-pipeline  
**Companion (content generation, Thejus):** https://github.com/thejusthom/keyword-popup-pipeline  
**Primary code paths:** `medhavi-cancer/janvi_keywords_feature/` · packaged docs in `popup_doc/keyword-qa-pipeline/`

---

## 1. Pipeline Architecture & Design Decisions

### 1.1 Why a 3-model ensemble (Mistral Small + GPT-4o-mini + Claude)

Content generation (Wikipedia → LLM rewrite; MDX → acronym enrich) produces candidates at scale (~10K keywords, ~927 acronyms). A single model writing definitions does not reliably catch its own mistakes (junk pages, disambiguation leftovers, wrong acronym expansions, relevance edge cases).

| Option | Verdict |
|--------|---------|
| 1 model | Encodes one lab’s blind spots as product truth |
| 2 models | Better, but ties have no clean breaker |
| **3 models** | **Majority (2 of 3) is well-defined; all-three-disagree → explicit `REVIEW` queue** |
| 5+ models | Cost/latency up; diminishing returns |

**Provider diversity mattered:** Mistral + OpenAI + Anthropic (Claude), not three models from one vendor. Same-family ensembles share failure modes.

**API models first, Claude second:** Mistral and GPT-4o-mini are batchable overnight via HTTPS. Claude ran via Claude Code on CSV batches (~500 rows) for careful instruction-following at ~10K scale without fighting API quotas, and so any bad batch could be re-run in isolation.

**Scores vs tags:** Raw 0–100 scores were poorly calibrated across judges (V2 audit averages: Mistral ~64.8, OpenAI ~76.2, Claude ~56.3). Shipping on `avg ≥ 70` would unfairly punish Claude. **Tag majority drives `action`; scores are for analytics and sorting.**

---

### 1.2 Evolution from V1 → V2

| | **V1** | **V2 (shipping)** |
|--|--------|-------------------|
| Models | Gemini + Mistral + Llama (Ollama) | Mistral Small + GPT-4o-mini + Claude |
| Scope | ~50-row test slice from live `articles` → `keyword_scores_test` | Full regenerated JSONL (~10,049) → `keyword_scores_v2` |
| Scripts | `ensemble_pipeline.py`, `ensemble_verify.py`, `test_connections.py` | `ensemble_pipeline_v2.py` + Claude split/merge |
| Tags | Early tagging experiments | Formal **5-tag** system with strict decision order |
| Claude | Not in the primary trio | Offline CSV batch workflow |
| Why change | Gemini free-tier rate limits; Discovery cluster blocked reliable Ollama/Llama access; PATCH issues on cluster proxy | Stable APIs, majority vote, resumable full-corpus scoring |

**V1 lesson kept:** resumable scoring (`score = -1` = unscored), Supabase as shared store, preflight connectivity checks.  
**V1 retired:** Gemini and Llama as required judges.

---

### 1.3 Five-tag classification system

Binary pass/fail collapses different workflows. Each tag maps to an owner and a next action:

| Tag | Meaning | Product action | Owner of follow-up |
|-----|---------|----------------|--------------------|
| `approved` | Core cancer/biotech/nanomedicine relevance; accurate definition | **Show** popup | Ship |
| `supplementary` | Supporting science (`DNA`, `pH`, `enzyme`) students need while reading | **Show** popup | Ship |
| `too_basic` | Too elementary *or* too off-topic for bachelor level | Hide by default; **keywords kept by professor policy** | Product / PM |
| `fix_definition` | Term belongs; text is wrong, empty, truncated, or disambiguation | **Regenerate** | Thejus (Pipeline A/B) → Janvi re-score |
| `junk` | Not a real keyword (category pages, biographies, markup noise) | **Delete** | Drop |

**Strict decision order in prompts** (junk → empty/broken → too_basic → approved → supplementary) so models don’t invent inconsistent policies (e.g. tagging a Wikipedia category page as `too_basic` instead of `junk`).

---

### 1.4 Consensus / majority-vote approach

After all three judges score a row:

1. Collect valid tags ∈ {approved, supplementary, too_basic, fix_definition, junk}.
2. If all three agree → `tag_consensus = AGREE`, `action = that tag`.
3. If 2 of 3 agree → `tag_consensus = MAJORITY`, `action = majority tag`.
4. If all three differ → `tag_consensus = DISAGREE`, `action = REVIEW` (human required).
5. `flag = true` unless `action ∈ {approved, supplementary}` (engineering default).

Separately, **score consensus** (threshold 70) records `ALL_PASS` / `ALL_FAIL` / `DISAGREE` for reporting — not the shipping rule.

**V2 audit score consensus (10,049 rows):** ALL_PASS 39.7% · ALL_FAIL 20.0% · DISAGREE 40.2% — evidence that scores alone would be a poor ship gate. Tag-level full disagreement (`REVIEW`) was only **5.8%** (586 rows) on the audit table.

---

### 1.5 Audit vs production tables

| Table | Rows | Role |
|-------|-----:|------|
| `keyword_scores_v2` | 10,049 | **Immutable audit** — full ensemble history |
| `keyword_scores_production` | 8,161 | Working/shipping set after filtering |
| `acronym_scores_v1` | 927 | Acronym verification |

**Why separate:** Once junk is dropped from the only copy, you cannot answer “why was this removed?” later. Audit is cheap; lost history is expensive in professor/PM review.

v2 → production: dropped **1,302 junk**; resolved most of **586 REVIEW**; kept `too_basic` after professor feedback.

---

### 1.6 Auto-approve override (`avg_score >= 75`)

Implemented in **`acronym_pipeline.py`** ensemble (Pipeline D), not in keyword `ensemble_pipeline_v2.py`:

```python
# Override: if avg score >= 75, auto-approve (resolve borderline cases)
if avg >= 75 and action not in SHOW_TAGS:
    action = "approved"
    flag = False
```

**Intent:** When tag majority would hide/flag a row but all three models still gave a high average confidence score, treat as borderline-resolvable and auto-approve rather than bloating the human REVIEW queue for acronyms. Keywords rely on tag majority + production policy without this override.

---

## 2. Scripts & Tools Built

### 2.1 Core keyword QA (Pipeline C)

#### `ensemble_pipeline_v2.py`
**Location:** `janvi_keywords_feature/new_version/` · packaged as `10_keyword_setup/ensemble_pipeline_v2.py`

Main CLI for keyword QA: `setup`, `score --model mistral|openai`, `export-for-claude`, `import-claude`, `ensemble`, `status`, `report`. Loads JSONL into Supabase, scores in batches (default 10), computes majority action, writes reports under `results_v2/`.

**Key decisions:** stdlib `urllib` only (no heavy deps); `POST` upsert instead of `PATCH` for Discovery proxy compatibility; upload batch size **50** with SSL retry (2s/4s/6s backoff); skip already-scored rows for resumability; debug dumps under `results_v2/debug_responses/`.

**Bugs / fixes:** Transient SSL drops on large upserts → smaller batches + retries. HTTP `PATCH` blocked/unreliable on Discovery cluster proxy → all updates via `POST` upsert on `slug`.

---

#### `split_for_claude_v2.py`
Splits `keywords_for_claude.csv` into `claude_batches_v2/batch_NNN.csv` (default **500** rows) and writes `claude_scoring_prompt.md`.

**Key decisions:** 500-row batches keep Claude Code context reliable at ~10K scale; prompt embedded in script so batches are self-contained.

---

#### `merge_claude_scores_v2.py`
Merges `batch_*_scored.csv` → `claude_all_scored_v2.csv`; remaps alternate Claude headers (`score` → `claude_score`, etc.); dedupes by slug.

**Key decisions:** Defensive column remapping — Claude does not always obey CSV headers exactly. That was a learned robustness fix, not accidental complexity.

---

#### `prepare_production.py`
Creates/populates `keyword_scores_production` from v2; exports handoff CSVs (`approved_supplementary*.csv`, `fix_definition.csv`, `final_keywords.csv`).

**Key decisions:** Copy operational actions only; keep audit table untouched; SSL-safe batched upsert.

---

#### `update_fixed_definitions.py` + `ensemble_pipeline_prod.py`
Fix-definition loop: load regenerated JSONL into production, reset scores to `-1`, re-score only those rows against `keyword_scores_production` / `results_prod/`.

**Key decisions:** Don’t re-run all 10K when ~300 definitions need regeneration; Thejus owns text, Janvi owns re-verification.

---

#### `split_for_claude.py` / `upload_claude_scores.py` / `claude_scoring_prompt.md` (V1 helpers)
Earlier Claude path before the v2 split/merge packaging. Kept under `reference/` for history.

---

### 2.2 Acronym QA (Pipeline D)

#### `acronym_pipeline.py`
Same CLI shape as keyword QA for `acronym_scores_v1` (~927 rows). Acronym-specific prompt checks **expansion correctness**, definition accuracy, and broad textbook relevance (FDA/WHO/MRI yes; NATO no).

**Key decisions:** Separate track from keywords (different failure modes); **auto-approve if `avg_score >= 75`** when action would not show; 927 rows fit one Claude Code session (no mandatory split).

---

#### `claude_acronym_prompt.md`
Claude Code instructions for acronym verification (expansion + definition + relevance).

---

### 2.3 V1 / infrastructure helpers

#### `ensemble_pipeline.py` (V1)
Prototype: Gemini + Mistral + Llama/Ollama; load from `articles` into `keyword_scores_test`; used `PATCH` for updates.

#### `ensemble_verify.py`
Early verification harness toward the same ensemble idea.

#### `test_connections.py`
Preflight script for Gemini / Mistral / Ollama before full runs (later largely superseded when V2 dropped Gemini/Llama).

#### `export_all_keywords.py` / `sample_for_review.py`
Export and stratified spot-check utilities around Supabase keyword data.

---

### 2.4 Packaged documentation repo

Stage folders `10_`–`25_`, plus `README.md`, `KEYWORD_QA_PIPELINE_DOCS.md`, `DESIGN.md`, `RESULTS.md`, `CLAUDE_CODE_PROMPT.md`, sample JSONL, and HTML dashboards — so the next engineer can run or adapt the gate without reconstructing chat history.

---

## 3. Infrastructure & Data

### 3.1 Supabase tables

**Shared scoring schema (conceptually):**

```text
slug (PK), term/acronym fields, category, definition,
mistral_score/tag/issue, openai_score/tag/issue, claude_score/tag/issue,
avg_score, consensus, tag_consensus, action, flag, scored_at
```

Sentinel: **`-1` = not yet scored.**

| Table | Rows | Purpose |
|-------|-----:|---------|
| `keyword_scores_v2` | 10,049 | Full audit — **do not modify** |
| `keyword_scores_production` | 8,161 | Production keywords |
| `acronym_scores_v1` | 927 | Acronym verification |
| `keyword_scores_test` (V1) | ~50 | Early prototype only |

RLS: anon **SELECT** enabled for dashboards; Python writes use **service_role** key.

---

### 3.2 `.env` configuration

```text
QA_SUPABASE_URL=https://….supabase.co
QA_SUPABASE_KEY=eyJ…          # service_role for writes
MISTRAL_API_KEY=…
OPENAI_API_KEY=sk-…
```

Fallbacks in code: `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.  
V1 also used `GEMINI_API_KEY`, `OLLAMA_URL` (default `http://localhost:11434`).

---

### 3.3 Claude Code batch workflow (keywords)

```text
export-for-claude
  → results_v2/keywords_for_claude.csv
split_for_claude_v2.py  (batch size 500)
  → claude_batches_v2/batch_001.csv …
  → claude_scoring_prompt.md
Claude Code scores each batch
  → batch_NNN_scored.csv  (slug, claude_score, claude_tag, claude_issue)
merge_claude_scores_v2.py
  → claude_all_scored_v2.csv
import-claude
  → Supabase claude_* columns
ensemble → report
```

Acronyms: export → **one** Claude session → import (no split required at 927 rows).

---

### 3.4 NEU Discovery cluster & why Llama was not used

**Plan:** Run heavy API scoring on Discovery; use local/cluster Ollama for Llama as the third judge.

**What happened:**

- Discovery was usable for **Mistral/OpenAI HTTPS** scoring (documented in `steps.md`).
- **Ollama/Llama** was not reliably reachable from the cluster environment (`Llama/Ollama NOT REACHABLE` path in V1 preflight).
- Cluster **proxy interfered with HTTP `PATCH`** to Supabase → switched to **POST upsert**.
- Gemini free tier **429 rate limits** made Gemini a poor full-corpus judge.

**Outcome:** Drop Gemini + Llama from the required trio; standardize on Mistral + OpenAI + Claude Code. Discovery remained optional for API scoring; Claude batches ran on laptop.

---

## 4. Dashboards

### 4.1 `keyword-qa-dashboard-v2.html` (primary)

Static HTML; login with Supabase URL + anon (or service) key; reads `keyword_scores_v2` / production via REST pagination.

**Features:**

- Action summary cards (approved / supplementary / too_basic / fix_definition / junk / REVIEW)
- Per-model cards (count scored, average score, below-70, tag chips)
- Stacked action distribution bar
- Filters by action + search by term/slug
- Paginated table; row click → **modal** with definition + per-model score/tag/issue comparison
- Refresh without rebuilding the page

### 4.2 `dashboard.html` / acronym dashboard

Same pattern for alternate keyword layout and for `acronym_scores_v1` (`acronym-qa-dashboard.html`).

### 4.3 V1 dashboards (`keyword-qa-dashboard.html`, `keyword_dashboard_qa.html`)

Earlier UIs with Gemini/Mistral/Llama columns — superseded by V2 but kept in `reference/`.

**Design choice:** Dumb HTML on purpose — no admin app until tags/ensemble stabilized through a full textbook run.

---

## 5. Results & Metrics

### 5.1 Keyword audit (`keyword_scores_v2`, 2026-06-18) — 10,049 rows

| Action | Count | % |
|--------|------:|--:|
| approved | 3,727 | 37.1% |
| supplementary | 2,994 | 29.8% |
| junk | 1,302 | 13.0% |
| too_basic | 1,102 | 11.0% |
| REVIEW | 586 | 5.8% |
| fix_definition | 338 | 3.4% |

Flagged (engineering default hide): **3,328 / 10,049 (33.1%)**.

| Model | Scored | Avg | Below 70 |
|-------|-------:|----:|---------:|
| Mistral | 9,914 | 64.8 | 3,578 |
| OpenAI | 9,826 | 76.2 | 1,823 |
| Claude | 10,017 | 56.3 | 5,944 |

**Model agreement (tags):** Full three-way tag disagreement (`REVIEW`) = **5.8%** → ~**94.2%** AGREE or MAJORITY on the audit table.  
**Score agreement:** only **39.7%** ALL_PASS — reinforces tag-majority shipping.

---

### 5.2 Keyword production (`keyword_scores_production`) — 8,161 rows

| Status | Count | % |
|--------|------:|--:|
| Approved | 3,758 | 46.0% |
| Supplementary | 3,101 | 38.0% |
| Too Basic | 1,194 | 14.6% |
| REVIEW | 68 | 0.8% |
| Junk | 30 | 0.4% |
| Fix Definition | 10 | 0.1% |

**Ready for textbook: 8,053** (approved + supplementary + too_basic).  
≈ **98.6%** of production keywords ready.

---

### 5.3 Acronyms (`acronym_scores_v1`) — 927 rows

| Status | Count | % |
|--------|------:|--:|
| Approved | 775 | 83.6% |
| Supplementary | 140 | 15.1% |
| REVIEW | 7 | 0.8% |
| Fix Definition | 5 | 0.5% |

**Ready for textbook: 915** (approved + supplementary).  
≈ **98.7%** of acronyms ready.

---

### 5.4 Five acronyms with wrong expansions (caught by ensemble)

| Slug | Bad expansion / issue in generated data | Ensemble finding |
|------|-------------------------------------------|------------------|
| **cd39** | Labeled “CD39 Ecto-5-Nucleotidase”; Claude noted ecto-5′-nucleotidase is **CD73**, CD39 is NTPDase1/ENTPD1 | Mixed tags; flagged for definition/expansion quality |
| **nca** | Expansion “Non-Specific Cross-Reacting Antigen” but definition described the **National Cancer Act (1971)** | Unanimous `fix_definition` / junk signals; avg ~22.7 |
| **pi3** | “Phosphatidylinositol-3 Kinase **Substrate**” — should be kinase / **PI3K** family sense | All three: `fix_definition` |
| **dtp** | “Deoxyribonucleoside Triphosphate” mixed with cancer “DTP cells”; oncology sense often **Drug-Tolerant Persister**; also confused with DTP vaccine | All three: `fix_definition` |
| **hdi** | “High-Dose Interleukin” conflated with **Human Development Index** | All three: `fix_definition` |

Corrected definitions were identified for these five but **not yet written back and re-scored** (see Pending).

**REVIEW acronyms (7):** `atp`, `cns`, `adp`, `nf`, `rainbow`, `ve`, `tets`.

---

### 5.5 Combined totals

| Category | Count |
|----------|------:|
| **Ready for textbook** | **8,968** (8,053 keywords + 915 acronyms) |
| Needs human review | 75 (68 keywords + 7 acronyms) |
| Needs definition fix | 15 (10 keywords + 5 acronyms) |
| Junk to delete (production) | 30 keywords |

---

## 6. Key Technical Challenges & Solutions

| Challenge | Solution |
|-----------|----------|
| **SSL drops during Supabase upload** | Batch size **50**; retry up to 3× with backoff on SSL/timeout/connection errors; upsert is idempotent so full re-run is safe |
| **PATCH blocked by Discovery proxy** | Replace row updates with **POST upsert** (`on_conflict=slug`, Prefer `resolution=merge-duplicates`) |
| **Supabase project pausing (inactivity)** | Re-awaken project in dashboard before scoring/dashboard use; document that free-tier pause breaks mid-run API calls |
| **Claude Code CLI setup / auth** | Documented export → split → `claude -p "…"` per batch → merge → import; prompt files committed beside batches |
| **Gemini free-tier rate limiting (429)** | V1 had 60s backoff on 429; ultimately **replaced Gemini** with OpenAI GPT-4o-mini in V2 |
| **Discovery blocking / unreachable Ollama** | Preflight detected failure; **replaced Llama** with Claude as third judge |
| **Claude CSV header drift** | `merge_claude_scores_v2.py` remaps `score` / `issue_tag` / `issue_detail` |
| **Score calibration mismatch across models** | Ship on **tag majority**, not raw average threshold |

---

## 7. Collaboration Points

### 7.1 Shared with Thejus

- Methodology: 5-tag system, majority vote, why tags beat scores  
- Handoff CSVs: `final_keywords.csv`, `approved_supplementary*.csv`, `fix_definition.csv`  
- Interface contract: his JSONL in → QA allowlists out → his `filter_to_v5` / merge / upload  
- Fix-definition loop: he regenerates targeted defs; Stage 19 re-scores production only  
- Stage numbering `10_`–`25_` so both packages read as one system  

### 7.2 Gene Ontology discussion

Shared design (with Thejus’s Pipeline B):

- **Not** “replace Wikipedia with GO” (coverage too narrow for a full glossary)  
- **Not** “ignore ontologies”  
- **Hybrid:** Wikipedia for bulk keywords; **GO autocomplete** as optional grounding in acronym enrichment prompts; QA remains the ship gate  

### 7.3 Feedback into his regeneration work

- Large `junk` / `fix_definition` / disambiguation patterns from review → justified separate QA job  
- `fix_definition.csv` drove targeted rewrites instead of full 10K regeneration  
- Acronym expansion failures (cd39, nca, pi3, dtp, hdi, and sense cases like `AI`) informed tighter enrichment/QA prompts  

### 7.4 Professor / standup communication

- Explained ensemble methodology and tag meanings in standups  
- **Product decision:** include keyword `too_basic` in the textbook ready set (professor request) → ready keywords = approved + supplementary + too_basic (**8,053**)  
- Engineering default (`SHOW_TAGS` hide too_basic) preserved in code; shipping policy documented in `RESULTS.md` so the next subject can flip the knob  

---

## 8. Pending / Unfinished Items

| Item | Status |
|------|--------|
| **68 keyword REVIEW** rows in production | Open — needs human triage in dashboard |
| **10 keyword `fix_definition`** rows | Open — regenerate + Stage 19 re-score |
| **30 production junk** rows | Open — confirm delete from shipping set |
| **5 acronym fix_definition** (`cd39`, `nca`, `pi3`, `dtp`, `hdi`) | Corrected defs identified; **not yet updated/re-scored** |
| **7 acronym REVIEW** (`atp`, `cns`, `adp`, `nf`, `rainbow`, `ve`, `tets`) | Open — human decision |
| Final merge/upload of latest QA allowlist into student-facing `articles` / `keywords.json` | Coordinate with Thejus if not already cut from last CSV handoff |
| Optional: apply keyword-side auto-approve policy or resolve remaining REVIEW systematically | Not done; only acronym ensemble has `avg >= 75` override |

---

## 9. How to Cite This Work

- **“Janvi built the keyword/acronym QA pipeline”** — stages `10`–`25`, 5-tag system, 3-model ensemble, production exports, fix loop, dashboards, final ready set **8,968**.  
- **“Thejus built the content generation pipeline”** — stages `00`–`07`, Wikipedia + acronym generation, merge/upload.  
- **Both shaped the product** — Wikipedia + GO hybrid, abbrev vs full-term split, majority-vote shipping, fix_definition contract, `too_basic` inclusion policy.

**Primary references:**  
[DESIGN.md](./DESIGN.md) · [RESULTS.md](./RESULTS.md) · [KEYWORD_QA_PIPELINE_DOCS.md](./KEYWORD_QA_PIPELINE_DOCS.md) · [README.md](./README.md)

---

*Document generated for formal documentation and weekly reporting. Numbers reflect the oncology reference build captured in `RESULTS.md` and the V2 audit summary dated 2026-06-18.*
