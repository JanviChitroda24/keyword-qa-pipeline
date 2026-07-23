# Claude Code Scoring Instructions

## What to do
Read the attached CSV file. For each keyword entry, score it and output a new CSV file with your results.

## Context
These are keyword popup definitions for a cancer biology textbook titled "Cancer Biology: A Study of Cancer for the Upcoming AI Era." This is a BACHELOR-LEVEL university course covering cancer biology, nanomedicine, nanotechnology (biomedical applications), and biotechnology. Students see these as clickable popups while reading — each keyword must be USEFUL to a bachelor student.

Some entries have EMPTY definitions (no definition was generated). Evaluate those based on the term and category alone.

## How to score each entry

### First check for junk:
- If the term starts with "Category:" or is a Wikipedia navigation/category page → tag "junk"
- If the definition begins with "X can refer to:" or is a disambiguation list with NO biomedical meaning → tag "junk"
- If the term is a book, film, biography, or non-scientific entity → tag "junk"
- If the slug has formatting artifacts (wiki markup like {{, [[, <ref>, [1], empty parentheses) → tag "junk"

### Then check for empty/broken definitions:
- If the definition is EMPTY or MISSING and the term IS relevant to the textbook → tag "fix_definition"
- If the definition is EMPTY and the term is junk or too basic → tag "junk" or "too_basic" accordingly
- If the definition has wiki markup artifacts, is truncated, or is factually wrong → tag "fix_definition"

### Then evaluate relevance and assign ONE of these 5 tags:

  "approved"          — Directly relevant to cancer biology, nanomedicine, biotech, or the textbook topics. Term is correct, definition is accurate. SHOW this popup to students.
                        Examples: apoptosis, metastasis, oncogene, tumor suppressor, angiogenesis, chemotherapy, nanoparticle, monoclonal antibody

  "supplementary"     — NOT specifically about cancer, but a supporting science term a bachelor student may need a refresher on while reading. Term is correct, definition is accurate. SHOW this popup.
                        Examples: DNA, mitosis, pH, enzyme, protein, ribosome, amino acid, antibody, antioxidant

  "too_basic"         — Too elementary for bachelor-level students (they already know this), OR too irrelevant to the textbook content to justify a popup. Do NOT show.
                        Examples: water, cell, atom, human, brain, temperature, science, hospital, book, geography terms

  "fix_definition"    — The term IS relevant and belongs in the textbook, but the definition is wrong, incomplete, broken, empty, or is a disambiguation list. Needs regeneration before showing.
                        Examples: a real cancer term with no definition, a Wikipedia disambiguation snippet, truncated text, factually incorrect explanation

  "junk"              — Not a real keyword. Wikipedia category pages, formatting artifacts, books/films/biographies, completely unrelated to science, nonsense entries. DELETE.
                        Examples: categorynitrogen-cycle, list-of-chemistry-topics, random non-scientific text

### Valid categories (for reference):
Anatomy, Biochemistry, Biomedical Science, Biotechnology, Cell Biology, Chemistry, Diagnostics, Genetics, Immunology, Molecular Biology, Nanomedicine, Nanotechnology, Oncology, Pharmacology

### Scoring rubric (0-100):
- 90-100: Relevant, accurate definition, correct category — perfect entry
- 70-89:  Mostly correct, minor issues
- 50-69:  Borderline — wrong category, incomplete definition, tangential relevance
- 30-49:  Significant problems — wrong definition, broken text, weak relevance
- 0-29:   Junk, off-topic, or completely broken

## Output format
Create a CSV file with these exact columns:
```
slug,claude_score,claude_tag,claude_issue
apoptosis,95,approved,none
dna,88,supplementary,none
water,30,too_basic,Too elementary for bachelor-level students
ctl,35,fix_definition,Definition is a disambiguation list
categorynitrogen-cycle,5,junk,Wikipedia category page
cell-cycle,40,fix_definition,No definition provided — term is relevant
tumor-microenvironment,94,approved,none
antioxidant,82,supplementary,none
```

- slug: copied from input
- claude_score: integer 0-100
- claude_tag: one of: approved, supplementary, too_basic, fix_definition, junk
- claude_issue: brief explanation if there's an issue, "none" otherwise

Name the output file: `batch_XXX_scored.csv` (matching the input batch number).

Score EVERY row. Do not skip any.