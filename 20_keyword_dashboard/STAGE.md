# Stage 20 — Keyword QA Dashboard

**Pipeline:** C (Keyword QA)  
**Files:** `keyword-qa-dashboard-v2.html`, `dashboard.html`

## Purpose

Browser UI for filtering and spot-checking scored keywords without writing SQL.

## Setup

1. Ensure Stage 10’s RLS policy allows `anon` SELECT on `keyword_scores_v2` (or production).  
2. Open `keyword-qa-dashboard-v2.html` in a browser.  
3. Enter Supabase project URL + **anon** key (not the service role key).

## Use for

- Triaging `REVIEW` rows (all three models disagreed on the tag)  
- Sampling `fix_definition` before sending to Pipeline A  
- Confirming `junk` / `too_basic` look correct  
- Searching by slug / term / category

## Files

| File | Notes |
|------|-------|
| `keyword-qa-dashboard-v2.html` | Primary V2 dashboard |
| `dashboard.html` | Alternate layout |

Do not commit real keys into these HTML files.
