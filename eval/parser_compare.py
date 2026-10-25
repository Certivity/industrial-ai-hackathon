#!/usr/bin/env python3
"""The marker parser (src/regcomp/parse_marker.py) against the hand-crafted one (src/regcomp/parse.py), as a silver set.

    python eval/parser_compare.py                 # the 5 anchored regulations and a spread of others (about a minute)
    python eval/parser_compare.py --all           # every fetched PDF, base and latest
    python eval/parser_compare.py --regs UN_R101 UN_R49 --verbose
    python eval/parser_compare.py --anchors       # also the expert anchors (eval/anchors.py) for both parsers

The hand parser is not the truth, only the one that was checked against the anchors; where the two differ, --verbose lists the labels.
Metrics per PDF, over the multiset of labels (the platform's key, tools/score_local._paragraph_key) of paragraph, table and scope nodes:

  P, R, F1, F2   marker labels against the hand parser's (F2 = 5PR / (4P + R), recall weighted)
  lab+pg         share of the hand parser's (label, first page) pairs the marker parser reproduces
  num+pg         the same for paragraphs by (number, first page) with the scope left out: a scope that one parser names
                 "Annex 4 Part 1" and the other "Annex 4" does not count against the numbering
  time           seconds per PDF, no table grids (the structure part only)
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "eval")]

from regcomp import corpus  # noqa: E402
from regcomp import parse as rules  # noqa: E402
from regcomp import parse_marker as marker  # noqa: E402
from score_local import _paragraph_key  # noqa: E402

ANCHORED = ["UN R150", "UN R148", "UN R48", "UN R10", "UN R175"]
SPREAD = ["UN R101", "UN R49", "UN R67", "UN R89", "UN R163", "UN R13H", "UN R131", "UN R171", "UN R40", "UN R107", "UN R3", "UN R100",
          "UN GTR 9", "UN R164", "UN R83"]


def keys(doc, kinds=None) -> Counter:
    return Counter(_paragraph_key(n.label) for n in doc.nodes if kinds is None or n.kind in kinds)


def f_scores(precision: float, recall: float) -> tuple[float, float]:
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    f2 = 5 * precision * recall / (4 * precision + recall) if precision + recall else 0.0
    return f1, f2


def compare(regulation: str, role: str, path: Path, verbose: bool = False) -> dict:
    t = time.time()
    a = rules.parse_pdf(path, grids=False)
    t_rules = time.time() - t
    t = time.time()
    b = marker.parse_pdf(path, grids=False)
    t_marker = time.time() - t
    ka, kb = keys(a), keys(b)
    inter = sum((ka & kb).values())
    p, r = inter / max(sum(kb.values()), 1), inter / max(sum(ka.values()), 1)
    f1, f2 = f_scores(p, r)
    la = Counter((_paragraph_key(n.label), n.page_start) for n in a.nodes)
    lb = Counter((_paragraph_key(n.label), n.page_start) for n in b.nodes)
    na = Counter((n.num, n.page_start) for n in a.nodes if n.kind == "para")
    nb = Counter((n.num, n.page_start) for n in b.nodes if n.kind == "para")
    row = {"pdf": f"{regulation} {role}", "n_rules": len(a.nodes), "n_marker": len(b.nodes), "p": p, "r": r, "f1": f1, "f2": f2,
           "lab_pg": sum((la & lb).values()) / max(sum(la.values()), 1), "num_pg": sum((na & nb).values()) / max(sum(na.values()), 1),
           "inter": inter, "t_rules": t_rules, "t_marker": t_marker}
    if verbose:
        row["only_rules"] = sorted((ka - kb).elements(), key=str)
        row["only_marker"] = sorted((kb - ka).elements(), key=str)
    return row


def anchors(parser: str) -> str:
    import anchors as gate
    gate.PARSER = parser
    found = total = 0
    for role, sources in (("base", gate.load_anchors()), ("latest", gate.load_new_anchors())):
        for regulation, wanted in sources.items():
            missed = gate.check(regulation, wanted, role)
            found, total = found + len(wanted) - len(missed), total + len(wanted)
    return f"{found}/{total}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--all", action="store_true", help="every fetched PDF, base and latest")
    parser.add_argument("--regs", nargs="*", help="regulations, e.g. UN_R101 or 'UN R101' (base and latest)")
    parser.add_argument("--anchors", action="store_true", help="also run the expert anchors for both parsers")
    parser.add_argument("--verbose", action="store_true", help="list labels only one of the parsers has")
    args = parser.parse_args(argv)

    pdfs = corpus.all_pdfs()
    if args.regs:
        wanted = {r.replace("_", " ") for r in args.regs}
        pdfs = [x for x in pdfs if x[0] in wanted]
    elif not args.all:
        pdfs = [x for x in pdfs if x[0] in ANCHORED + SPREAD and (x[1] == "base" or x[0] == "UN R175")]
    rows = []
    print(f"{'pdf':<16}{'rules':>6}{'marker':>7}{'P':>7}{'R':>7}{'F1':>7}{'F2':>7}{'lab+pg':>8}{'num+pg':>8}{'t rules':>9}{'t marker':>9}")
    for regulation, role, path in pdfs:
        row = compare(regulation, role, path, args.verbose)
        rows.append(row)
        print(f"{row['pdf']:<16}{row['n_rules']:>6}{row['n_marker']:>7}{row['p']:>7.3f}{row['r']:>7.3f}{row['f1']:>7.3f}{row['f2']:>7.3f}"
              f"{row['lab_pg']:>8.3f}{row['num_pg']:>8.3f}{row['t_rules']:>8.1f}s{row['t_marker']:>8.1f}s", flush=True)
        if args.verbose and (row["only_rules"] or row["only_marker"]):
            print("      only rules :", row["only_rules"][:12], len(row["only_rules"]))
            print("      only marker:", row["only_marker"][:12], len(row["only_marker"]))
    if rows:
        inter = sum(r["inter"] for r in rows)
        n_rules, n_marker = sum(r["n_rules"] for r in rows), sum(r["n_marker"] for r in rows)
        # micro: pooled over nodes; the nodes of a kind that is in both parsers' label multisets
        p, r = inter / max(n_marker, 1), inter / max(n_rules, 1)
        f1, f2 = f_scores(p, r)
        mean = lambda k: sum(x[k] for x in rows) / len(rows)  # noqa: E731
        print(f"{'micro':<16}{n_rules:>6}{n_marker:>7}{p:>7.3f}{r:>7.3f}{f1:>7.3f}{f2:>7.3f}"
              f"{sum(x['lab_pg'] * x['n_rules'] for x in rows) / max(n_rules, 1):>8.3f}{sum(x['num_pg'] * x['n_rules'] for x in rows) / max(n_rules, 1):>8.3f}"
              f"{sum(x['t_rules'] for x in rows):>8.1f}s{sum(x['t_marker'] for x in rows):>8.1f}s")
        print(f"{'macro':<16}{'':>6}{'':>7}{mean('p'):>7.3f}{mean('r'):>7.3f}{mean('f1'):>7.3f}{mean('f2'):>7.3f}{mean('lab_pg'):>8.3f}{mean('num_pg'):>8.3f}")
        print(f"PDFs {len(rows)}; identical label sets on {sum(1 for x in rows if x['p'] == 1 and x['r'] == 1)}; "
              f"F1 >= 0.95 on {sum(1 for x in rows if x['f1'] >= 0.95)}; num+pg >= 0.98 on {sum(1 for x in rows if x['num_pg'] >= 0.98)}")
    if args.anchors:
        print(f"anchors (193 expected): rules {anchors('rules')}, marker {anchors('marker')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
