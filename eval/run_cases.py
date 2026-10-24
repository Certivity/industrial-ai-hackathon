#!/usr/bin/env python3
"""Measure the lexical baseline on test cases, stage by stage, against each case's expected.json.

    python eval/run_cases.py cases/dev-rear-lamp spec/testing/cases/*         # a case is a folder with spec.md and expected.json
    python eval/run_cases.py spec/testing/cases/* --json spec/testing/results.json

Per case, the funnel of spec/precision.md M3, with precision, recall and F2 (beta 2) at every stage:
  regulations  where the gold regulations rank among all of them, and P and R of the set the baseline chooses
  sections     (gold regulations given) what the K best sections hold of the gold, and what that costs in nodes
  nodes        the N best nodes, or all nodes of the K best sections: with the gold regulations given, then with the chosen ones
"Paragraph level" counts a requirement as found when it cites a paragraph the gold cites (the platform accepts "page or
paragraph"). It stands in for the requirement-level score, which needs the judge, and it is an upper bound: the baseline emits
one requirement per node and the gold has 1.3 to 2.1 per cited paragraph. Regulation and page level come from tools/score_local.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import baseline  # noqa: E402
from baseline import emit, heading_only, parsed, section_of  # noqa: E402
from score_local import _paragraph_key, score  # noqa: E402

SECTION_SIZES = (1, 2, 3, 5, 8)
NODE_SIZES = (10, 25, 50, 100)
# (name suffix, match nodes with their breadcrumb, leave out nodes under a Definitions / Scope / Purpose heading)
# "-flat" and "-nodef" were added to see why the default fails; they are post hoc, the default is the first.
VARIANTS = (("", True, False), ("-flat", False, False), ("-nodef", True, True))


def f2(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 5 * precision * recall / (4 * precision + recall)


def prf(found: int, emitted: int, wanted: int) -> dict:
    precision, recall = found / emitted if emitted else 0.0, found / wanted if wanted else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f2": round(f2(precision, recall), 3)}


class Case:
    def __init__(self, folder: Path) -> None:
        self.id = folder.name
        self.spec = baseline.read_spec(folder / "spec.md")
        self.expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
        reqs = self.expected["requirements"]
        self.regulations = sorted({r["source"]["regulation"] for r in reqs})
        self.requirements = len(reqs)
        # gold paragraphs as (regulation, key), the node each one is, and the sections they sit in
        self.paragraphs = {(r["source"]["regulation"], _paragraph_key(r["source"]["paragraph"])) for r in reqs}
        by_key = {reg: {_paragraph_key(n.label): n for n in parsed(reg).nodes if n.kind in ("para", "table")} for reg in self.regulations}
        self.sections = {(reg, section_of(by_key[reg][key])) for reg, key in self.paragraphs if key in by_key[reg]}
        self.missing = [(reg, key) for reg, key in self.paragraphs if key not in by_key[reg]]

    def evaluate(self, picks: list) -> dict:
        cited = {(reg, _paragraph_key(node.label)) for reg, node in picks}
        found = len(cited & self.paragraphs)
        result = {"nodes": len(picks), "found": found, **{f"paragraph_{k}": v for k, v in prf(found, len(cited), len(self.paragraphs)).items()}}
        platform = score(baseline.to_submission(self.id, picks), self.expected)
        result["regulation_level"] = {k: round(platform["regulation_level"][k], 3) for k in ("precision", "recall")}
        result["page_level"] = {k: round(platform["page_level"][k], 3) for k in ("precision", "recall")}
        return result


def run(case: Case) -> dict:
    ranking = baseline.rank_regulations(case.spec)
    chosen = baseline.choose_regulations(ranking)
    rank = {name: i + 1 for i, (name, _) in enumerate(ranking)}
    out: dict = {
        "case": case.id, "gold_regulations": case.regulations, "gold_requirements": case.requirements,
        "gold_paragraphs": len(case.paragraphs), "gold_sections": len(case.sections), "unparsed_gold": case.missing,
        "stage_regulations": {
            "gold_ranks": {r: rank[r] for r in case.regulations}, "top5": [name for name, _ in ranking[:5]], "chosen": chosen,
            **prf(len(set(chosen) & set(case.regulations)), len(chosen), len(case.regulations)),
        },
    }
    # the oracle on sections: every non-heading node of the gold sections (spec/precision.md's "every node in the subtrees")
    every = [(reg, n) for reg in case.regulations for n in parsed(reg).nodes if n.kind in ("para", "table") and (reg, section_of(n)) in case.sections]
    kept = [(reg, n) for reg, n in every if not heading_only(n)]
    out["oracle_sections"] = {"every_node": {"nodes": len(every), **prf(case.evaluate(every)["found"], len(every), len(case.paragraphs))},
                              "without_headings": {"nodes": len(kept), **prf(case.evaluate(kept)["found"], len(kept), len(case.paragraphs))}}
    for mode, regulations in (("oracle_regulations", case.regulations), ("chosen_regulations", chosen)):
        rows = {}
        for strategy, sizes in (("sections", SECTION_SIZES), ("nodes", NODE_SIZES)):
            for suffix, graph, nodef in VARIANTS:
                if strategy == "sections" and suffix == "-flat":
                    continue
                for size in sizes:
                    picks = emit(regulations, case.spec, strategy, size, graph, nodef)
                    row = case.evaluate(picks)
                    if strategy == "sections":
                        index = lambda reg: baseline.index_of(reg, graph, nodef)  # noqa: E731
                        shown = {(reg, s) for reg in regulations for s in index(reg).ranked_sections(index(reg).score(case.spec.facets))[:size]}
                        row["gold_sections_found"] = len(shown & case.sections)
                    rows[f"{strategy}{suffix}:{size}"] = row
        out[mode] = rows
    out["taxonomy"] = taxonomy(case, chosen, baseline.NODES, baseline.SECTIONS)
    return out


def taxonomy(case: Case, chosen: list[str], n_nodes: int, k_sections: int) -> dict:
    """Why each emitted node is wrong and why each gold paragraph is missed, at the default settings, with the chosen regulations."""
    result = {}
    for strategy, size in (("nodes", n_nodes), ("sections", k_sections)):
        picks = emit(chosen, case.spec, strategy, size)  # the default variant: breadcrumb, definitions kept
        fp, found = Counter(), set()
        for reg, node in picks:
            key = (reg, _paragraph_key(node.label))
            if key in case.paragraphs:
                found.add(key)
                fp["found"] += 1
            elif reg not in case.regulations:
                fp["wrong regulation"] += 1
            elif (reg, section_of(node)) not in case.sections:
                fp["wrong section"] += 1
            elif node.body.rstrip().endswith(":"):
                fp["lead-in stem in a gold section"] += 1
            else:
                fp["uncited node in a gold section"] += 1
        emitted_sections = {(reg, section_of(n)) for reg, n in picks}
        fn = Counter()
        for reg, key in case.paragraphs - found:
            if reg not in chosen:
                fn["regulation not chosen"] += 1
            else:
                node = next((n for n in parsed(reg).nodes if n.kind in ("para", "table") and _paragraph_key(n.label) == key), None)
                fn["section not reached" if node is None or (reg, section_of(node)) not in emitted_sections else "in a reached section, not emitted"] += 1
        result[f"{strategy}:{size}"] = {"emitted": dict(fp), "missed": dict(fn)}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the lexical baseline on test cases.")
    parser.add_argument("cases", nargs="+", help="case folders, each with spec.md and expected.json")
    parser.add_argument("--json", help="write all numbers to this file")
    args = parser.parse_args(argv)

    results = []
    for folder in map(Path, args.cases):
        case = Case(folder)
        result = run(case)
        results.append(result)
        stage = result["stage_regulations"]
        print(f"\n== {case.id}: gold {case.requirements} requirements on {len(case.paragraphs)} paragraphs, {len(case.sections)} sections, {case.regulations}")
        if case.missing:
            print("   !! gold paragraphs the parser has no node for:", case.missing)
        print(f"   regulations: gold ranks {stage['gold_ranks']}, top5 {stage['top5']}, chosen {stage['chosen']}  P={stage['precision']} R={stage['recall']}")
        oracle = result["oracle_sections"]
        print(f"   oracle sections: every node {oracle['every_node']['nodes']} -> P={oracle['every_node']['precision']}; without headings {oracle['without_headings']['nodes']} -> "
              f"P={oracle['without_headings']['precision']} R={oracle['without_headings']['recall']} F2={oracle['without_headings']['f2']}")
        for mode in ("oracle_regulations", "chosen_regulations"):
            print(f"   [{mode}] strategy:size  nodes  P     R     F2    page P/R")
            for name, row in result[mode].items():
                print(f"      {name:<16}{row['nodes']:>5}  {row['paragraph_precision']:<5} {row['paragraph_recall']:<5} {row['paragraph_f2']:<5} "
                      f"{row['page_level']['precision']}/{row['page_level']['recall']}")
        print("   taxonomy:", json.dumps(result["taxonomy"]))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
