#!/usr/bin/env python3
"""
merge_claude_scores_v2.py — Merge all Claude Code scored batch CSVs into one file.

Looks for claude_batches_v2/batch_*_scored.csv and merges them.

Usage:
    python merge_claude_scores_v2.py
    python merge_claude_scores_v2.py --input-dir claude_batches_v2 --output claude_all_scored_v2.csv
"""

import argparse
import csv
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Merge Claude scored batch CSVs")
    parser.add_argument("--input-dir", default="claude_batches_v2",
                        help="Directory with batch_*_scored.csv files")
    parser.add_argument("--output", default="claude_all_scored_v2.csv",
                        help="Output merged CSV")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"ERROR: Directory not found: {input_dir}")
        sys.exit(1)

    # Find all scored files
    scored_files = sorted(input_dir.glob("batch_*_scored.csv"))
    if not scored_files:
        print(f"ERROR: No batch_*_scored.csv files found in {input_dir}")
        print(f"  Make sure Claude Code saved outputs as batch_001_scored.csv, etc.")
        sys.exit(1)

    print(f"Found {len(scored_files)} scored batch files:")
    all_rows = []
    expected_cols = {"slug", "claude_score", "claude_tag", "claude_issue"}

    for f in scored_files:
        with open(f, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        # Handle alternate column names from Claude
        if rows:
            cols = set(rows[0].keys())
            # Auto-remap common variations
            remap = {}
            for col in cols:
                lc = col.lower().strip()
                if lc == "score" and "claude_score" not in cols:
                    remap[col] = "claude_score"
                elif lc == "issue_tag" and "claude_tag" not in cols:
                    remap[col] = "claude_tag"
                elif lc in ("issue_detail", "issue") and "claude_issue" not in cols:
                    remap[col] = "claude_issue"

            if remap:
                remapped_rows = []
                for r in rows:
                    new_r = {}
                    for k, v in r.items():
                        new_r[remap.get(k, k)] = v
                    remapped_rows.append(new_r)
                rows = remapped_rows

        all_rows.extend(rows)
        print(f"  {f.name}: {len(rows)} rows")

    # Deduplicate by slug (keep last occurrence)
    seen = {}
    for r in all_rows:
        seen[r.get("slug", "")] = r
    deduped = list(seen.values())

    print(f"\nTotal: {len(all_rows)} rows ({len(deduped)} unique slugs)")

    # Write merged CSV
    output_path = Path(args.output)
    fieldnames = ["slug", "claude_score", "claude_tag", "claude_issue"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in deduped:
            writer.writerow({
                "slug":         r.get("slug", ""),
                "claude_score": r.get("claude_score", "-1"),
                "claude_tag":   r.get("claude_tag", ""),
                "claude_issue": r.get("claude_issue", ""),
            })

    # Quick stats
    scores = [int(r.get("claude_score", -1)) for r in deduped
              if str(r.get("claude_score", "")).lstrip("-").isdigit()]
    if scores:
        valid = [s for s in scores if s >= 0]
        print(f"\nScore stats ({len(valid)} valid):")
        print(f"  Avg: {sum(valid)/len(valid):.1f}")
        print(f"  Min: {min(valid)} | Max: {max(valid)}")
        print(f"  Below 70: {sum(1 for s in valid if s < 70)}")

    print(f"\nMerged CSV: {output_path}")
    print(f"\nNext: upload to Supabase:")
    print(f"  python ensemble_pipeline_v2.py import-claude --csv {output_path}")


if __name__ == "__main__":
    main()