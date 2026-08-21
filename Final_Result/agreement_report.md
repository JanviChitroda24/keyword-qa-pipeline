# Inter-Rater Agreement Analysis

- **Source:** Supabase:keyword_scores_v2
- **Generated:** 2026-08-21 03:07 UTC
- **Items loaded:** 10049
- **Raters:** Mistral, OpenAI, Claude

- **Valid rows (all 3 models tagged):** 8967

## 1. Fleiss' Kappa

Chance-corrected multi-rater agreement.

| Metric | Value |
|--------|------:|
| κ (Fleiss) | 0.4884 |
| SE | 0.0019 |
| 95% CI | [0.4847, 0.4921] |
| P(observed) | 0.6599 |
| P(expected) | 0.3353 |
| N items | 8967 |
| n raters | 3 |
| k categories | 4 (approved, junk, supplementary, too_basic) |
| Landis & Koch | moderate |

### Category base rates (p_j)

| Category | p_j | % |
|----------|----:|--:|
| approved | 0.4496 | 45.0% |
| supplementary | 0.3295 | 33.0% |
| too_basic | 0.1194 | 11.9% |
| junk | 0.1015 | 10.2% |

## 2. Pairwise Cohen's Kappa

| Pair | κ (Cohen) | SE | P(obs) | Raw agree % | P(exp) |
|------|----------:|---:|-------:|------------:|-------:|
| Mistral vs Openai | 0.4251 | 0.0077 | 0.6196 | 62.0% | 0.3384 |
| Mistral vs Claude | 0.6559 | 0.0065 | 0.7607 | 76.1% | 0.3046 |
| Openai vs Claude | 0.4022 | 0.0077 | 0.5995 | 60.0% | 0.3301 |

## 3. Per-Category Agreement

| Category | 3/3 Agree | ≥2/3 Agree | Any Rater | Full % | Maj % |
|----------|----------:|-----------:|----------:|-------:|------:|
| approved | 2613 | 3708 | 5774 | 45.2% | 64.2% |
| supplementary | 913 | 2960 | 4990 | 18.3% | 59.3% |
| junk | 809 | 908 | 1013 | 79.9% | 89.6% |
| too_basic | 243 | 1021 | 1949 | 12.5% | 52.4% |

## 4. Majority-Vote Split Distribution (2/1 splits)

### Consensus breakdown

| Type | Count | % |
|------|------:|--:|
| Full agreement (3/3) | 4578 | 51.1% |
| Majority (2/1 split) | 4019 | 44.8% |
| Full disagreement | 370 | 4.1% |

### 2/1 Split types (majority → minority)

| Majority Tag | Dissent Tag | Count | % of splits |
|--------------|-------------|------:|------------:|
| supplementary | approved | 1547 | 38.5% |
| approved | supplementary | 1044 | 26.0% |
| too_basic | supplementary | 605 | 15.1% |
| supplementary | too_basic | 492 | 12.2% |
| too_basic | approved | 136 | 3.4% |
| junk | approved | 49 | 1.2% |
| approved | too_basic | 48 | 1.2% |
| too_basic | junk | 37 | 0.9% |
| junk | too_basic | 31 | 0.8% |
| junk | supplementary | 19 | 0.5% |
| supplementary | junk | 8 | 0.2% |
| approved | junk | 3 | 0.1% |

### Dissenter frequency

| Model | Dissents | % of 2/1 splits |
|-------|---------:|----------------:|
| Mistral | 798 | 19.9% |
| Openai | 2243 | 55.8% |
| Claude | 978 | 24.3% |

## 5. Per-Model Tag Distributions

| Tag | Mistral | Openai | Claude |
|-----|-------:|-------:|-------:|
| approved | 3244 (36.2%) | 5549 (61.9%) | 3302 (36.8%) |
| junk | 988 (11.0%) | 832 (9.3%) | 910 (10.1%) |
| supplementary | 3551 (39.6%) | 2249 (25.1%) | 3063 (34.2%) |
| too_basic | 1184 (13.2%) | 337 (3.8%) | 1692 (18.9%) |

## 6. Fleiss' Kappa by Subject Category (top 15)

| Subject Category | N | κ | 95% CI | Interpretation |
|------------------|----:|--:|--------|----------------|
| Molecular Biology | 1606 | 0.4926 | [0.4829, 0.5023] | moderate |
| Biochemistry | 1291 | 0.3816 | [0.3714, 0.3917] | fair |
| Cell Biology | 832 | 0.4010 | [0.3887, 0.4133] | fair |
| Oncology | 825 | 0.7776 | [0.7590, 0.7962] | substantial |
| Biotechnology | 819 | 0.3305 | [0.3182, 0.3427] | fair |
| Genetics | 502 | 0.4422 | [0.4248, 0.4597] | moderate |
| Immunology | 443 | 0.3953 | [0.3744, 0.4162] | fair |
| Pharmacology | 422 | 0.3205 | [0.3036, 0.3374] | fair |
| Nanotechnology | 334 | 0.4423 | [0.4202, 0.4643] | moderate |
| Diagnostics | 226 | 0.5476 | [0.5230, 0.5721] | moderate |
| Anatomy | 189 | 0.4190 | [0.3921, 0.4459] | moderate |
| Bioinformatics | 181 | 0.1113 | [0.0793, 0.1432] | slight |
| Biomedical Science | 111 | 0.5722 | [0.5404, 0.6040] | moderate |
| Toxicology | 103 | 0.3258 | [0.2942, 0.3574] | fair |
| Microbiology | 103 | 0.2646 | [0.2273, 0.3020] | fair |
