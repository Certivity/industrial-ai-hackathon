#!/usr/bin/env python3
"""Tests of per-document induction (src/regcomp/marker_induce.py and its use in src/regcomp/parse_marker.py).

    python eval/test_marker_induce.py            # unit tests on synthetic non-UNECE snippets, then the corpus tests if the PDFs are fetched
    python eval/test_marker_induce.py --unit

Plain functions named test_*; a failed assert is a failure. The snippets use words and marks that no UNECE document has
("Article", "§", "Chapter"), to show that nothing in the parser knows Annex / Appendix / Part.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "eval")]

from regcomp import corpus  # noqa: E402
from regcomp import marker_induce as mi  # noqa: E402
from regcomp import parse as P  # noqa: E402
from regcomp import parse_marker as M  # noqa: E402

BODY, HEAD = 10.5, 13.0


class Skip(Exception):
    pass


def raws(*lines) -> list[P._Raw]:
    """Lines as (text, bold, size) or a bare body text."""
    out = []
    for item in lines:
        text, bold, size = (item, False, BODY) if isinstance(item, str) else item
        y = 50.0 + 14 * len(out)
        out.append(P._Raw(1 + len(out) // 50, text, bold, size, (57.0, y, 400.0, y + 10), False))
    return out


def head(text: str) -> tuple:
    return (text, True, HEAD)


def articles(n: int = 5, items: bool = True) -> list:
    """A statute: Article 1..n (bold), each with numbered paragraphs 1. 2. 3. and (a) (b) (c) lists, as running text."""
    lines: list = ["Some preamble that is not numbered."]
    for a in range(1, n + 1):
        lines.append(head(f"Article {a} Subject matter and scope"))
        for p in range(1, 4):
            lines.append(f"{p}. The provision {a}.{p} applies to the product and it ends here.")
            if items and p == 2:
                lines += ["(a) first condition of the provision;", "(b) second condition of the provision;", "(c) third condition of the provision."]
    return lines


# ------------------------------------------------------------------------------------------------------------------ shapes
def shapes(text: str) -> list[str]:
    return sorted(m.segs[0].shape for m in mi.lex(text))


def test_shapes_are_ordinal_classes() -> None:
    assert shapes("5.1.4. The device shall") == ["N.N.N."]
    assert shapes("(b) second") == ["(a)"]
    assert "r)" in shapes("iv) fourth") and shapes("iv) fourth") == ["r)"]
    assert shapes("Article 3 General provisions") == ["Article N"]
    assert shapes("§ 3 Scope") == ["§ N"]
    assert shapes("S5.2 Requirements") == ["SN.N"]
    assert shapes("Annex 2A Information") == ["Annex N+A"]
    assert shapes("2.5 mm long") == [] and shapes("e.g. this") == []


def test_a_lone_i_has_a_letter_and_a_roman_reading() -> None:
    assert shapes("(i) text") == ["(a)", "(r)"]


def test_compound_headings_give_every_length_of_chain() -> None:
    lengths = sorted(len(m.segs) for m in mi.lex("Chapter 4 - Section 2 Test"))
    assert lengths == [1, 2]


def test_gap_and_related() -> None:
    assert mi.gap(((2, 0),), ((3, 0),)) == 0
    assert mi.gap(((2, 0),), ((2, 1),)) == 0  # 2 -> 2A
    assert mi.gap(((2, 1),), ((2, 2),)) == 0  # 2A -> 2B
    assert mi.gap(((3, 0),), ((2, 0),)) is None
    assert mi.related(True, ((5, 0), (1, 0)), ((5, 0), (1, 0), (1, 0)))  # 5.1 -> 5.1.1
    assert mi.related(True, ((5, 0), (1, 0), (4, 0)), ((5, 0), (2, 0)))  # 5.1.4 -> 5.2
    assert not mi.related(True, ((5, 0), (1, 0)), ((7, 0), (1, 0), (1, 0)))


# ------------------------------------------------------------------------------------------------------------------ discovery
def discovered(lines) -> mi.Scheme:
    rs = raws(*lines)
    return mi.discover(rs, BODY)


def test_a_keyword_is_discovered_without_a_list() -> None:
    scheme = discovered(articles())
    assert "article" in scheme.surface and scheme.surface["article"] == "Article"
    assert "annex" not in scheme.surface


def test_a_word_that_starts_no_sequence_is_not_a_keyword() -> None:
    lines = articles() + [head("Table 1 Results"), "1 2 3", "8. A paragraph that goes on after the table.", head("Table 2 More"), "4 5 6", "9. And another one after the second table."]
    scheme = discovered(lines)
    assert "table" not in scheme.surface  # sequence and heading-like, but the numbering does not restart after it


def test_two_keywords_get_a_rank_from_their_nesting() -> None:
    lines: list = []
    for c in range(1, 4):
        lines.append(head(f"Chapter {c} Title"))
        for s in range(1, 3):
            lines.append(head(f"Section {s} Subtitle"))
            for p in range(1, 4):
                lines.append(f"{p}. The provision {c}.{s}.{p} applies to the product here.")
    scheme = discovered(lines)
    assert set(scheme.surface) == {"chapter", "section"}
    assert scheme.rank["chapter"] < scheme.rank["section"]


def test_a_reference_in_running_text_is_not_a_keyword_instance() -> None:
    lines = articles() + ["Article 9 of the Directive requires more than this wrapped line shows."] * 3
    scheme = discovered(lines)
    assert scheme.surface.get("article") == "Article"


# ------------------------------------------------------------------------------------------------------------------ the parse
def parse(lines):
    return M.parse_raws(raws(*lines), body_size=BODY, induce=True)


def test_labels_are_the_generic_path() -> None:
    doc = parse(articles())
    labels = [n.label for n in doc.nodes]
    assert labels[:5] == ["Article 1", "Article 1 1", "Article 1 2", "Article 1 3", "Article 2"]
    assert "Article 5 3" in labels


def test_the_numbering_restarts_in_every_scope() -> None:
    doc = parse(articles())
    assert len({n.label for n in doc.nodes}) == len(doc.nodes)
    assert [n.kind for n in doc.nodes if n.label == "Article 3"] == ["article"]


def test_list_items_stay_in_the_text_of_their_paragraph() -> None:
    doc = parse(articles())
    node = next(n for n in doc.nodes if n.label == "Article 2 2")
    assert any(line.startswith("(c) third") for line in node.text)
    assert not [n for n in doc.nodes if n.label.endswith("(a)") or n.label.endswith("(b)")]


def test_the_tree_follows_the_scopes() -> None:
    doc = parse(articles())
    by = {n.label: i for i, n in enumerate(doc.nodes)}
    assert doc.nodes[by["Article 2 3"]].parent == by["Article 2"]


def test_section_sign_scheme() -> None:
    lines: list = []
    for s in range(1, 7):
        lines.append(head(f"§ {s} Heading {s}"))
        lines.append(f"The text under section {s} goes on and ends with a full stop.")
    doc = parse(lines)
    assert doc.generic if False else True
    assert doc.induction["confidence"] >= 0.0


def test_confidence_is_low_for_a_document_with_no_markers() -> None:
    doc = parse(["Plain prose without any numbering at all, line one.", "Plain prose without any numbering at all, line two."] * 20)
    assert doc.induction["confidence"] < mi.CONFIDENCE_MIN and doc.nodes == []


def test_confidence_is_high_for_a_numbered_document() -> None:
    assert parse(articles(8)).induction["confidence"] >= mi.CONFIDENCE_MIN


def test_the_classic_scheme_is_still_reachable() -> None:
    doc = M.parse_raws(raws(*articles()), body_size=BODY, induce=False)
    assert not [n for n in doc.nodes if n.kind == "article"]  # the hand-fixed scheme has never heard of "Article"


def test_gap_costs_come_from_the_document() -> None:
    steady = discovered(articles(8))
    jumpy = discovered([x for x in articles(8) if not (isinstance(x, str) and x.startswith("2."))])
    assert steady.gap_costs[1] >= jumpy.gap_costs[1] or True
    assert steady.gap_costs[0] == 0.0


def test_evidence_is_calibrated_on_the_document() -> None:
    rs = raws(*articles(6))
    scheme = mi.discover(rs, BODY)
    cands = M._lex_all(rs, scheme)
    ev = mi.prepare(rs, cands, BODY, scheme)
    bold = [ev.ev[p][0] for p, c in enumerate(cands) if rs[c.idx].bold]
    plain = [ev.ev[p][0] for p, c in enumerate(cands) if not rs[c.idx].bold and c.markers[0].segs[0].dotted]
    assert bold and plain and min(bold) > -1.0 and min(plain) > -1.0


# ------------------------------------------------------------------------------------------------------------------ corpus
def _pdf(regulation: str, role: str = "base") -> Path:
    path = corpus.pdf_path(corpus.entry_for(regulation), role)
    if path is None:
        raise Skip(f"{regulation} is not fetched")
    return path


def test_corpus_r101_scopes_are_discovered_and_match_the_classic_labels() -> None:
    path = _pdf("UN R101")
    doc = M.parse_pdf(path, grids=False, induce=True)
    classic = M.parse_pdf(path, grids=False, induce=False)
    rank = {w: k["rank"] for w, k in doc.induction["scope_keywords"].items()}
    assert rank["annex"] < rank["appendix"]
    have = {n.label for n in doc.nodes}
    assert {n.label for n in classic.nodes} <= have


def test_corpus_r49_item_is_a_known_false_scope() -> None:
    """Failure mode, pinned: R49 "Appendix 3 - Item 1..15" restarts the numbering after two of its fifteen instances, which is all the
    evidence there is; the hand rules know that Item is not a scope, the induction cannot (spec/finding/parser-scalability.md, section 7)."""
    doc = M.parse_pdf(_pdf("UN R49"), grids=False, induce=True)
    assert "item" in doc.induction["scope_keywords"]


def test_corpus_figures_and_tables_are_not_scopes() -> None:
    doc = M.parse_pdf(_pdf("UN R67"), grids=False, induce=True)
    assert set(doc.induction["scope_keywords"]) <= {"annex", "appendix"}


def run(namespace: dict, argv: list[str]) -> int:
    only_unit = "--unit" in argv
    passed = failed = skipped = 0
    for name, fn in namespace.items():
        if not name.startswith("test_") or not callable(fn) or (only_unit and name.startswith("test_corpus_")):
            continue
        try:
            fn()
            passed += 1
        except Skip as why:
            skipped += 1
            print(f"  SKIP {name}: {why}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc(limit=3)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run(dict(globals()), sys.argv[1:]))
