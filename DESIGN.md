# Design Decisions — What, Why, How

This document is for the **next engineer** who will adapt this QA pipeline to a new textbook, or rebuild it as a cleaner CLI. It explains the decisions behind the system — not just which script to run, but *why the system looks like this*.

If you only need commands, use [`README.md`](./README.md).  
If you need per-stage mechanics, use [`KEYWORD_QA_PIPELINE_DOCS.md`](./KEYWORD_QA_PIPELINE_DOCS.md).  
If you need final oncology numbers, use [`RESULTS.md`](./RESULTS.md).  
**Read this file when you need to change the design without breaking the intent.**

---

## 1. The problem we were solving

### What

Students reading the Medhavi cancer textbook hover on a term and get a popup definition. Those definitions come from:

1. **Pipeline A** — Wikipedia dump → clean → LLM rewrite (~10K keyword candidates)
2. **Pipeline B** — Textbook MDX scan → abbreviation enrich (~927 acronyms)

That content-generation path (stages `00`–`07`) is necessary. It is **not sufficient** to ship.

### Why a QA gate exists at all

A single LLM rewrite still leaves:

| Failure mode | Example |
|--------------|---------|
| Wikipedia junk that survived category filters | `Category:Nitrogen cycle`, biographies, “list of…” pages |
| Disambiguation leftovers | `CTL can refer to: Champions Tennis League; Cytotoxic T…` |
| Empty / truncated definitions | Term is real; definition field is blank or cut mid-sentence |
| Relevance mismatch | Term is “real science” but too elementary (`water`) or off-topic for this course |
| Ambiguous relevance | `DNA` is not “cancer,” but students need the popup while reading |
| Acronym sense errors | `AI` expanded as Artificial Intelligence instead of Aromatase Inhibitor |

One model writing definitions will not reliably catch its own mistakes. **QA is a separate job from generation** — different prompts, different judges, different success metric (“should a bachelor student see this popup?”).

### How we placed it in the chain

```
00–07  Content generation   →  definitions exist
10–25  Quality gate         →  definitions are allowed to ship
06–07  Merge + upload       →  (re-run after QA CSVs exist)
```

Numbering starts at `10_` so it sits *after* content generation without colliding with the colleague’s stages. The QA package does **not** regenerate Wikipedia text; it **classifies and filters** what generation already produced, and sends a small `fix_definition` set back when regeneration is needed.

**Design rule for the next pipeline:** keep generation and verification as separate stages with separate prompts. Do not ask one LLM call to both invent and police the same definition.

---

## 2. Why three models (not one, not five)

### What

Every entry is judged by:

1. **Mistral Small** (API)  
2. **OpenAI GPT-4o-mini** (API)  
3. **Claude** (Claude Code on CSV batches)

Then a majority vote produces `action`.

### Why three

| Option | Tradeoff |
|--------|----------|
| **1 model** | Cheap and fast — but that model’s blind spots become the textbook’s blind spots. We saw large score-calibration differences across providers; a single judge would silently encode one bias. |
| **2 models** | Better — but ties are awkward, and two-provider disagreement has no tie-breaker. |
| **3 models** | Majority is well-defined (2 of 3). Disagreement among all three is rare and becomes an explicit `REVIEW` queue for humans. |
| **5+ models** | Cost and latency grow linearly; marginal quality gain shrinks. Three was enough to reach ~98.6% ready. |

We also deliberately mixed **providers** (Mistral / OpenAI / Anthropic), not three OpenAI models. Same-family ensembles share failure modes.

### Why these specific models

- **API models first (Mistral + OpenAI):** batchable, cheap, resumable overnight on a cluster or laptop.  
- **Claude second (via Claude Code):** strong at careful instruction-following and edge cases; running it as offline CSV batches avoided API quota fights during the large ~10K pass and let a human/CLI session review prompt quality.

**V1 lesson:** the first prototype used Gemini / Mistral / Llama. V2 standardized on Mistral + OpenAI + Claude because that trio was reliable, available, and easy to operate. Don’t revive V1 unless you have a reason.

### How consensus works (and why tags beat scores)

Each model returns:

- a **score** 0–100 (confidence / quality signal)  
- a **tag** (the operational decision)

**Scores alone are not the shipping rule.** In the oncology V2 run, average scores differed a lot by model (Mistral ~65, OpenAI ~76, Claude ~56). If we had shipped on “avg ≥ 70,” Claude’s stricter scoring would have dominated unfairly.

So:

| Signal | Role |
|--------|------|
| `score` | Soft signal → `avg_score`, `ALL_PASS` / `ALL_FAIL` / `DISAGREE` for analytics |
| `tag` | Hard decision → majority vote → `action` (what we actually do) |
| `flag` | Derived from `action` for dashboards |

**Design rule:** if you change models, re-check score calibration. Prefer **tag majority** as the product decision; keep scores for reporting and sorting review queues.

---

## 3. Why five tags (not approve/reject)

### What

```
approved | supplementary | too_basic | fix_definition | junk
```

### Why not binary pass/fail

Binary “good/bad” collapses different *actions*:

| If we only had pass/fail… | We would lose… |
|---------------------------|----------------|
| Pass | Whether this is core cancer content or supporting science |
| Fail | Whether to **delete**, **hide**, or **regenerate** |

Those are different workflows and different owners:

| Tag | Action | Who owns the follow-up |
|-----|--------|------------------------|
| `approved` | Show popup | Product — ship |
| `supplementary` | Show popup | Product — ship (supporting term) |
| `too_basic` | Hide *or* show (policy) | Product / professor |
| `fix_definition` | Regenerate text | Content pipeline (stages `00`–`07`) |
| `junk` | Delete | Nobody — drop from DB |

`supplementary` exists because bachelor cancer students still need `DNA`, `pH`, `enzyme`. Those are not “cancer terms,” but hiding them hurts reading. A binary “relevant to cancer?” check would wrongly kill them.

`fix_definition` exists so we don’t delete real terms that only have broken text. Generation and deletion are different costs.

`junk` exists so Wikipedia artifacts don’t compete with real terms in the popup index (false matches in MDX are worse than a missing popup).

### Why the decision order in the prompt is strict

The prompt forces judges to check in order:

1. junk?  
2. empty/broken definition on a real term? → fix_definition  
3. too basic / irrelevant?  
4. core domain? → approved  
5. supporting science? → supplementary  

Without order, models invent inconsistent policies (e.g. tagging a category page as `too_basic` instead of `junk`). Strict order makes majority vote meaningful.

### Product policy override: `too_basic` on keywords

Default engineering assumption: `too_basic` → hide (`flag = true`).

**Oncology product decision:** the professor asked to **include** elementary terms in the textbook. So the ready set became:

```
approved + supplementary + too_basic   →  8,053 keywords
```

The code’s `SHOW_TAGS = {approved, supplementary}` was the *default*; the *shipping* rule lives in how Stage 18 exports and how RESULTS count “ready.”  

**Design rule for the next textbook:** treat show/hide of `too_basic` as a **product knob**, not a model truth. Document the professor/PM decision next to the numbers (as in `RESULTS.md`).

---

## 4. Why keywords and acronyms are separate tracks

### What

- **Pipeline C (`10_`–`20_`)** — keywords from Wikipedia/LLM  
- **Pipeline D (`21_`–`25_`)** — acronyms from textbook scan  

Same five tags, same three judges, same ensemble math. Different tables, prompts, and input files.

### Why not one combined scorer

| Dimension | Keywords | Acronyms |
|-----------|----------|----------|
| Failure modes | Junk pages, thin wiki leads, over-broad science | Wrong **expansion**, wrong sense, regex noise |
| Volume | ~10K | ~927 |
| Context needed | Term + definition + category | Expansion + definition + how textbook uses it |
| Claude workflow | Must **split** into ~500-row batches | Fits in **one** Claude Code session |
| Relevance rule | Direct vs supporting vs too basic | Broad-but-real (FDA/WHO ok; NATO not) |

A single prompt that tries to cover both produces worse judgments on both. Acronym QA explicitly asks “is the expansion correct for *this* textbook?” — that question barely applies to full-word keywords.

**Design rule:** reuse the *framework* (tables, ensemble, tags); specialize the *prompt* and *input schema* per content type.

---

## 5. Why Supabase as the scoring store

### What

Scores live in Postgres tables (`keyword_scores_v2`, `keyword_scores_production`, `acronym_scores_v1`), not only in local CSVs.

### Why

| Need | How Supabase helps |
|------|--------------------|
| Resumable scoring | `score = -1` means “not done”; re-run skips finished rows |
| Multi-machine | Cluster scores Mistral; laptop runs Claude; both write the same table |
| Dashboard | Static HTML + anon read policy — no backend app required |
| Audit trail | Keep `keyword_scores_v2` forever; ship from `keyword_scores_production` |
| Collaboration | Content owner and QA owner share one source of truth |

Local CSVs are still used for Claude batches and reports — they’re **exchange formats**, not the system of record.

### Why two keyword tables (audit vs production)

| Table | Role |
|-------|------|
| `keyword_scores_v2` | Full 10,049-row audit — **do not modify** after the fact |
| `keyword_scores_production` | Filtered working set (8,161) for export and fix loops |

**Why:** once you delete junk from the only copy, you can’t answer “what did the models think about this junk?” later. Audit tables are cheap; lost history is expensive when a professor asks why something disappeared.

**Design rule:** never overwrite your first full ensemble run. Copy forward into a production table.

---

## 6. Why the stage order is the way it is

### The sequence (and the reason for each step)

```
10 setup        Load once; establish slug as primary key
11 score APIs   Cheap judges first; fill most of the table overnight
12 export       Materialize a stable CSV snapshot for Claude
13 split        Keep Claude context reliable at ~10K scale
14 merge        Normalize Claude’s messy CSV variants
15 import       Write Claude columns without re-touching API scores
16 ensemble     Only now compute majority — all three votes present
17 report       Human-readable artifact for stakeholders
18 production   Separate shipping table + CSVs for merge/upload
19 fix loop     Small re-score path; don’t rerun 10K from scratch
20 dashboard    Spot-check REVIEW / fix_definition without SQL
```

### Why not “score all three in one command”

- Different failure domains (API rate limits vs Claude session length)  
- Different machines (Discovery cluster vs laptop)  
- Need to inspect API results *before* spending Claude time on a bad prompt  

Resumability > elegance. If stage 14 crashes, stages 10–13 stay done.

### Why Claude is batched offline

Calling Claude for 10K rows in one API loop was less practical during this project than:

1. export CSV  
2. split to 500-row batches  
3. Claude Code scores each batch to `batch_NNN_scored.csv`  
4. merge + import  

That path is slower wall-clock for a single operator, but **debuggable**: you can open any batch file, see bad output, and re-run one batch. The merger remaps alternate column names because Claude doesn’t always obey CSV headers perfectly — that was a **learned** robustness fix, not accidental complexity.

For acronyms (~927), one session is enough — we didn’t force the split machinery where it wasn’t needed.

---

## 7. Why the fix-definition loop exists

### What

Stage 19: take regenerated definitions → update production rows → reset scores to `-1` → re-score only those rows.

### Why

`fix_definition` means “the term belongs; the text doesn’t.” Regenerating all 10K keywords because 300 definitions are broken would be wasteful and would churn already-approved text.

The loop keeps:

- **Pipeline A** responsible for writing better definitions  
- **Pipeline C** responsible for verifying the replacements  

**Design rule:** tags should map to *workflows*, not just labels. If a tag has no owner and no next script, delete the tag.

---

## 8. Why dashboards are dumb HTML

### What

Static HTML files that call Supabase REST with the anon key.

### Why

QA review is filtering, searching, and spot-checking — not a product feature that needs React. A dashboard that deploys as “open this file” kept the loop fast during the oncology push.

RLS policy: anon can **SELECT** only. Writes still use the service role from Python.

**Design rule:** don’t build an admin app until the tag system and ensemble rules have stabilized through at least one full textbook run.

---

## 9. End-to-end mental model (for the next pipeline)

```
┌─────────────────────────────────────────────────────────────┐
│  CONTENT GENERATION (colleague stages 00–07)                │
│  Goal: produce candidate definitions at scale               │
│  Success: coverage + readable text                          │
└────────────────────────────┬────────────────────────────────┘
                             │ JSONL
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  QUALITY GATE (this package, stages 10–25)                  │
│  Goal: decide show / hide / delete / regenerate             │
│  Success: high-precision shipping set + small REVIEW tail   │
│  Method: 3-provider tag majority + human REVIEW queue       │
└────────────────────────────┬────────────────────────────────┘
                             │ final_keywords.csv + acronym actions
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  SHIP (merge + upload + Next.js popup)                      │
│  Goal: students see the right popups                        │
└─────────────────────────────────────────────────────────────┘
```

**What we optimized for**

1. **Resumability** — never redo 10K API calls because Claude failed on batch 17  
2. **Actionable tags** — every label maps to show / hide / delete / regenerate / human  
3. **Provider diversity** — majority across labs, not across siblings of one model  
4. **Auditability** — keep the full V2 table forever  
5. **Human override** — `REVIEW` queue + professor policy on `too_basic`  

**What we did *not* optimize for**

- Single-command elegance  
- Zero human involvement  
- Perfect score calibration across models  
- Fancy UI  

Those can come later; they are not what made 8,968 popups shippable.

---

## 10. Playbook: building the next textbook’s QA pipeline

Copy this checklist; don’t invent a new philosophy unless the product needs it.

1. **Run content generation first** (`00`–`07`) until you have JSONL definitions.  
2. **Copy this package**; change prompts’ domain name, category list, and examples.  
3. **Keep the five tags** unless product truly needs a sixth workflow.  
4. **Keep three providers** if budget allows; if you must drop to two, define a tie-break (`REVIEW` or prefer the stricter model) *before* you score.  
5. **Smoke-test** with `sample_data/` and `--limit 5` before full spend.  
6. **Score APIs → then Claude**; inspect a sample of API tags before paying for Claude on the full set.  
7. **Freeze an audit table**; copy to production for filtering.  
8. **Ask product** explicitly: do `too_basic` terms ship? Write the answer in your RESULTS file.  
9. **Budget human time** for `REVIEW` + `fix_definition` only — that should be a few percent if prompts are good (oncology ended ~1% REVIEW on production keywords).  
10. **Hand CSVs back** to merge/upload; don’t upload half-scored tables to student-facing `articles`.

### When to change the design

| Change | Do it when… |
|--------|-------------|
| Add a 4th model | You have a documented failure mode 3 models keep missing |
| Drop Claude batches for Claude API | You have stable API quotas and don’t need per-batch debugging |
| Merge keyword + acronym prompts | You are sure failure modes are identical (usually they’re not) |
| Replace Supabase with local SQLite | You’re solo and never need a dashboard or multi-machine resume |
| Change tags | You have a new *workflow*, not just a new adjective |

### When *not* to change the design

- Because a new model is trendy  
- To make the folder structure look prettier without changing behavior  
- To eliminate the human `REVIEW` queue before you’ve run one full subject  

---

## 11. Glossary for new engineers

| Term | Meaning |
|------|---------|
| Pipeline A / B | Content generation (Wikipedia / abbreviations) |
| Pipeline C / D | QA (keywords / acronyms) |
| `action` | Majority tag — the operational decision |
| `flag` | Convenience boolean derived from `action` for “don’t show by default” |
| `REVIEW` | All three tags differed — human required |
| Audit table | Full scored set kept immutable |
| Production table | Filtered set used for export and fix loops |
| Ready for textbook | Policy-defined shippable set (oncology keywords: approved + supplementary + too_basic) |

---

## 12. Where to look in code for each decision

| Decision | Primary place |
|----------|----------------|
| Tag definitions + decision order | `10_keyword_setup/ensemble_pipeline_v2.py` → `PROMPT_TEMPLATE` |
| Acronym-specific rules | `21_acronym_setup/acronym_pipeline.py` + `23_acronym_claude/claude_acronym_prompt.md` |
| Majority / REVIEW / flag | `cmd_ensemble` in the keyword and acronym CLIs |
| Claude batch size | `13_claude_split/split_for_claude_v2.py` (`BATCH_SIZE = 500`) |
| Production filter copy | `18_production_export/prepare_production.py` |
| Fix-loop reset | `19_definition_fix_loop/update_fixed_definitions.py` |
| Final oncology policy + numbers | `RESULTS.md` |

---

If you remember only one thing: **generation creates candidates; QA decides fate; humans only handle the tiny disagreement and fix tails.** Everything in this repo is arranged to make that separation reliable at ~10K scale.
