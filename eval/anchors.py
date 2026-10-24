#!/usr/bin/env python3
"""Parser gate: every expert anchor (regulation, page, paragraph) has to land on a parsed node.

    python eval/anchors.py              # every cases/*/expected.json and subgoal/*/requirements_old.json in the package
    python eval/anchors.py --misses     # also list the anchors that were not found

An anchor is found when a node of the regulation's base PDF has the same label (compared with the platform's own
tools/score_local._paragraph_key) and the anchor's page lies inside the node's page range. Exit status 1 if any is missed.
The sources are globbed, so the held-out sub-goal's requirements_old.json joins the gate as soon as it is pulled.

The new-version side of a sub-goal is checked the same way: the `source` (page, paragraph) of every change in
subgoal/*/expected.json points into the new PDF, which is the regulation's latest version (the folder's requirements_old.json names
the regulation). The held-out sub-goal has no expected.json, so there this side is empty.
Needs PyMuPDF and the base PDFs: python tools/fetch_regulations.py --role base --out regulations/data
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True  # importing tools/score_local.py must not leave a __pycache__ in the repo
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from regcomp import corpus  # noqa: E402
from regcomp.parse import parse_pdf  # noqa: E402
from score_local import _paragraph_key  # noqa: E402

SOURCES = sorted(ROOT.glob("cases/*/expected.json")) + sorted(ROOT.glob("subgoal/*/requirements_old.json"))
NEW_SIDE = sorted(ROOT.glob("subgoal/*/expected.json"))


def load_requirements() -> list[dict]:
    """Every expert requirement of the package, each with its `source` (regulation, page, paragraph)."""
    requirements = []
    for path in SOURCES:
        data = json.loads(path.read_text(encoding="utf-8"))
        requirements += data["requirements"] if isinstance(data, dict) else data
    return requirements


def load_anchors() -> dict[str, set[tuple[int, str]]]:
    anchors: dict[str, set[tuple[int, str]]] = defaultdict(set)
    for requirement in load_requirements():
        source = requirement["source"]
        anchors[source["regulation"]].add((source["page"], source.get("paragraph", "")))
    return anchors


def load_new_anchors() -> dict[str, set[tuple[int, str]]]:
    """(page, paragraph) of the new version, from the `source` of each change of a sub-goal's expected.json, by regulation."""
    anchors: dict[str, set[tuple[int, str]]] = defaultdict(set)
    for path in NEW_SIDE:
        old = path.with_name("requirements_old.json")
        if not old.is_file():
            continue
        data = json.loads(old.read_text(encoding="utf-8"))
        regulations = {r["source"]["regulation"] for r in (data["requirements"] if isinstance(data, dict) else data)}
        if len(regulations) != 1:  # the new PDF cannot be told from the folder when it has several regulations
            continue
        for change in json.loads(path.read_text(encoding="utf-8")).get("changes", []):
            source = change.get("source")
            if source:
                anchors[next(iter(regulations))].add((source["page"], source.get("paragraph", "")))
    return anchors


def check(regulation: str, anchors: set[tuple[int, str]], role: str = "base") -> list[tuple[int, str, list[tuple[str, int, int]]]]:
    """The anchors of one regulation that were not found, each with the nodes that carry its label (if any)."""
    pdf = corpus.pdf_path(corpus.entry_for(regulation), role)
    if pdf is None:
        raise SystemExit(f"error: the {role} PDF of {regulation} is not in regulations/data; run tools/fetch_regulations.py")
    by_label: dict[str | None, list] = defaultdict(list)
    for node in parse_pdf(pdf, grids=False).nodes:
        by_label[_paragraph_key(node.label)].append(node)
    misses = []
    for page, paragraph in sorted(anchors, key=lambda a: (a[0], a[1])):
        nodes = by_label.get(_paragraph_key(paragraph), [])
        if not any(n.page_start <= page <= n.page_end for n in nodes):
            misses.append((page, paragraph, [(n.label, n.page_start, n.page_end) for n in nodes]))
    return misses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the parser finds every expert anchor on the right page.")
    parser.add_argument("--misses", action="store_true", help="list the anchors that were not found")
    args = parser.parse_args(argv)

    found = total = 0
    for role, sources in (("base", load_anchors()), ("latest", load_new_anchors())):
        for regulation, anchors in sources.items():
            misses = check(regulation, anchors, role)
            found, total = found + len(anchors) - len(misses), total + len(anchors)
            print(f"{regulation:<10}{len(anchors) - len(misses):>4}/{len(anchors)}" + ("   (new version of the sub-goal)" if role == "latest" else ""))
            if args.misses:
                for page, paragraph, nodes in misses:
                    print(f"    MISS p{page} {paragraph!r}: {nodes or 'no node with that label'}")
    print(f"{'total':<10}{found:>4}/{total}")
    return 0 if found == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
