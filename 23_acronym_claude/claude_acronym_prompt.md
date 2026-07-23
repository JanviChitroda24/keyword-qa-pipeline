# Claude Code Acronym Scoring Instructions

## What to do
Read the attached CSV file. For each acronym entry, verify it and output a new CSV file with your results.

## Context
These are acronym/abbreviation popup definitions for a cancer biology textbook titled "Cancer Biology: A Study of Cancer for the Upcoming AI Era." This is a BACHELOR-LEVEL university course covering cancer biology, nanomedicine, nanotechnology (biomedical applications), and biotechnology.

These acronyms were found by scanning the textbook for words with 2+ capital letters, cross-referencing them with an oncology database, and generating definitions via LLM. Your job is to VERIFY three things:

1. **EXPANSION** — Does the acronym expand to the correct full name?
2. **DEFINITION** — Is the definition factually accurate and useful?
3. **RELEVANCE** — Does this belong in a cancer biology textbook?

## Relevance is BROAD
The acronym does NOT need to be directly about cancer or genes. If a student reading a cancer biology textbook would benefit from knowing what it means, it's relevant:
- WHO (World Health Organization) → relevant (health policy context)
- FDA (Food and Drug Administration) → relevant (drug approvals)
- NIH (National Institutes of Health) → relevant (funds cancer research)
- MRI (Magnetic Resonance Imaging) → relevant (cancer diagnostics)
- PCR (Polymerase Chain Reaction) → relevant (lab technique)
- NATO → NOT relevant (no textbook connection)

## How to score

### First check for junk:
- If it's not a real acronym, random letters, or formatting noise → tag "junk"
- If the slug has wiki markup or formatting artifacts → tag "junk"

### Then check expansion and definition:
- If the acronym expands to the WRONG full name → tag "fix_definition"
- If the definition is factually wrong, misleading, or describes a different meaning → tag "fix_definition"
- If the definition has wiki markup artifacts ({{, [[, <ref>, [1]) → tag "fix_definition"

### Then evaluate relevance:
- Directly about cancer/oncology/nanomedicine/biotech/genetics/immunology/pharmacology → tag "approved"
- Indirectly relevant (organizations, general science tools, imaging, lab techniques) → tag "supplementary"
- Too common/basic or completely irrelevant to the textbook → tag "too_basic"

## Tags (assign exactly one):
- "approved" — correct expansion, accurate definition, directly relevant to cancer biology / nanomedicine / biotech
- "supplementary" — correct expansion, accurate definition, indirectly relevant (students benefit from knowing it)
- "fix_definition" — relevant acronym but wrong expansion, wrong definition, or describes wrong meaning
- "too_basic" — too common or completely irrelevant to cancer textbook
- "junk" — not a real acronym, noise, formatting artifact

## Scoring rubric (0-100):
- 90-100: Correct expansion, accurate definition, clearly relevant
- 70-89: Correct, minor issues
- 50-69: Expansion may be off, or definition has notable issues
- 30-49: Wrong expansion or mostly irrelevant
- 0-29: Junk or completely wrong

## Output format
Create a CSV file with these exact columns:
```
slug,claude_score,claude_tag,claude_issue
csc,95,approved,none
who,85,supplementary,none
vegf,95,approved,none
ai,75,fix_definition,AI commonly means Artificial Intelligence but defined as Aromatase Inhibitor without context
xyz,10,junk,Not a recognized acronym
dna,40,too_basic,Too common for bachelor students to need a popup
```

- slug: copied from input
- claude_score: integer 0-100
- claude_tag: one of: approved, supplementary, too_basic, fix_definition, junk
- claude_issue: brief explanation if there's an issue, "none" otherwise

Score EVERY row. Do not skip any.
