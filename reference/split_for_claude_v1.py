#!/usr/bin/env python3
"""
split_for_claude.py — Split keywords CSV into batches for Claude Code.

Usage:
    python split_for_claude.py keywords_for_claude.csv

Creates:
    claude_batches/batch_001.csv
    claude_batches/batch_002.csv
    ...
"""

import csv
import os
import sys
from pathlib import Path

BATCH_SIZE = 500

def main():
    if len(sys.argv) < 2:
        print("Usage: python split_for_claude.py <input_csv>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = Path("claude_batches")
    output_dir.mkdir(exist_ok=True)

    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Total rows: {len(rows)}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Batches: {(len(rows) + BATCH_SIZE - 1) // BATCH_SIZE}")

    batch_num = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch_num += 1
        batch = rows[i:i + BATCH_SIZE]
        out_path = output_dir / f"batch_{batch_num:03d}.csv"

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["slug", "term", "category", "definition"])
            writer.writeheader()
            for row in batch:
                writer.writerow({
                    "slug": row.get("slug", ""),
                    "term": row.get("term", ""),
                    "category": row.get("category", ""),
                    "definition": row.get("definition", ""),
                })

        print(f"  {out_path} — {len(batch)} rows")

    print(f"\nDone! {batch_num} batch files in {output_dir}/")
    print(f"\nNext: give each batch to Claude Code with the scoring prompt.")


if __name__ == "__main__":
    main()
