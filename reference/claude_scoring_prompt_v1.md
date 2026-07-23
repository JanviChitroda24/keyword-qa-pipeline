# Claude Code Scoring Instructions

## What to do
Read the attached CSV file. For each keyword entry, score it and output a new CSV file with your results.

## Context
These are keyword popup definitions for a cancer biology textbook titled "Cancer Biology: A Study of Cancer for the Upcoming AI Era." The textbook covers cancer biology, nanomedicine, nanotechnology (biomedical applications), and biotechnology.

## How to score each entry

### First check for junk:
- If the term starts with "Category:" or is a Wikipedia navigation page → score 0-10, tag "off_topic"
- If the definition begins with "X can refer to:" or is a disambiguation list → check if any meaning is biomedical. If no biomedical meaning → tag "off_topic"  
- If the term is a book, film, biography, or non-scientific entity → tag "off_topic"

### Evaluation criteria (in priority order):

1. **RELEVANCE** — Does this term belong in a cancer biology / nanomedicine / biotech textbook?
   - Must connect to cancer biology, nanomedicine, nanotechnology, biotechnology, or foundational sciences (cell biology, molecular biology, genetics, immunology, pharmacology, biochemistry, anatomy, chemistry, diagnostics)
   - Reject: books, biographies, geography, politics, sports, economics, pure physics with no biomedical link
   - When uncertain, lean toward including it

2. **DEFINITION ACCURACY** — Is it factually correct and useful for students?
   - Flag definitions that are wrong, misleading, or too vague
   - Flag broken text, wiki markup ({{, [[, <ref>, [1], pronunciation guides /.../, empty parentheses)

3. **CATEGORY CORRECTNESS** — Valid categories ONLY:
   Anatomy, Biochemistry, Biomedical Science, Biotechnology, Cell Biology, Chemistry, Diagnostics, Genetics, Immunology, Molecular Biology, Nanomedicine, Nanotechnology, Oncology, Pharmacology

### Scoring rubric:
- 90-100: Relevant, accurate definition, correct category
- 75-89: Mostly correct, minor issues
- 50-74: Problems — wrong category, incomplete definition, borderline relevance
- 25-49: Serious issues — wrong definition, broken markup, weak relevance
- 0-24: Should not be in textbook — off-topic, wrong, gibberish

### Issue tags (assign exactly one):
- "none" — no issues
- "incorrect_term" — term doesn't exist or is a disambiguation page
- "incorrect_definition" — definition is wrong, broken, or has wiki artifacts
- "incorrect_category" — wrong category (suggest correct one in issue column)
- "low_relevance" — real term but too tangential for cancer biology
- "off_topic" — not biomedical at all

## Output format
Create a CSV file with these columns:
```
slug,claude_score,claude_tag,claude_issue
antigen,95,none,none
categorynitrogen-cycle,10,off_topic,Wikipedia category page not a real term
```

Name the output file: `batch_XXX_scored.csv` (matching the input batch number).

Score EVERY row. Do not skip any.
