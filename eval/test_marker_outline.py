#!/usr/bin/env python3
"""Offline tests of the model-outline fallback of the marker parser (src/regcomp/marker_outline.py): windows and overlap, heading
verification, node cutting, parent from level, cache, hallucination, de-duplication, refusal of cases/. A fake model; no network.

    python eval/test_marker_outline.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from test_parse import run_tests  # noqa: E402

from regcomp import marker_outline as mo  # noqa: E402
from regcomp.parse import ParsedDocument, _Raw  # noqa: E402

PAGES = {
    1: ["Contents", "1 Scope ....... 2", "Annex 1 ....... 3"],
    2: ["1 Scope", "1.1. This text applies to widgets.", "2 Defi-", "nitions", "2.1. A widget is a thing."],
    3: ["2.2. A gadget is another thing.", "2.2.1. Small gadgets weigh less.", "Annex 1", "1. Test of the ﬁrst kind", "1.1. Procedure text."],
    4: ["2. Second part of the annex", "Closing remarks go here."],
}


def make_doc(tmp: Path, pages=PAGES) -> ParsedDocument:
    pdf = tmp / "doc.pdf"
    pdf.write_bytes(b"%PDF fake " + repr(sorted(pages.items())).encode())
    raws = [_Raw(p, text, text[:1].isupper() and len(text) < 20, 10.0, (50.0, 10.0 * i, 300.0, 10.0 * i + 9))
            for p, lines in pages.items() for i, text in enumerate(lines)]
    doc = ParsedDocument(path=pdf, pages=max(pages))
    doc.raws, doc.induction = raws, {"confidence": 0.2}
    return doc


GOOD = {
    "headings": [
        {"label": "1", "page": 2, "words": "1 Scope", "level": 1, "kind": "para"},
        {"label": "1.1", "page": 2, "words": "1.1. This text applies", "level": 2, "kind": "para"},
        {"label": "2", "page": 2, "words": "2 Definitions", "level": 1, "kind": "para"},
        {"label": "2.1", "page": 2, "words": "2.1. A widget is a thing.", "level": 2, "kind": "para"},
        {"label": "2.2", "page": 3, "words": "2.2. A gadget", "level": 2, "kind": "para"},
        {"label": "2.2.1", "page": 3, "words": "2.2.1. Small gadgets", "level": 3, "kind": "para"},
        {"label": "Annex 1", "page": 3, "words": "Annex 1", "level": 1, "kind": "scope"},
        {"label": "1", "page": 3, "words": "1. Test of the first kind", "level": 2, "kind": "para"},
        {"label": "1.1", "page": 3, "words": "1.1. Procedure", "level": 3, "kind": "para"},
        {"label": "2", "page": 4, "words": "2. Second part", "level": 2, "kind": "para"},
    ]
}


class Fake:
    """A fake model that answers every window with the same reply (the code's de-duplication and cursor sort it out)."""

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def __call__(self, system, user):
        self.prompts.append(user)
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def run(tmp, reply, grids=False, pages=PAGES, **kw):
    doc = make_doc(tmp, pages)
    ask = Fake(reply)
    out = mo.parse_with_outline(doc.path, doc, grids, ask=ask, cache_dir=tmp / "cache", **kw)
    return doc, out, ask


def test_verification():
    raws = make_doc(Path(tempfile.mkdtemp())).raws
    at = mo.find_heading(raws, -1, 2, "2 Definitions")
    assert raws[at].text == "2 Defi-"  # wrapped heading, hyphen tolerated
    assert mo.find_heading(raws, -1, 3, "1. Test of the first kind") is not None  # ligature tolerated
    assert mo.find_heading(raws, -1, 3, "ANNEX 1") is not None  # case tolerated
    assert mo.find_heading(raws, -1, 4, "Annex 1") is None  # wrong page
    assert mo.find_heading(raws, -1, 2, "2.1. A widget is a gadget") is None  # not what is printed
    assert mo.find_heading(raws, mo.find_heading(raws, -1, 2, "1 Scope"), 2, "1 Scope") is None  # monotone: not at or before the cursor
    assert mo.find_heading(raws, -1, 2, "..") is None  # too short to verify


def test_windows_overlap():
    raws = make_doc(Path(tempfile.mkdtemp())).raws
    wins = mo.make_windows(raws, 4, max_pages=3)
    assert [(a, b) for a, b, _ in wins] == [(1, 3), (3, 4)]  # one page of overlap
    assert "=== page 3 ===" in wins[0][2] and "=== page 3 ===" in wins[1][2]
    wins = mo.make_windows(raws, 4, max_pages=3, max_bytes=200)
    assert all(len(t.encode()) <= 200 for _, _, t in wins) and wins[0][0] == 1 and wins[-1][1] == 4  # byte cap kept, document covered
    for (a1, b1, _), (a2, b2, _) in zip(wins, wins[1:]):
        assert a2 == b1 or a2 == b1 + 1  # overlap by a page, or advance by one when a window holds a single page


def test_cutting_and_parents():
    _, out, _ = run(Path(tempfile.mkdtemp()), GOOD)
    assert out is not None and out.induction["fallback"] is True
    labels = [n.label for n in out.nodes]
    assert labels == ["1", "1.1", "2", "2.1", "2.2", "2.2.1", "Annex 1", "Annex 1 1", "Annex 1 1.1", "Annex 1 2"], labels
    n = out.nodes
    assert n[2].text == ["2 Defi-", "nitions"] and n[2].page_start == n[2].page_end == 2  # text is the PDF's, cut by code
    assert n[4].text == ["2.2. A gadget is another thing."] and n[4].pages == [3]
    assert n[9].text == ["2. Second part of the annex", "Closing remarks go here."] and n[9].page_end == 4
    assert [x.parent for x in n] == [-1, 0, -1, 2, 2, 4, -1, 6, 7, 6]
    assert n[2].children == [3, 4] and n[6].children == [7, 9]
    assert (n[6].kind, n[6].scope, n[7].scope, n[7].num, n[0].scope) == ("annex", "Annex 1", "Annex 1", (1,), "")
    assert n[5].num == (2, 2, 1) and n[5].path.count("›") == 2
    assert out.front_chars == sum(len(t) for t in PAGES[1])  # the table of contents sits before the first heading
    st = out.induction["outline"]
    assert st["verified"] == 10 and st["dropped"] == 0


def test_hallucination_dropped():
    bad = {"headings": GOOD["headings"][:3] + [{"label": "9.9", "page": 2, "words": "9.9. The widget shall explode", "level": 2, "kind": "para"},
                                             {"label": "x", "page": "?", "words": "zzz", "level": 1, "kind": "para"}, "junk"]}
    _, out, _ = run(Path(tempfile.mkdtemp()), bad)
    assert [n.label for n in out.nodes] == ["1", "1.1", "2"]
    st = out.induction["outline"]
    assert st["dropped"] >= 2 and st["verified"] == 3
    assert not any("explode" in " ".join(n.text) for n in out.nodes)  # nothing the model wrote reaches the text


def test_dedup_across_overlap():
    tmp = Path(tempfile.mkdtemp())
    doc = make_doc(tmp)
    replies = iter([json.dumps({"headings": GOOD["headings"][:6]}), json.dumps({"headings": GOOD["headings"][4:]})])  # windows (1-3), (3-4)
    out = mo.parse_with_outline(doc.path, doc, False, ask=lambda s, u: next(replies), cache_dir=tmp / "c")
    assert [n.label for n in out.nodes].count("2.2") == 1 and len(out.nodes) == 10
    st = out.induction["outline"]
    assert st["calls"] == 2 and st["duplicates"] == 2 and st["dropped"] == 0


def test_stack_carried():
    tmp = Path(tempfile.mkdtemp())
    doc = make_doc(tmp)
    seen = []
    replies = iter([json.dumps({"headings": GOOD["headings"][:6]}), json.dumps({"headings": []})])

    def ask(system, user):
        seen.append(user)
        return next(replies)

    mo.parse_with_outline(doc.path, doc, False, ask=ask, cache_dir=tmp / "c")
    assert "(none yet)" in seen[0] and "level 1: 2 | 2 Definitions" in seen[1] and "level 3: 2.2.1" in seen[1]
    assert "UN" not in mo.SYSTEM and "UNECE" not in mo.SYSTEM  # neutral vocabulary only


def test_cache_hit():
    tmp = Path(tempfile.mkdtemp())
    doc = make_doc(tmp)
    first = Fake(GOOD)
    a = mo.parse_with_outline(doc.path, doc, False, ask=first, cache_dir=tmp / "c")
    second = Fake(GOOD)
    b = mo.parse_with_outline(doc.path, doc, False, ask=second, cache_dir=tmp / "c")
    assert first.prompts and not second.prompts  # no model call the second time
    assert [n.label for n in a.nodes] == [n.label for n in b.nodes]
    assert b.induction["outline"]["calls"] == 0 and b.induction["outline"]["cache_hits"] == len(first.prompts)
    other = make_doc(tmp, {**PAGES, 4: ["2. Second part of the annex"]})  # other PDF bytes: other cache entries
    third = Fake(GOOD)
    mo.parse_with_outline(other.path, other, False, ask=third, cache_dir=tmp / "c")
    assert third.prompts


def test_refuses_cases_path():
    tmp = Path(tempfile.mkdtemp()) / "cases" / "x"
    tmp.mkdir(parents=True)
    doc = make_doc(tmp)
    ask = Fake(GOOD)
    assert mo.parse_with_outline(doc.path, doc, False, ask=ask, cache_dir=tmp / "c") is None
    assert not ask.prompts


def test_failures_return_none():
    tmp = Path(tempfile.mkdtemp())
    assert run(tmp, "not json")[1] is None
    assert run(tmp, {"headings": []})[1] is None

    def boom(system, user):
        raise SystemExit("unreachable")

    doc = make_doc(tmp)
    assert mo.parse_with_outline(doc.path, doc, False, ask=boom, cache_dir=tmp / "c2") is None


if __name__ == "__main__":
    raise SystemExit(run_tests(globals(), sys.argv[1:]))
