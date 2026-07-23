# Stage 25 — Acronym QA Dashboard

**Pipeline:** D (Acronym QA)  
**File:** `acronym-qa-dashboard.html`

## Purpose

Browser UI for reviewing acronym scores, tags, and ensemble actions on `acronym_scores_v1`.

## Setup

1. Stage 21 RLS policy must allow `anon` SELECT.  
2. Open `acronym-qa-dashboard.html` in a browser.  
3. Enter Supabase URL + **anon** key.

## Use for

- Catching wrong expansions (classic: `AI`)  
- Confirming org/tool acronyms tagged `supplementary` not `junk`  
- Clearing `REVIEW` disagreements before merge

Do not commit real keys into the HTML file.
