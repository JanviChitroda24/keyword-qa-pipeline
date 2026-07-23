# Stage 11 — Keyword Score (API Models)

**Pipeline:** C (Keyword QA)  
**Script:** `run_pipeline.py` → `../10_keyword_setup/ensemble_pipeline_v2.py`  
**Models:** Mistral Small (`mistral-small-latest`), OpenAI (`gpt-4o-mini`)

## Purpose

Have two independent API judges score and tag every keyword before Claude runs. Uses the shared five-tag prompt embedded in `ensemble_pipeline_v2.py`.

## Prerequisites

- Stage 10 complete  
- `MISTRAL_API_KEY` and `OPENAI_API_KEY` in `.env`

## Commands

```bash
cd 11_keyword_score_api
python run_pipeline.py score --model mistral
python run_pipeline.py score --model openai
python run_pipeline.py score --model mistral --batch-size 5
python run_pipeline.py status
```

## Behavior

- Default batch size: 10 entries per API call  
- Skips rows already scored for that model (resumable)  
- Failed/unparseable batches land in `results_v2/debug_responses/`  
- Rate-limit pacing: ~2s (Mistral), ~1s (OpenAI) between batches

## Outputs

- `mistral_score`, `mistral_tag`, `mistral_issue`  
- `openai_score`, `openai_tag`, `openai_issue`  
- Next: **Stage 12** (`12_claude_export/`)

## Oncology reference

| Model | Scored | Avg score |
|-------|-------:|----------:|
| Mistral | 9,914 / 10,049 | 64.8 |
| OpenAI | 9,826 / 10,049 | 76.2 |

Raw averages differ by model; **tags** drive the final `action` at Stage 16.
