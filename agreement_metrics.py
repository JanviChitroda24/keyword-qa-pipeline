#!/usr/bin/env python3
"""
Medhavi Keyword QA — Inter-Rater Agreement Metrics
====================================================

WHAT
----
Computes how often three LLM reviewers (Mistral, OpenAI, Claude) agree when
tagging keyword definitions. Reports:

  • Fleiss' kappa (+ 95% CI)     — multi-rater chance-corrected agreement
  • Pairwise Cohen's kappa      — agreement between each pair of models
  • Per-category agreement      — which tags (approved, junk, …) are stable
  • 2/1 split-type distributions — what the majority vs dissenter chose
  • Per-model tag distributions — bias / leniency differences across models
  • Fleiss' kappa by subject    — agreement within Oncology, Immunology, etc.

WHY
---
Shipping keywords should reflect reliable multi-model consensus, not a single
model's quirks. These metrics quantify that reliability for papers, QA
dashboards, and decisions about which items need human review.

HOW
---
1. Load rows that include each model's tag (or fall back to consensus-only JSONL).
2. Build a ratings matrix: for each keyword, count how many raters chose each tag.
3. Feed that matrix into Fleiss / Cohen formulas (stdlib only — no scipy needed).
4. Write a Markdown report to disk (default: Final_Result/agreement_report.md).

Usage
-----
  Run from keyword-qa-pipeline/ (this repo).

  MODE 1 — From Supabase audit tables (full per-model data):
    # QA_SUPABASE_* already used by this repo's .env / stages 10–18
    export QA_SUPABASE_URL=https://xxx.supabase.co
    export QA_SUPABASE_KEY=eyJ...   # service_role
    python agreement_metrics.py --supabase
    python agreement_metrics.py --supabase keyword_scores_v2

  MODE 2 — From local JSONL shipping files (consensus fields only unless tags exist):
    python agreement_metrics.py --jsonl Final_Result/keywords_combined.jsonl
    python agreement_metrics.py --jsonl Final_Result/keywords_combined.jsonl --out Final_Result/my_report.md

  MODE 3 — From local CSV export of the audit table (needs per-model columns):
    python agreement_metrics.py --csv keyword_scores_v2_export.csv

  MODE 4 — Synthetic demo (verify math without real data):
    python agreement_metrics.py --demo

  Optional for all modes:
    --out <path.md>   Write report here (default: Final_Result/agreement_report.md)

Environment (for --supabase only):
    QA_SUPABASE_URL=https://xxx.supabase.co
    QA_SUPABASE_KEY=eyJ...  (service_role)
"""

import json
import csv
import sys
import os
import math
from datetime import datetime, timezone
from collections import Counter, defaultdict
from pathlib import Path

# Default Markdown report path (WHAT: where results land if --out is omitted)
# WHY: next to the shipping JSONL under Final_Result/ for easy findability
DEFAULT_OUT_PATH = os.path.join("Final_Result", "agreement_report.md")


def load_dotenv():
    """
    WHAT: Load KEY=VALUE pairs from .env into os.environ (stdlib only).
    WHY:  --supabase needs QA_SUPABASE_URL / QA_SUPABASE_KEY; other QA scripts
          already read these from .env — this script should too.
    HOW:  Prefer .env next to this file, then cwd/.env. Do not overwrite
          vars already set in the shell.
    """
    for p in [Path(__file__).resolve().parent / ".env", Path.cwd() / ".env"]:
        if not p.is_file():
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        return


load_dotenv()

# ── Tag / model constants ─────────────────────────────────────────────
# WHAT: Canonical review tags and which ones mean "show this keyword in UI".
# WHY:  Analysis must use one vocabulary so kappa is comparable across runs.
# HOW:  Rows whose tags are outside VALID_TAGS are dropped before scoring.
VALID_TAGS = ["approved", "supplementary", "too_basic", "false_definition", "junk"]
SHOW_TAGS = {"approved", "supplementary", "too_basic"}
MODELS = ["mistral", "openai", "claude"]
MODEL_TAG_COLS = {
    "mistral": "mistral_tag",
    "openai": "openai_tag",
    "claude": "claude_tag",
}
MODEL_SCORE_COLS = {
    "mistral": "mistral_score",
    "openai": "openai_score",
    "claude": "claude_score",
}


# ══════════════════════════════════════════════════════════════════════
#  CORE STATISTICS
# ══════════════════════════════════════════════════════════════════════

def fleiss_kappa(ratings_matrix, categories):
    """
    Compute Fleiss' kappa for n raters on categorical labels.

    WHAT
        Chance-corrected agreement for >2 raters on the same items/categories.

    WHY
        Raw % agreement looks high when one tag dominates (e.g. mostly
        "approved"). Kappa subtracts agreement expected by chance.

    HOW
        ratings_matrix: list of dicts, one per item.
            Each dict maps category -> count of raters who chose it.
            Example for 3 raters: {"approved": 2, "junk": 1}
        categories: list of all possible category labels.

        Steps:
          1. For each item i, compute P_i = agreement among its n raters.
          2. P_bar = mean(P_i)          → observed agreement
          3. p_j   = overall share of category j across all assignments
          4. P_e   = sum(p_j^2)         → chance agreement
          5. κ     = (P_bar - P_e) / (1 - P_e)
          6. SE from Fleiss (1971) large-sample approx → 95% CI

    Returns
        dict with kappa, se, ci_95_*, P_observed, P_expected, N, n_raters, …
    """
    N = len(ratings_matrix)  # number of items (keywords)
    n = sum(ratings_matrix[0].values())  # raters per item (expect 3)
    k = len(categories)

    # P_i: pairwise agreement among raters on item i
    P_i_list = []
    for row in ratings_matrix:
        sum_sq = sum(row.get(c, 0) ** 2 for c in categories)
        # (sum n_ij^2 - n) / (n(n-1)) is the fraction of rater-pairs that match
        P_i = (sum_sq - n) / (n * (n - 1)) if n > 1 else 1.0
        P_i_list.append(P_i)

    P_bar = sum(P_i_list) / N  # mean observed agreement

    # p_j: proportion of all assignments that landed in category j
    p_j = {}
    total_assignments = N * n
    for c in categories:
        p_j[c] = sum(row.get(c, 0) for row in ratings_matrix) / total_assignments

    P_e = sum(pj ** 2 for pj in p_j.values())  # expected agreement by chance

    kappa = (P_bar - P_e) / (1 - P_e) if P_e < 1 else 1.0

    # Standard error (Fleiss 1971 large-sample approximation)
    se = (
        math.sqrt(
            2
            * (P_e - sum(pj ** 3 for pj in p_j.values())) ** 2
            / (N * n * (n - 1) * (1 - P_e) ** 2)
        )
        if N > 0 and P_e < 1
        else 0
    )

    ci_lower = kappa - 1.96 * se
    ci_upper = kappa + 1.96 * se

    return {
        "kappa": round(kappa, 4),
        "se": round(se, 4),
        "ci_95_lower": round(ci_lower, 4),
        "ci_95_upper": round(ci_upper, 4),
        "P_observed": round(P_bar, 4),
        "P_expected": round(P_e, 4),
        "N": N,
        "n_raters": n,
        "k_categories": k,
        "p_j": {c: round(v, 4) for c, v in sorted(p_j.items(), key=lambda x: -x[1])},
    }


def cohen_kappa(rater_a, rater_b, categories):
    """
    Compute Cohen's kappa between two raters.

    WHAT
        Chance-corrected agreement for exactly two raters.

    WHY
        Pairwise kappas show *which* models disagree (e.g. Mistral vs Claude
        may be weaker than OpenAI vs Claude).

    HOW
        rater_a, rater_b: parallel lists of category labels (same length).
          P_o = fraction of items where labels match
          P_e = sum over categories of (row_marginal * col_marginal) / n^2
          κ   = (P_o - P_e) / (1 - P_e)

    Returns
        dict with kappa, se, P_observed, P_expected, n
    """
    assert len(rater_a) == len(rater_b)
    n = len(rater_a)

    # Confusion matrix kept for potential future detailed reporting
    confusion = defaultdict(lambda: defaultdict(int))
    for a, b in zip(rater_a, rater_b):
        confusion[a][b] += 1

    row_totals = Counter(rater_a)
    col_totals = Counter(rater_b)

    P_o = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    P_e = sum(row_totals.get(c, 0) * col_totals.get(c, 0) for c in categories) / (n ** 2)

    kappa = (P_o - P_e) / (1 - P_e) if P_e < 1 else 1.0

    # SE (Cohen 1960 simple approximation)
    se = math.sqrt(P_o * (1 - P_o) / (n * (1 - P_e) ** 2)) if P_e < 1 else 0

    return {
        "kappa": round(kappa, 4),
        "se": round(se, 4),
        "P_observed": round(P_o, 4),
        "P_expected": round(P_e, 4),
        "n": n,
    }


def per_category_agreement(ratings_matrix, categories):
    """
    Per-tag agreement breakdown.

    WHAT
        For each tag, how often all 3 raters (or ≥2) chose that tag when it
        appeared at all.

    WHY
        Overall kappa can hide that "junk" is rare but highly agreed, while
        "supplementary" vs "approved" is noisier.

    HOW
        full_agree  = items where all n raters chose `cat`
        majority    = items where ≥2 raters chose `cat`
        rates are relative to items where at least one rater chose `cat`
    """
    n_raters = sum(ratings_matrix[0].values())
    results = {}

    for cat in categories:
        items_with_cat = [row for row in ratings_matrix if row.get(cat, 0) > 0]
        if not items_with_cat:
            continue

        full_agree = sum(1 for row in ratings_matrix if row.get(cat, 0) == n_raters)
        majority = sum(1 for row in ratings_matrix if row.get(cat, 0) >= 2)

        results[cat] = {
            "full_agree_count": full_agree,
            "majority_count": majority,
            "any_rater_count": len(items_with_cat),
            "total_assignments": sum(row.get(cat, 0) for row in ratings_matrix),
            "full_agree_rate": round(full_agree / len(items_with_cat), 4),
            "majority_rate": round(majority / len(items_with_cat), 4),
        }

    return results


def split_type_distribution(model_tags_per_item):
    """
    Classify 2/1 majority-vote disagreements.

    WHAT
        Among items that are not unanimous, count (majority_tag, minority_tag)
        pairs, plus full 3-way disagreements.

    WHY
        Shows the *shape* of disagreement (e.g. approved vs supplementary is
        common; approved vs junk is rare and more concerning).

    HOW
        model_tags_per_item: list of [tag_mistral, tag_openai, tag_claude]
        - 1 unique tag  → skip (full agreement)
        - 2 unique tags → 2/1 split → count (majority, minority)
        - 3 unique tags → count as ("DISAGREE", "all_differ")
    """
    splits = Counter()

    for tags in model_tags_per_item:
        tag_counts = Counter(tags)
        if len(tag_counts) == 1:
            continue  # full agreement
        if len(tag_counts) == 3:
            splits[("DISAGREE", "all_differ")] += 1
            continue

        # Exactly 2 unique tags → 2/1 split
        majority_tag = tag_counts.most_common(1)[0][0]
        minority_tag = [t for t in tags if t != majority_tag][0]
        splits[(majority_tag, minority_tag)] += 1

    return splits


# ══════════════════════════════════════════════════════════════════════
#  DATA LOADERS
# ══════════════════════════════════════════════════════════════════════

def load_from_supabase(table="keyword_scores_v2", limit=None):
    """
    Load per-model scores from a Supabase audit table.

    WHAT
        Paginated REST fetch of rows where all three models have tags.

    WHY
        Audit tables hold the raw per-model tags needed for Fleiss/Cohen;
        shipping JSONL often only keeps consensus aggregates.

    HOW
        Requires QA_SUPABASE_URL + QA_SUPABASE_KEY (from .env or the shell).
        Uses PostgREST with offset paging (1000 rows/page). Stdlib urllib only.
    """
    import urllib.request

    url = os.environ.get("QA_SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("QA_SUPABASE_KEY", "")
    if not url or not key:
        print(
            "ERROR: Missing QA_SUPABASE_URL or QA_SUPABASE_KEY.\n"
            "  Put them in .env (see .env.example) or export them in your shell."
        )
        sys.exit(1)

    select_cols = (
        "slug,category,mistral_tag,openai_tag,claude_tag,"
        "mistral_score,openai_score,claude_score,action,tag_consensus"
    )
    endpoint = f"{url}/rest/v1/{table}?select={select_cols}"

    # Only rows where all 3 models have scored
    endpoint += "&mistral_tag=not.is.null&openai_tag=not.is.null&claude_tag=not.is.null"
    endpoint += "&order=slug"
    if limit:
        endpoint += f"&limit={limit}"

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    all_rows = []
    offset = 0
    page_size = 1000

    while True:
        page_url = endpoint + f"&offset={offset}&limit={page_size}"
        req = urllib.request.Request(page_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            batch = json.loads(resp.read().decode())
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        if limit and len(all_rows) >= limit:
            break

    print(f"Loaded {len(all_rows)} rows from {table}")
    return all_rows


def load_from_csv(path):
    """
    Load from a CSV export of the audit table.

    WHAT
        DictReader rows with normalized lowercase column names.

    WHY
        Lets you run full kappa offline after exporting from Supabase/Sheets.

    HOW
        Expects columns: mistral_tag, openai_tag, claude_tag (and ideally category).
    """
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized = {}
            for k, v in row.items():
                normalized[k.strip().lower()] = v.strip() if v else ""
            rows.append(normalized)
    print(f"Loaded {len(rows)} rows from {path}")
    return rows


def load_from_jsonl(path):
    """
    Load from a JSONL shipping file (e.g. Final_Result/keywords_combined.jsonl).

    WHAT
        One JSON object per line (keyword records).

    WHY
        Shipping files are always available locally; useful for consensus /
        action distributions even when per-model tags were stripped.

    HOW
        If mistral_tag / openai_tag / claude_tag are present → full analysis.
        Otherwise → limited consensus/action report only (no Fleiss/Cohen).
    """
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    print(f"Loaded {len(rows)} rows from {path}")
    return rows


# ══════════════════════════════════════════════════════════════════════
#  REPORT HELPERS
# ══════════════════════════════════════════════════════════════════════

def _landis_koch(kappa):
    """Map kappa to Landis & Koch (1977) verbal bands for report readability."""
    if kappa >= 0.81:
        return "almost perfect"
    if kappa >= 0.61:
        return "substantial"
    if kappa >= 0.41:
        return "moderate"
    if kappa >= 0.21:
        return "fair"
    if kappa >= 0.0:
        return "slight"
    return "poor (below chance)"


def write_markdown_report(path, content):
    """
    WHAT: Persist the analysis as a Markdown file.
    WHY:  Reports should be shareable / versionable, not only terminal scrollback.
    HOW:  Create parent dirs if needed, write UTF-8, print the path to stdout.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
        if not content.endswith("\n"):
            f.write("\n")
    print(f"Wrote report → {path}")


def parse_cli_args(argv):
    """
    WHAT: Parse mode + optional --out from argv (after script name).
    WHY:  Keep CLI simple without adding argparse dependency complexity.
    HOW:  mode is argv[0]; positional path/table is next non-flag; --out takes next arg.
    """
    if not argv:
        return None, None, DEFAULT_OUT_PATH

    mode = argv[0]
    out_path = DEFAULT_OUT_PATH
    positional = None
    i = 1
    while i < len(argv):
        if argv[i] == "--out":
            if i + 1 >= len(argv):
                print("ERROR: --out requires a path.md argument")
                sys.exit(1)
            out_path = argv[i + 1]
            i += 2
        elif argv[i].startswith("-"):
            print(f"Unknown flag: {argv[i]}")
            sys.exit(1)
        else:
            positional = argv[i]
            i += 1
    return mode, positional, out_path


# ══════════════════════════════════════════════════════════════════════
#  MAIN ANALYSIS FUNCTIONS (build Markdown, then write via CLI)
# ══════════════════════════════════════════════════════════════════════

def analyze_full(rows, source_label="audit table"):
    """
    Full analysis when per-model tags are available.

    WHAT
        End-to-end Markdown report: Fleiss, Cohen pairs, category agreement,
        splits, per-model distributions, and per-subject kappa.

    WHY
        This is the primary QA deliverable when audit data exists.

    HOW
        1. Keep rows where all 3 tags ∈ VALID_TAGS
        2. Build ratings_matrix + model_tags_list
        3. Run sections 1–6 into a Markdown string
        4. Return (markdown, metrics_dict) for the CLI to write to disk
    """
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append("# Inter-Rater Agreement Analysis")
    lines.append("")
    lines.append(f"- **Source:** {source_label}")
    lines.append(f"- **Generated:** {now}")
    lines.append(f"- **Items loaded:** {len(rows)}")
    lines.append("- **Raters:** Mistral, OpenAI, Claude")
    lines.append("")

    # Filter to rows where all 3 models have valid tags
    valid_rows = []
    for r in rows:
        mt = r.get("mistral_tag", "").strip().lower()
        ot = r.get("openai_tag", "").strip().lower()
        ct = r.get("claude_tag", "").strip().lower()
        if mt in VALID_TAGS and ot in VALID_TAGS and ct in VALID_TAGS:
            valid_rows.append(r)

    if not valid_rows:
        lines.append("## Error")
        lines.append("")
        lines.append("No rows with valid per-model tags found.")
        keys = list(rows[0].keys()) if rows else []
        lines.append(f"Available keys: `{keys}`")
        return "\n".join(lines) + "\n", None

    lines.append(f"- **Valid rows (all 3 models tagged):** {len(valid_rows)}")
    lines.append("")

    ratings_matrix = []
    model_tags_list = []
    categories_seen = set()

    for r in valid_rows:
        tags = [
            r["mistral_tag"].strip().lower(),
            r["openai_tag"].strip().lower(),
            r["claude_tag"].strip().lower(),
        ]
        model_tags_list.append(tags)
        counts = Counter(tags)
        ratings_matrix.append(dict(counts))
        categories_seen.update(tags)

    categories = sorted(categories_seen)

    # ── 1. Fleiss' Kappa ─────────────────────────────────────────────
    fk = fleiss_kappa(ratings_matrix, categories)
    lines.append("## 1. Fleiss' Kappa")
    lines.append("")
    lines.append("Chance-corrected multi-rater agreement.")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|------:|")
    lines.append(f"| κ (Fleiss) | {fk['kappa']:.4f} |")
    lines.append(f"| SE | {fk['se']:.4f} |")
    lines.append(f"| 95% CI | [{fk['ci_95_lower']:.4f}, {fk['ci_95_upper']:.4f}] |")
    lines.append(f"| P(observed) | {fk['P_observed']:.4f} |")
    lines.append(f"| P(expected) | {fk['P_expected']:.4f} |")
    lines.append(f"| N items | {fk['N']} |")
    lines.append(f"| n raters | {fk['n_raters']} |")
    lines.append(f"| k categories | {fk['k_categories']} ({', '.join(categories)}) |")
    lines.append(f"| Landis & Koch | {_landis_koch(fk['kappa'])} |")
    lines.append("")
    lines.append("### Category base rates (p_j)")
    lines.append("")
    lines.append("| Category | p_j | % |")
    lines.append("|----------|----:|--:|")
    for cat, pj in fk["p_j"].items():
        lines.append(f"| {cat} | {pj:.4f} | {pj * 100:.1f}% |")
    lines.append("")

    # ── 2. Pairwise Cohen's Kappa ────────────────────────────────────
    pairs = [("mistral", "openai"), ("mistral", "claude"), ("openai", "claude")]
    pair_col = MODEL_TAG_COLS
    cohen_results = {}

    lines.append("## 2. Pairwise Cohen's Kappa")
    lines.append("")
    lines.append("| Pair | κ (Cohen) | SE | P(obs) | Raw agree % | P(exp) |")
    lines.append("|------|----------:|---:|-------:|------------:|-------:|")
    for a_name, b_name in pairs:
        rater_a = [r[pair_col[a_name]].strip().lower() for r in valid_rows]
        rater_b = [r[pair_col[b_name]].strip().lower() for r in valid_rows]
        ck = cohen_kappa(rater_a, rater_b, categories)
        cohen_results[(a_name, b_name)] = ck
        lines.append(
            f"| {a_name.title()} vs {b_name.title()} | {ck['kappa']:.4f} | "
            f"{ck['se']:.4f} | {ck['P_observed']:.4f} | "
            f"{ck['P_observed'] * 100:.1f}% | {ck['P_expected']:.4f} |"
        )
    lines.append("")

    # ── 3. Per-Category Agreement ────────────────────────────────────
    pca = per_category_agreement(ratings_matrix, categories)
    lines.append("## 3. Per-Category Agreement")
    lines.append("")
    lines.append("| Category | 3/3 Agree | ≥2/3 Agree | Any Rater | Full % | Maj % |")
    lines.append("|----------|----------:|-----------:|----------:|-------:|------:|")
    for cat in sorted(pca.keys(), key=lambda c: -pca[c]["full_agree_count"]):
        p = pca[cat]
        lines.append(
            f"| {cat} | {p['full_agree_count']} | {p['majority_count']} | "
            f"{p['any_rater_count']} | {p['full_agree_rate'] * 100:.1f}% | "
            f"{p['majority_rate'] * 100:.1f}% |"
        )
    lines.append("")

    # ── 4. 2/1 Split-Type Distribution ───────────────────────────────
    splits = split_type_distribution(model_tags_list)
    full_agree = sum(1 for tags in model_tags_list if len(set(tags)) == 1)
    majority_2_1 = sum(1 for tags in model_tags_list if len(set(tags)) == 2)
    full_disagree = sum(1 for tags in model_tags_list if len(set(tags)) == 3)
    n_valid = len(valid_rows)

    lines.append("## 4. Majority-Vote Split Distribution (2/1 splits)")
    lines.append("")
    lines.append("### Consensus breakdown")
    lines.append("")
    lines.append("| Type | Count | % |")
    lines.append("|------|------:|--:|")
    lines.append(
        f"| Full agreement (3/3) | {full_agree} | {full_agree / n_valid * 100:.1f}% |"
    )
    lines.append(
        f"| Majority (2/1 split) | {majority_2_1} | {majority_2_1 / n_valid * 100:.1f}% |"
    )
    lines.append(
        f"| Full disagreement | {full_disagree} | {full_disagree / n_valid * 100:.1f}% |"
    )
    lines.append("")
    lines.append("### 2/1 Split types (majority → minority)")
    lines.append("")
    lines.append("| Majority Tag | Dissent Tag | Count | % of splits |")
    lines.append("|--------------|-------------|------:|------------:|")
    for (maj, minor), count in sorted(splits.items(), key=lambda x: -x[1]):
        if maj == "DISAGREE":
            continue
        pct = count / majority_2_1 * 100 if majority_2_1 > 0 else 0
        lines.append(f"| {maj} | {minor} | {count} | {pct:.1f}% |")
    lines.append("")

    dissent_counts = Counter()
    for tags in model_tags_list:
        if len(set(tags)) != 2:
            continue
        tag_counts = Counter(tags)
        majority_tag = tag_counts.most_common(1)[0][0]
        for i, model in enumerate(MODELS):
            if tags[i] != majority_tag:
                dissent_counts[model] += 1

    lines.append("### Dissenter frequency")
    lines.append("")
    lines.append("| Model | Dissents | % of 2/1 splits |")
    lines.append("|-------|---------:|----------------:|")
    for model in MODELS:
        c = dissent_counts[model]
        pct = c / majority_2_1 * 100 if majority_2_1 > 0 else 0
        lines.append(f"| {model.title()} | {c} | {pct:.1f}% |")
    lines.append("")

    # ── 5. Per-Model Tag Distributions ───────────────────────────────
    model_tag_counts = {}
    for m_idx, m in enumerate(MODELS):
        model_tag_counts[m] = Counter(tags[m_idx] for tags in model_tags_list)

    lines.append("## 5. Per-Model Tag Distributions")
    lines.append("")
    header = "| Tag | " + " | ".join(m.title() for m in MODELS) + " |"
    sep = "|-----|" + "|".join(["-------:"] * len(MODELS)) + "|"
    lines.append(header)
    lines.append(sep)
    for cat in categories:
        cells = [cat]
        for m in MODELS:
            c = model_tag_counts[m].get(cat, 0)
            pct = c / n_valid * 100
            cells.append(f"{c} ({pct:.1f}%)")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # ── 6. Per-Subject-Category Kappa ────────────────────────────────
    cat_field = "category"
    subject_cats = Counter(r.get(cat_field, "unknown").strip() for r in valid_rows)

    lines.append("## 6. Fleiss' Kappa by Subject Category (top 15)")
    lines.append("")
    lines.append("| Subject Category | N | κ | 95% CI | Interpretation |")
    lines.append("|------------------|----:|--:|--------|----------------|")

    for subject, cnt in subject_cats.most_common(15):
        sub_rows = [r for r in valid_rows if r.get(cat_field, "").strip() == subject]
        sub_matrix = []
        for r in sub_rows:
            tags = [
                r["mistral_tag"].strip().lower(),
                r["openai_tag"].strip().lower(),
                r["claude_tag"].strip().lower(),
            ]
            sub_matrix.append(dict(Counter(tags)))

        sub_cats = set()
        for rm in sub_matrix:
            sub_cats.update(rm.keys())
        sub_cats = sorted(sub_cats)

        if len(sub_matrix) < 5:
            lines.append(f"| {subject} | {cnt} | (n<5) | — | — |")
            continue

        sfk = fleiss_kappa(sub_matrix, sub_cats)
        sk = sfk["kappa"]
        si = _landis_koch(sk).replace(" (below chance)", "")
        lines.append(
            f"| {subject} | {cnt} | {sk:.4f} | "
            f"[{sfk['ci_95_lower']:.4f}, {sfk['ci_95_upper']:.4f}] | {si} |"
        )
    lines.append("")

    metrics = {
        "fleiss": fk,
        "cohen_pairwise": cohen_results,
        "per_category": pca,
        "splits": dict(splits),
        "full_agree": full_agree,
        "majority_2_1": majority_2_1,
        "full_disagree": full_disagree,
    }
    return "\n".join(lines), metrics


def analyze_jsonl_limited(rows, source_label="shipping file"):
    """
    Limited analysis from JSONL shipping files without per-model tags.

    WHAT
        Consensus / action / cross-tab / per-subject agree rates as Markdown.

    WHY
        keywords_combined.jsonl typically has _review_consensus and
        _review_action but not mistral_tag / openai_tag / claude_tag.
        Still useful for shipment QA; not a substitute for kappa.

    HOW
        Count fields, build Markdown tables, return markdown string for --out.
    """
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append("# Agreement Analysis (Limited)")
    lines.append("")
    lines.append(f"- **Source:** {source_label}")
    lines.append(f"- **Generated:** {now}")
    lines.append("")
    lines.append(
        "> **Note:** Per-model tags are not in this file. Fleiss/Cohen kappa "
        "require the Supabase audit table or a CSV export with "
        "`mistral_tag`, `openai_tag`, `claude_tag` columns."
    )
    lines.append("")

    consensus_counts = Counter(r.get("_review_consensus", "unknown") for r in rows)
    action_counts = Counter(r.get("_review_action", "unknown") for r in rows)
    total = len(rows)

    lines.append(f"- **Total items:** {total}")
    lines.append("")

    lines.append("## Consensus distribution")
    lines.append("")
    lines.append("| Consensus | Count | % |")
    lines.append("|-----------|------:|--:|")
    for c, n in consensus_counts.most_common():
        lines.append(f"| {c} | {n} | {n / total * 100:.1f}% |")
    lines.append("")

    lines.append("## Action distribution")
    lines.append("")
    lines.append("| Action | Count | % |")
    lines.append("|--------|------:|--:|")
    for a, n in action_counts.most_common():
        lines.append(f"| {a} | {n} | {n / total * 100:.1f}% |")
    lines.append("")

    lines.append("## Action × Consensus")
    lines.append("")
    lines.append("| Action | AGREE | MAJORITY | Other |")
    lines.append("|--------|------:|---------:|------:|")
    for action in sorted(action_counts.keys()):
        ag = sum(
            1
            for r in rows
            if r.get("_review_action") == action and r.get("_review_consensus") == "AGREE"
        )
        mj = sum(
            1
            for r in rows
            if r.get("_review_action") == action
            and r.get("_review_consensus") == "MAJORITY"
        )
        ot = sum(
            1
            for r in rows
            if r.get("_review_action") == action
            and r.get("_review_consensus") not in ("AGREE", "MAJORITY")
        )
        lines.append(f"| {action} | {ag} | {mj} | {ot} |")
    lines.append("")

    cat_consensus = defaultdict(lambda: {"AGREE": 0, "MAJORITY": 0, "other": 0, "total": 0})
    for r in rows:
        cat = r.get("category", "unknown")
        cons = r.get("_review_consensus", "other")
        cat_consensus[cat]["total"] += 1
        if cons in ("AGREE", "MAJORITY"):
            cat_consensus[cat][cons] += 1
        else:
            cat_consensus[cat]["other"] += 1

    lines.append("## Consensus by Subject Category (top 15)")
    lines.append("")
    lines.append("| Category | Total | AGREE | MAJ | Agree % |")
    lines.append("|----------|------:|------:|----:|--------:|")
    for cat in sorted(cat_consensus.keys(), key=lambda c: -cat_consensus[c]["total"])[:15]:
        cc = cat_consensus[cat]
        pct = cc["AGREE"] / cc["total"] * 100 if cc["total"] > 0 else 0
        lines.append(
            f"| {cat} | {cc['total']} | {cc['AGREE']} | {cc['MAJORITY']} | {pct:.1f}% |"
        )
    lines.append("")
    lines.append(
        "> To compute Fleiss' kappa, Cohen's kappa, and split-type analysis, "
        "run with `--supabase` or `--csv` using the audit table export."
    )
    lines.append("")

    return "\n".join(lines), None


# ══════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # HOW: mode + optional path/table + optional --out path.md
    mode, positional, out_path = parse_cli_args(sys.argv[1:])

    if mode is None:
        print(__doc__)
        sys.exit(1)

    if mode == "--supabase":
        table = positional or "keyword_scores_v2"
        rows = load_from_supabase(table)
        md, _ = analyze_full(rows, source_label=f"Supabase:{table}")
        write_markdown_report(out_path, md)

    elif mode == "--csv":
        if not positional:
            print("Usage: python agreement_metrics.py --csv <path.csv> [--out report.md]")
            sys.exit(1)
        rows = load_from_csv(positional)
        md, _ = analyze_full(rows, source_label=f"CSV:{positional}")
        write_markdown_report(out_path, md)

    elif mode == "--jsonl":
        if not positional:
            print("Usage: python agreement_metrics.py --jsonl <path.jsonl> [--out report.md]")
            sys.exit(1)
        rows = load_from_jsonl(positional)
        sample = rows[0] if rows else {}
        if "mistral_tag" in sample or "openai_tag" in sample:
            md, _ = analyze_full(rows, source_label=f"JSONL:{positional}")
        else:
            md, _ = analyze_jsonl_limited(rows, source_label=f"JSONL:{positional}")
        write_markdown_report(out_path, md)

    elif mode == "--demo":
        # WHY: Sanity-check formulas without network or private data.
        print("Running demo with synthetic data...")
        import random

        random.seed(42)
        cats = ["approved", "supplementary", "too_basic", "junk"]
        demo_rows = []
        for _ in range(500):
            true_cat = random.choices(cats, weights=[0.45, 0.30, 0.15, 0.10])[0]
            tags = []
            for _ in range(3):
                if random.random() < 0.80:
                    tags.append(true_cat)
                else:
                    tags.append(random.choice(cats))
            demo_rows.append(
                {
                    "mistral_tag": tags[0],
                    "openai_tag": tags[1],
                    "claude_tag": tags[2],
                    "category": random.choice(["Oncology", "Biochemistry", "Immunology"]),
                }
            )
        md, _ = analyze_full(
            demo_rows,
            source_label="SYNTHETIC DEMO (500 items, 80% per-rater accuracy)",
        )
        write_markdown_report(out_path, md)

    else:
        print(f"Unknown mode: {mode}")
        print(__doc__)
        sys.exit(1)
