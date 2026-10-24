#!/usr/bin/env python3
"""Why the lexical baseline loses, case by case, and one rule from spec/precision.md that does not carry over.

    python eval/diagnose.py cases/dev-rear-lamp spec/testing/cases/*

  1. regulation rank of each gold regulation under three queries: the whole spec, the product type alone, product type plus
     functions. Post hoc and exploratory: it shows where the signal for choosing a regulation sits, it is not a tuned setting
  2. the sections ranked first inside the gold regulations, marked when the gold lives there
  3. heading-only nodes (spec/precision.md 4.1: under 60 characters, no verb, no digit) in the gold sections: how many the gold
     cites, and whether a node is a heading (it has sub-paragraphs) or a list item (it is a leaf)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import baseline  # noqa: E402
from baseline import Spec, heading_only, index_of, parsed, section_of  # noqa: E402
from run_cases import Case, f2, prf  # noqa: E402
from score_local import _paragraph_key  # noqa: E402


def query_ranks(case: Case) -> dict[str, dict[str, int]]:
    spec = case.spec
    queries = {"whole spec": spec.text, "product type": spec.product, "product type + functions": " ".join([spec.product, *spec.functions])}
    out = {}
    for name, text in queries.items():
        rank = {n: i + 1 for i, (n, _) in enumerate(baseline.rank_regulations(Spec(text, spec.facets)))}
        out[name] = {reg: rank[reg] for reg in case.regulations}
    return out


def top_sections(case: Case, shown: int = 6) -> dict[str, list[tuple[str, bool]]]:
    out = {}
    for reg in case.regulations:
        index = index_of(reg)
        ranked = index.ranked_sections(index.score(case.spec.facets))[:shown]
        out[reg] = [(section, (reg, section) in case.sections) for section in ranked]
    return out


def heading_rule(case: Case) -> dict:
    """The heading-only nodes of the gold sections, and what dropping them (all, or only those with sub-paragraphs) does."""
    rows = {"cited_leaf": 0, "cited_parent": 0, "uncited_leaf": 0, "uncited_parent": 0}
    every = kept_all = kept_parents = 0
    found_all = found_parents = 0
    for reg in case.regulations:
        nodes = [n for n in parsed(reg).nodes if n.kind in ("para", "table") and (reg, section_of(n)) in case.sections]
        nums = {(n.scope, n.num) for n in parsed(reg).nodes if n.kind == "para"}
        for n in nodes:
            every += 1
            cited = (reg, _paragraph_key(n.label)) in case.paragraphs
            parent = any(s == n.scope and len(m) > len(n.num) and m[: len(n.num)] == n.num for s, m in nums)
            hollow = heading_only(n)
            if hollow:
                rows[("cited" if cited else "uncited") + ("_parent" if parent else "_leaf")] += 1
            if not hollow:
                kept_all += 1
                found_all += cited
            if not (hollow and parent):
                kept_parents += 1
                found_parents += cited
    total = len(case.paragraphs)
    return {"nodes_in_gold_sections": every, **rows,
            "drop_all_heading_only": {"nodes": kept_all, **prf(found_all, kept_all, total)},
            "drop_only_headings_with_children": {"nodes": kept_parents, **prf(found_parents, kept_parents, total)}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostics for the lexical baseline on test cases.")
    parser.add_argument("cases", nargs="+")
    args = parser.parse_args(argv)
    for folder in map(Path, args.cases):
        case = Case(folder)
        print(f"\n== {case.id}")
        for name, ranks in query_ranks(case).items():
            print(f"   regulation rank, {name:<26} {ranks}")
        for reg, sections in top_sections(case).items():
            print(f"   first sections in {reg}: " + ", ".join(f"{s}{'*' if gold else ''}" for s, gold in sections) + "   (* = holds gold)")
        rule = heading_rule(case)
        print(f"   heading-only nodes in the gold sections: cited leaf {rule['cited_leaf']}, cited with children {rule['cited_parent']}, "
              f"uncited leaf {rule['uncited_leaf']}, uncited with children {rule['uncited_parent']}")
        for name in ("drop_all_heading_only", "drop_only_headings_with_children"):
            row = rule[name]
            print(f"   {name:<34} nodes {row['nodes']:>4}  P={row['precision']} R={row['recall']} F2={row['f2']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
