# Stage 22 — Acronym Score (API Models)

**Pipeline:** D (Acronym QA)  
**Script:** `run_pipeline.py` → `../21_acronym_setup/acronym_pipeline.py`  
**Models:** Mistral Small, OpenAI GPT-4o-mini

## Purpose

Score and tag every acronym with the two API judges. Prompt emphasizes correct **expansion**, accurate definition, and broad-but-real textbook relevance (FDA/WHO/MRI yes; NATO no).

## Commands

```bash
cd 22_acronym_score_api
python run_pipeline.py score --model mistral
python run_pipeline.py score --model openai
python run_pipeline.py status
```

927 rows × batch size 10 ≈ 93 batches per model (~15–20 minutes each, rate-limit dependent).

## Outputs

- Mistral + OpenAI columns filled on `acronym_scores_v1`  
- Next: **Stage 23** (Claude)
