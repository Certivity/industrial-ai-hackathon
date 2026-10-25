#!/usr/bin/env python3
"""Text gate: the numbers of every expert requirement have to be in the text the parser gives its anchor node.

    python eval/fidelity.py              # the requirements of eval/anchors.py's sources
    python eval/fidelity.py --all        # also list the requirements that pass

eval/anchors.py checks that a label sits on the right page; it never reads the text. The extractor rewrites that text into
requirements, and the platform compares constraints, so a value the parser garbles (an exponent fused into its base,
"3.00∙10²" read as "3.00∙102") is a requirement lost while the anchor gate still passes.

A requirement passes when every number in its text (scientific notation such as "2.5·10¹" counts as one number) occurs in
its node's family: the node, its ancestors, its children, the tables it owns, and their grids. Thousands commas and the
two multiplication dots are normalised first. Numbers the gold derives rather than quotes are listed one by one in ALLOWED
with the reason. Exit status 1 if a requirement misses a number that is not allowed.

It also prints content-word containment (the share of a requirement's words of 3+ letters found in the node's own text and
in its family), a figure to track, not a gate.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from anchors import load_requirements  # noqa: E402
from regcomp import corpus  # noqa: E402
from regcomp.parse import Node, parse_pdf  # noqa: E402
from score_local import _paragraph_key  # noqa: E402

SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
PLAIN = str.maketrans(SUPERSCRIPTS, "0123456789-+")
NUMBER = re.compile(rf"\d+(?:\.\d+)*(?:∙10[{SUPERSCRIPTS}]+)?")
WORD = re.compile(r"[a-z]{3,}")
STOP = {"the", "and", "shall", "for", "with", "that", "which", "this", "are", "not", "than", "its", "from", "each", "any",
        "all", "has", "have", "been", "being", "when", "where", "who", "into", "per", "must", "may", "such", "also", "his"}

# (regulation, requirement id) -> (the numbers of the gold that are not in the text at that node, why)
ALLOWED: dict[tuple[str, str], tuple[set[str], str]] = {
    ("UN R148", "G-0218"): ({"60"}, "the gold adds '(60 cd)' after 6.0·10¹ cd"),
    ("UN R148", "G-0222"): ({"25"}, "the gold adds '(25 cd)' after 2.5·10¹ cd"),
    ("UN R148", "G-0232"): ({"1.2.1"}, "the gold names sibling 1.2.1 where the text says 'for all other lamps'"),
}


def normalise(text: str) -> str:
    text = text.replace("·", "∙").replace("⋅", "∙")
    # the gold writes powers of ten raised ("10²") but unit exponents flat ("100 cm2", "lx-1"); a unit's cannot fuse into a number
    text = re.sub(rf"(?<=[A-Za-z])[{SUPERSCRIPTS}]+", lambda m: m.group().translate(PLAIN), text)
    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # "1,200 mm" -> "1200 mm"; "Nos. 3, 27" is untouched


def numbers(text: str) -> list[str]:
    return sorted(set(NUMBER.findall(normalise(text))))


def occurs(number: str, text: str) -> bool:
    # not the tail of a longer number ("6.4" does not contain "4"), but "Rev.3" contains "3"
    return re.search(rf"(?<![\d{SUPERSCRIPTS}])(?<!\d\.){re.escape(number)}(?![\d{SUPERSCRIPTS}])", text) is not None


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower())) - STOP


def family(node: Node, nodes: list[Node]) -> list[Node]:
    """The node, its ancestors, its direct children and the tables it owns (all in its scope)."""
    out = []
    for other in nodes:
        if other.scope != node.scope or other.kind not in ("para", "table"):
            continue
        n, m = node.num, other.num
        if m == n[: len(m)] or (m[: len(n)] == n and len(m) == len(n) + 1):
            out.append(other)
    return out or [node]


def text_of(nodes: list[Node]) -> str:
    return normalise(" ".join(n.body + (" " + n.grid if n.grid else "") for n in nodes))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that every number of the expert requirements is in the parsed text.")
    parser.add_argument("--all", action="store_true", help="also list the requirements that pass")
    parser.add_argument("--parser", choices=("rules", "marker"), default="rules", help="which parser to check (default: the hand-crafted rules)")
    args = parser.parse_args(argv)
    if args.parser == "marker":
        from regcomp.parse_marker import parse_pdf as parse
    else:
        parse = parse_pdf

    by_regulation: dict[str, list[dict]] = defaultdict(list)
    for requirement in load_requirements():
        by_regulation[requirement["source"]["regulation"]].append(requirement)

    failed = allowed = total = 0
    own_80 = family_80 = 0
    for regulation, requirements in by_regulation.items():
        pdf = corpus.pdf_path(corpus.entry_for(regulation), "base")
        if pdf is None:
            raise SystemExit(f"error: the base PDF of {regulation} is not in regulations/data; run tools/fetch_regulations.py")
        nodes = parse(pdf).nodes
        by_label: dict[str | None, list[Node]] = defaultdict(list)
        for node in nodes:
            by_label[_paragraph_key(node.label)].append(node)
        passed = 0
        for requirement in requirements:
            source, total = requirement["source"], total + 1
            node = next((n for n in by_label.get(_paragraph_key(source.get("paragraph", "")), [])
                         if n.page_start <= source["page"] <= n.page_end), None)
            if node is None:
                print(f"  {regulation} {requirement['id']} {source.get('paragraph')!r}: no anchor node (see eval/anchors.py)")
                failed += 1
                continue
            kin = family(node, nodes)
            context = text_of(kin)
            missing = [x for x in numbers(requirement["text"]) if not occurs(x, context)]
            wanted = words(requirement["text"])
            if wanted:
                own_80 += len(wanted & words(text_of([node]))) >= 0.8 * len(wanted)
                family_80 += len(wanted & words(context)) >= 0.8 * len(wanted)
            excused, reason = ALLOWED.get((regulation, requirement["id"]), (set(), ""))
            if missing and set(missing) <= excused:
                allowed += 1
                print(f"  allowed {regulation} {requirement['id']} {node.label}: {missing} ({reason})")
            elif missing:
                failed += 1
                print(f"  MISS {regulation} {requirement['id']} {node.label}: {missing} not in the node's text")
            else:
                passed += 1
                if args.all:
                    print(f"  ok {regulation} {requirement['id']} {node.label}")
        print(f"{regulation:<10}{passed:>4}/{len(requirements)} with every number in the text")
    print(f"{'total':<10}{total - failed - allowed:>4}/{total}, {allowed} allowed, {failed} failed")
    print(f"content words: {own_80}/{total} requirements have 80% of theirs in the node's own text, {family_80}/{total} in its family")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
