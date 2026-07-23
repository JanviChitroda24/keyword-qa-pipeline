#!/usr/bin/env python3
"""
split_for_claude_v2.py — Split keywords CSV into batches for Claude Code.

Usage:
    python split_for_claude_v2.py results_v2/keywords_for_claude.csv
    python split_for_claude_v2.py results_v2/keywords_for_claude.csv --batch-size 300

Creates:
    claude_batches_v2/batch_001.csv
    claude_batches_v2/batch_002.csv
    ...
    claude_batches_v2/claude_scoring_prompt.md   (copy of the prompt to give Claude Code)
"""

import csv
import os
import sys
from pathlib import Path

BATCH_SIZE = 500

SCORING_PROMPT = """You are a scientific content reviewer for a cancer biology textbook used in a BACHELOR-LEVEL university course.
This textbook covers cancer biology, nanomedicine, biomedical science, and biotechnology.

Your job is to decide what happens to each keyword popup in the textbook. Students see these as clickable popups while reading — so each keyword must be USEFUL to a bachelor student studying cancer biology.

I'm giving you a CSV file with keyword entries (slug, term, category, definition). For each entry, assign ONE of these 5 tags:

  "approved"          — Directly relevant to cancer biology or the textbook topics. Term is correct, definition is accurate. SHOW this popup to students.
                        Examples: apoptosis, metastasis, oncogene, tumor suppressor, angiogenesis, chemotherapy

  "supplementary"     — NOT specifically about cancer, but a supporting science term a bachelor student may need a refresher on while reading. Term is correct, definition is accurate. SHOW this popup.
                        Examples: DNA, mitosis, pH, enzyme, protein, ribosome, amino acid, antibody

  "too_basic"         — Too elementary for bachelor-level students (they already know this), OR too irrelevant to the textbook content to justify a popup. Do NOT show.
                        Examples: water, cell, atom, human, brain, temperature, science, hospital

  "fix_definition"    — The term IS relevant and belongs in the textbook, but the definition is wrong, incomplete, broken, or is a disambiguation list ("X can refer to:"). Needs regeneration before showing.
                        Examples: a real cancer term with a Wikipedia disambiguation snippet, a truncated definition, factually incorrect explanation

  "junk"              — Not a real keyword. Wikipedia category pages ("categorynitrogen-cycle"), slugs with formatting artifacts, completely unrelated to science, or nonsense entries. DELETE.
                        Examples: categorynitrogen-cycle, list-of-chemistry-topics, random non-scientific text

DECISION RULES (follow in order):
  1. Is it junk or a formatting artifact? → "junk"
  2. Is the definition EMPTY or MISSING? If the term is valid and relevant, tag as "fix_definition" (it needs a definition written). If the term itself is junk or too basic, tag accordingly.
  3. Is the definition broken, wrong, or a disambiguation list? → "fix_definition"
  4. Is the term too basic for bachelor students OR completely irrelevant to the textbook? → "too_basic"
  5. Is it directly about cancer biology / nanomedicine / biotech / pharmacology? → "approved"
  6. Is it a valid science term that supports understanding of the textbook? → "supplementary"

Also score each entry 0-100 to indicate confidence:
  90-100: Perfect entry, no issues
  70-89:  Good, minor quibbles
  50-69:  Borderline — definition is okay but has issues
  30-49:  Significant problems
  0-29:   Junk or completely broken

EXAMPLES:
  slug=apoptosis        → claude_score=95, claude_tag=approved, claude_issue=none
  slug=dna              → claude_score=88, claude_tag=supplementary, claude_issue=none
  slug=water            → claude_score=30, claude_tag=too_basic, claude_issue=Too elementary for bachelor-level students
  slug=ctl              → claude_score=35, claude_tag=fix_definition, claude_issue=Definition is a disambiguation list
  slug=categorynitrogen → claude_score=5, claude_tag=junk, claude_issue=Wikipedia category page
  slug=antioxidant      → claude_score=82, claude_tag=supplementary, claude_issue=none
  slug=tumor-microenvironment → claude_score=94, claude_tag=approved, claude_issue=none
  slug=cell-cycle             → claude_score=40, claude_tag=fix_definition, claude_issue=No definition provided — term is relevant, needs definition generated

OUTPUT FORMAT: A CSV file with these exact columns: slug, claude_score, claude_tag, claude_issue
- slug: copied from input
- claude_score: integer 0-100
- claude_tag: one of: approved, supplementary, too_basic, fix_definition, junk
- claude_issue: brief explanation if there's an issue, "none" otherwise

Read the input CSV and produce the output CSV. Save it as batch_NNN_scored.csv (matching the input batch number).
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python split_for_claude_v2.py <input_csv> [--batch-size N]")
        sys.exit(1)

    input_file = sys.argv[1]
    batch_size = BATCH_SIZE

    # Parse --batch-size flag
    if "--batch-size" in sys.argv:
        idx = sys.argv.index("--batch-size")
        if idx + 1 < len(sys.argv):
            batch_size = int(sys.argv[idx + 1])

    output_dir = Path("claude_batches_v2")
    output_dir.mkdir(exist_ok=True)

    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total_batches = (len(rows) + batch_size - 1) // batch_size
    print(f"Total rows: {len(rows)}")
    print(f"Batch size: {batch_size}")
    print(f"Batches: {total_batches}")

    batch_num = 0
    for i in range(0, len(rows), batch_size):
        batch_num += 1
        batch = rows[i:i + batch_size]
        out_path = output_dir / f"batch_{batch_num:03d}.csv"

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["slug", "term", "category", "definition"])
            writer.writeheader()
            for row in batch:
                writer.writerow({
                    "slug":       row.get("slug", ""),
                    "term":       row.get("term", ""),
                    "category":   row.get("category", ""),
                    "definition": row.get("definition", ""),
                })

        print(f"  {out_path} — {len(batch)} rows")

    # Write the scoring prompt
    prompt_path = output_dir / "claude_scoring_prompt.md"
    prompt_path.write_text(SCORING_PROMPT, encoding="utf-8")
    print(f"\n  Scoring prompt: {prompt_path}")

    print(f"\nDone! {batch_num} batch files in {output_dir}/")
    print(f"\n{'='*60}")
    print(f"CLAUDE CODE INSTRUCTIONS:")
    print(f"{'='*60}")
    print(f"For each batch, run in Claude Code:")
    print(f"")
    print(f"  claude -p \"Read {output_dir}/claude_scoring_prompt.md for instructions.")
    print(f"    Score the keywords in {output_dir}/batch_001.csv")
    print(f"    Save output as {output_dir}/batch_001_scored.csv\"")
    print(f"")
    print(f"After all batches are scored, merge them:")
    print(f"  python merge_claude_scores_v2.py")
    print(f"")
    print(f"Then upload to Supabase:")
    print(f"  python ensemble_pipeline_v2.py import-claude --csv claude_all_scored_v2.csv")


if __name__ == "__main__":
    main()