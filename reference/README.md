# Reference — Earlier Versions & Operator Notes

Material kept for history and debugging. **Not part of the numbered stage path.** Prefer stages `10_`–`25_` for new runs.

## Contents

| File | What it is |
|------|------------|
| `ensemble_pipeline_v1.py` | First ensemble prototype (Gemini / Mistral / Llama) scoring from live `articles` into `keyword_scores_test` |
| `ensemble_verify.py` | Early verification helper around the v1 approach |
| `split_for_claude_v1.py` | Pre-v2 Claude batch splitter |
| `upload_claude_scores.py` | Early Claude score uploader |
| `claude_scoring_prompt_v1.md` | First Claude keyword scoring prompt |
| `steps_keyword_v2.md` | Original operator checklist for keyword QA V2 (source for stages 10–17 docs) |
| `STEPS_ACRONYMS.md` | Original operator checklist for acronym QA (source for stages 21–25 docs) |
| `keyword-qa-dashboard-v1.html` | Older keyword dashboard |
| `keyword_dashboard_qa.html` | Alternate dashboard variant |
| `sample_for_review.py` | Stratified spot-check sampler against Supabase after upload |
| `export_all_keywords.py` | Utility to dump keywords from the app DB |

## Evolution (short)

1. **V1** — score a 50-row test slice from production `articles` with Gemini/Mistral/Llama  
2. **V2** — full regenerated JSONL (~10K), Mistral + OpenAI + Claude Code, five-tag system, `keyword_scores_v2`  
3. **Production handoff** — `prepare_production.py` + fix-definition loop  
4. **Acronym track** — same pattern on Pipeline B’s 927 abbreviations  

Use V2 + acronym stages going forward; keep V1 only if you need to understand older tables or dashboards.
