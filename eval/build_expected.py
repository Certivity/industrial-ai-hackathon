#!/usr/bin/env python3
"""Build a test case's expected.json from an authoring file, checking every citation against the parsed regulation.

    python eval/build_expected.py spec/testing/cases/<case>/authoring.json

authoring.json:
    {"case_id": "synth-r43-windscreen", "regulation": "UN R43",
     "requirements": [{"paragraph": "6.1", "quote": "danger of bodily injury", "text": "The windscreen shall ..."}, ...]}

Each requirement is one atomic obligation written as "X shall Y". `quote` is a verbatim phrase of the cited node (copy it from
the node's text): the script finds it in the node to fix the page, and refuses a requirement whose quote or paragraph is not
there, so every label and page in the output comes from the parser, not from typing. A requirement may carry its own
"regulation" to cite a different one. The output, expected.json next to the input, has the format of
cases/dev-rear-lamp/expected.json. Needs PyMuPDF and the base PDFs in regulations/data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from regcomp import corpus  # noqa: E402
from regcomp.parse import Node, parse_pdf  # noqa: E402
from score_local import _paragraph_key  # noqa: E402


def load_nodes(regulation: str) -> dict[str | None, Node]:
    pdf = corpus.pdf_path(corpus.entry_for(regulation), "base")
    if pdf is None:
        raise SystemExit(f"error: the base PDF of {regulation} is not in regulations/data; run tools/fetch_regulations.py")
    nodes: dict[str | None, Node] = {}
    for node in parse_pdf(pdf, grids=False).nodes:
        if node.kind in ("para", "table"):
            nodes.setdefault(_paragraph_key(node.label), node)
    return nodes


def build(authoring: dict) -> tuple[dict, list[str]]:
    """The expected file and the problems found (an empty list when every citation is grounded)."""
    problems: list[str] = []
    parsed: dict[str, dict[str | None, Node]] = {}
    requirements = []
    for number, item in enumerate(authoring["requirements"], start=1):
        regulation = item.get("regulation", authoring["regulation"])
        if regulation not in parsed:
            parsed[regulation] = load_nodes(regulation)
        node = parsed[regulation].get(_paragraph_key(item["paragraph"]))
        if node is None:
            problems.append(f"#{number}: {regulation} has no paragraph {item['paragraph']!r}")
            continue
        page = node.page_of(item["quote"]) if item.get("quote") else node.page_start
        if page is None:
            problems.append(f"#{number}: the quote {item['quote']!r} is not in {regulation} {node.label}")
            continue
        version = corpus.version_label(corpus.entry_for(regulation), "base")
        requirements.append({
            "id": f"G-{number:04d}",
            "text": item["text"],
            "source": {"regulation": regulation, "version": version, "page": page, "paragraph": node.label},
        })
    return {"team_id": "synthetic", "case_id": authoring["case_id"], "requirements": requirements}, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build expected.json from an authoring file, verifying every citation.")
    parser.add_argument("authoring", help="path of authoring.json")
    args = parser.parse_args(argv)

    path = Path(args.authoring)
    expected, problems = build(json.loads(path.read_text(encoding="utf-8")))
    for problem in problems:
        print("error:", problem, file=sys.stderr)
    if problems:
        return 1
    target = path.with_name("expected.json")
    target.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pages = sorted({r["source"]["page"] for r in expected["requirements"]})
    paragraphs = {r["source"]["paragraph"] for r in expected["requirements"]}
    print(f"{target}: {len(expected['requirements'])} requirements on {len(paragraphs)} paragraphs, pages {pages[0]}..{pages[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
