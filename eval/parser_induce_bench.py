#!/usr/bin/env python3
"""Parser-level numbers of the marker parser with per-document induction (src/regcomp/parse_marker.py, marker_induce.py) against the
marker parser with its hand-fixed scheme (REGCOMP_MARKER_INDUCE=0, "classic") and the hand parser.

    python eval/parser_induce_bench.py labels --dev        # label agreement with the classic marker parser on the development PDFs
    python eval/parser_induce_bench.py labels --all        # ... on every PDF (the number reported at the end)
    python eval/parser_induce_bench.py grounding           # DeepSeek-grounded requirements: quote in one node, label matches
    python eval/parser_induce_bench.py anchors             # expert anchors for the three parsers (same as eval/anchors.py)

The development set is every corpus PDF except the regulations of cases/dev-rear-lamp (UN R10, R48, R148, R150) and its known wrong
extra (R128): those are not looked at while the parser is tuned. Part B (the model outline) is off here unless --llm is given; the
confidence of part A and whether it would have fallen back are reported either way.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "eval")]

from regcomp import corpus  # noqa: E402
from regcomp import parse as hand  # noqa: E402
from regcomp import parse_marker as marker  # noqa: E402
from score_local import _paragraph_key  # noqa: E402

HELD_OUT = ("UN R10", "UN R48", "UN R148", "UN R150", "UN R128")  # the dev case's regulations and its known wrong extra
CACHE = ROOT / "runs" / "_generic" / "labels_cache.json"


def pdfs(dev: bool) -> list[tuple[str, str, Path]]:
    return [(r, role, p) for r, role, p in corpus.all_pdfs() if not dev or r not in HELD_OUT]


def f_scores(p: float, r: float) -> tuple[float, float]:
    return (2 * p * r / (p + r) if p + r else 0.0), (5 * p * r / (4 * p + r) if p + r else 0.0)


def induced(path, grids=False):
    return marker.parse_pdf(path, grids=grids, induce=True)


def classic(path, grids=False):
    return marker.parse_pdf(path, grids=grids, induce=False)


def labels_of(doc) -> list[tuple[str, int]]:
    return [(_paragraph_key(n.label), n.page_start) for n in doc.nodes]


def cached(parser: str, regulation: str, role: str, path: Path) -> list:
    store = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}
    key = f"{parser}|{regulation}|{role}"
    if key not in store:
        store[key] = labels_of({"marker": classic, "hand": hand.parse_pdf}[parser](path, grids=False))
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(store), encoding="utf-8")
    return [tuple(x) for x in store[key]]


def cmd_labels(args: argparse.Namespace) -> int:
    if args.llm:
        os.environ["REGCOMP_MARKER_LLM"] = "1"
    rows = []
    for regulation, role, path in pdfs(args.dev):
        ref = cached(args.against, regulation, role, path)
        t = time.time()
        doc = induced(path)
        elapsed = time.time() - t
        mine = labels_of(doc)
        ka, kb = Counter(k for k, _ in ref), Counter(k for k, _ in mine)
        inter = sum((ka & kb).values())
        pa, pb = Counter(ref), Counter(mine)
        both = sum((pa & pb).values())
        p, r = inter / max(len(mine), 1), inter / max(len(ref), 1)
        f1, f2 = f_scores(p, r)
        g = getattr(doc, "induction", {})
        rows.append({"pdf": f"{regulation} {role}", "p": p, "r": r, "f1": f1, "f2": f2, "lab_pg": both / max(len(ref), 1), "n": len(mine), "n_ref": len(ref),
                     "inter": inter, "time": elapsed, "conf": g.get("confidence", 0), "fallback": g.get("fallback", False),
                     "would_fall_back": g.get("confidence_a", g.get("confidence", 0)) < marker.mi.CONFIDENCE_MIN})
        if args.verbose:
            print(f"{rows[-1]['pdf']:<18} n {len(mine):>5}/{len(ref):<5} P {p:.3f} R {r:.3f} F1 {f1:.3f} lab+pg {rows[-1]['lab_pg']:.3f} conf {rows[-1]['conf']:.2f} {elapsed:.1f}s", flush=True)
    tot_i, tot_m, tot_r = (sum(x[k] for x in rows) for k in ("inter", "n", "n_ref"))
    p, r = tot_i / tot_m, tot_i / tot_r
    f1, f2 = f_scores(p, r)
    macro = [sum(x[k] for x in rows) / len(rows) for k in ("p", "r", "f1", "f2", "lab_pg")]
    print(f"\n{len(rows)} PDFs against {args.against}: micro P {p:.3f} R {r:.3f} F1 {f1:.3f} F2 {f2:.3f}; macro P {macro[0]:.3f} R {macro[1]:.3f} F1 {macro[2]:.3f} F2 {macro[3]:.3f}; "
          f"(label, page) {macro[4]:.3f}")
    times = sorted(x["time"] for x in rows)
    print(f"time per PDF, no grids: total {sum(times):.0f} s, median {times[len(times) // 2]:.2f} s, max {times[-1]:.1f} s")
    low = [x for x in rows if x["would_fall_back"]]
    print(f"confidence of part A under {marker.mi.CONFIDENCE_MIN}: {len(low)} PDFs; min {min(x['conf'] for x in rows):.2f}; " + ", ".join(x["pdf"] for x in low[:12]))
    worst = sorted(rows, key=lambda x: x["f1"])[:10]
    print("lowest F1: " + "; ".join(f"{x['pdf']} {x['f1']:.2f}" for x in worst))
    return 0


# ------------------------------------------------------------------------------------------------------------------ grounding
def squash(text: str) -> str:
    return re.sub(r"\s+", "", text.translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")))


def grounded_rows() -> list[dict]:
    """The requirements that DeepSeek wrote and the hand parser grounded: regulation, page, the paragraph the model named, the quote as the
    hand parser's node has it, and the hand parser's label."""
    rows = []
    folders = sorted(ROOT.glob("testing/ts-*")) + sorted((ROOT / "spec" / "testing" / "cases").glob("ds-*"))
    for folder in folders:
        gp, pp = folder / "ground.json", folder / "provider.json"
        if not (gp.is_file() and pp.is_file()):
            continue
        ground = json.loads(gp.read_text(encoding="utf-8"))
        reqs = json.loads(pp.read_text(encoding="utf-8"))["requirements"]
        for g, q in zip(ground, reqs):
            if g.get("verdict") == "ok" and g.get("exact"):
                rows.append({"case": folder.name, "regulation": g["regulation"], "page": g["page"], "paragraph": q["paragraph"], "quote": g["exact"], "hand_label": g["label"]})
    return rows


def cmd_grounding(args: argparse.Namespace) -> int:
    rows = grounded_rows()
    if args.llm:
        os.environ["REGCOMP_MARKER_LLM"] = "1"
    parsers = {"hand": hand.parse_pdf, "classic": classic, "induced": induced}
    result = {name: Counter() for name in parsers}
    docs: dict[tuple[str, str], list] = {}
    for name, fn in parsers.items():
        for reg in sorted({r["regulation"] for r in rows}):
            path = corpus.pdf_path(corpus.entry_for(reg), "base")
            docs[(name, reg)] = [(n, squash(n.body)) for n in fn(path, grids=False).nodes]
    for row in rows:
        quote, want = squash(row["quote"]), _paragraph_key(row["hand_label"])
        named = _paragraph_key(row["paragraph"])
        for name in parsers:
            nodes = docs[(name, row["regulation"])]
            holding = [n for n, s in nodes if quote in s]
            near = [n for n in holding if n.page_start - 1 <= row["page"] <= n.page_end + 1]
            result[name]["rows"] += 1
            result[name]["one node"] += bool(holding)
            result[name]["one node, page"] += bool(near)
            result[name]["label as hand's"] += any(_paragraph_key(n.label) == want for n in near)
            result[name]["label as the model's"] += any(_paragraph_key(n.label) == named for n in near)
    print(f"{len(rows)} DeepSeek-grounded requirements in {len({r['case'] for r in rows})} cases")
    for name, c in result.items():
        n = c["rows"]
        print(f"{name:<8} quote in one node {c['one node'] / n:.3f}; and on the page (+-1) {c['one node, page'] / n:.3f}; label as the hand parser's {c['label as hand\'s'] / n:.3f}; "
              f"label as the model wrote it {c['label as the model\'s'] / n:.3f}")
    return 0


def cmd_anchors(args: argparse.Namespace) -> int:
    import anchors as gate
    for name in ("rules", "classic", "induced"):
        gate.PARSER = "rules" if name == "rules" else "marker"
        os.environ["REGCOMP_MARKER_INDUCE"] = "1" if name == "induced" else "0"
        marker.INDUCE_DEFAULT = name == "induced"
        found = total = 0
        t = time.time()
        for role, sources in (("base", gate.load_anchors()), ("latest", gate.load_new_anchors())):
            for regulation, wanted in sources.items():
                misses = gate.check(regulation, wanted, role)
                found, total = found + len(wanted) - len(misses), total + len(wanted)
        print(f"{name:<8} {found}/{total}  ({time.time() - t:.0f} s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("labels")
    a.add_argument("--dev", action="store_true")
    a.add_argument("--all", action="store_true")
    a.add_argument("--against", choices=["marker", "hand"], default="marker")
    a.add_argument("--llm", action="store_true", help="force part B (REGCOMP_MARKER_LLM=1)")
    a.add_argument("--verbose", "-v", action="store_true")
    a.set_defaults(fn=cmd_labels)
    b = sub.add_parser("grounding")
    b.add_argument("--llm", action="store_true")
    b.set_defaults(fn=cmd_grounding)
    c = sub.add_parser("anchors")
    c.set_defaults(fn=cmd_anchors)
    args = ap.parse_args(argv)
    if args.cmd == "labels" and not (args.dev or args.all):
        ap.error("labels needs --dev or --all")
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
