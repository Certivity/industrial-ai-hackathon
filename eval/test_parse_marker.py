#!/usr/bin/env python3
"""Tests of src/regcomp/parse_marker.py (the marker lexer + stack parse): the lexer, succ/gap, the ambiguous readings, the beam on
small synthetic line lists, and, with the PDFs fetched, the regulations whose hand rules it is meant to make unnecessary.

    python eval/test_parse_marker.py            # unit tests, then the corpus tests if regulations/data has the PDFs
    python eval/test_parse_marker.py --unit     # unit tests only

Plain functions named test_*; a failed assert is a failure. No pytest needed (it runs them too).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from regcomp import corpus  # noqa: E402
from regcomp import parse as P  # noqa: E402
from regcomp import parse_marker as M  # noqa: E402

HEAD = 13.0  # heading size over a 10.5 body (1.24x, as in the PDFs)
BODY = 10.5


def raws(*lines: str | tuple, page: int = 1) -> list[P._Raw]:
    """Lines as (text, bold, size) or a bare text (body, not bold); a page break is a line ('--page--',)."""
    out: list[P._Raw] = []
    for item in lines:
        if item == ("--page--",):
            page += 1
            continue
        text, bold, size = (item, False, BODY) if isinstance(item, str) else item
        y = 50.0 + 12 * len(out)
        out.append(P._Raw(page, text, bold, size, (57.0, y, 400.0, y + 10), False))
    return out


def _parse(lines: list[P._Raw]) -> P.ParsedDocument:
    return M.parse_raws(lines, body_size=BODY, induce=False)


def head(text: str) -> tuple:
    return (text, True, HEAD)


def labels(*lines, kinds=("para",)) -> list[str]:
    doc = _parse(raws(*lines))
    return [n.label for n in doc.nodes if n.kind in kinds]


# ------------------------------------------------------------------------------------------------------------------ lexer
def sigs(text: str) -> list[str]:
    return [" ".join(f"{s.kw} {s.key}".strip() + ("|" + s.sig if s.sig else "") for s in m.segs) + m.deco for m in M.lex(text)]


def test_lex_dotted_number() -> None:
    (m,) = M.lex("5.1.4. The device shall")
    assert [s.key for s in m.segs] == ["N.N.N"] and m.segs[0].val == ((5, 0), (1, 0), (4, 0)) and m.deco == "." and m.rest.startswith("The")
    assert m.segs[0].dotted and not m.segs[0].first


def test_lex_no_space_after_the_dot() -> None:
    (m,) = M.lex("5.1.2.An immobilizer shall")
    assert m.segs[0].val == ((5, 0), (1, 0), (2, 0)) and m.rest == "An immobilizer shall"


def test_lex_heading_without_final_dot() -> None:
    (m,) = M.lex("5.7 Test procedure")
    assert m.deco == "" and m.segs[0].key == "N.N"
    (m,) = M.lex("1 Scope")
    assert m.deco == "" and m.segs[0].key == "N" and m.segs[0].first


def test_lex_rejects_numbers_in_running_text() -> None:
    for text in ("1.20∙10³ at 5 m", "2.5 mm wide", "e.g. the car", "i.e. when", "12345", "5.1.2.3x", "of this Regulation", "(of the"):
        assert M.lex(text) == [], text


def test_lex_list_markers() -> None:
    assert sigs("(a) the first") == ["a|()"] or sigs("(a) the first")[0].startswith("(")
    (m,) = M.lex("(ii) second")
    assert m.segs[0].key == "(r)" and m.segs[0].val == ((2, 0),)
    (m,) = M.lex("a) first")
    assert m.segs[0].key == "a)" and m.deco == ")"
    (m,) = M.lex("B. Test")
    assert m.segs[0].key == "A." and m.segs[0].val == ((2, 0),)


def test_lex_ambiguous_readings() -> None:
    """A lone i, v, x is both a letter and a roman numeral; ii and iv are only roman, h only a letter."""
    keys = lambda t: sorted(m.segs[0].key for m in M.lex(t))  # noqa: E731
    assert keys("(i) text") == ["(a)", "(r)"]
    assert keys("(v) text") == ["(a)", "(r)"]
    assert keys("(iv) text") == ["(r)"]
    assert keys("(h) text") == ["(a)"]
    assert keys("I. Statement") == ["A.", "R."]
    values = {m.segs[0].key: m.segs[0].val for m in M.lex("(i) text")}
    assert values["(a)"] == ((9, 0),) and values["(r)"] == ((1, 0),)


def test_lex_keyword_markers() -> None:
    (m,) = M.lex("Annex 2A Information document")
    seg = m.segs[0]
    assert (seg.kw, seg.key, seg.sig, seg.val, seg.raw) == ("annex", "Annex N", "Annex N+A", ((2, 1),), "2A") and m.rest.startswith("Information")
    (m,) = M.lex("ANNEX 1 COMMUNICATION")
    assert m.segs[0].kw == "annex" and m.segs[0].val == ((1, 0),)
    (m,) = M.lex("Annex 4 - Appendix 1 Test")
    assert [(s.kw, s.val) for s in m.segs] == [("annex", ((4, 0),)), ("appendix", ((1, 0),))]
    (m,) = M.lex("Annex 4 – Part 2 – Appendix 3 Test")
    assert [s.kw for s in m.segs] == ["annex", "part", "appendix"]
    (m,) = M.lex("Annex 2B - Appendix Containers only")  # a keyword with no number is the only one
    assert [(s.kw, s.val) for s in m.segs] == [("annex", ((2, 2),)), ("appendix", ((1, 0),))]
    assert sorted(m.segs[0].key for m in M.lex("Part I - Approval")) == ["Part A", "Part R"]
    assert M.lex("Part of the system") == []  # not a marker: "of" is no component
    assert M.lex("Annex 1.") and M.lex("Annex 5 to this Regulation")  # lexed; the evidence rejects them (not bold)


def test_roman_values() -> None:
    assert [M.roman_value(x) for x in ("i", "iv", "ix", "xiv", "MCM")] == [1, 4, 9, 14, 1900]
    assert M.roman_value("iiii") is None and M.roman_value("vx") is None and M.roman_value("abc") is None


# ------------------------------------------------------------------------------------------------------------------ relations
def test_gap_and_succ() -> None:
    f = lambda a, b: M.gap(tuple((x, 0) for x in a), tuple((x, 0) for x in b))  # noqa: E731
    assert f((5, 1), (5, 2)) == 0 and f((5, 1), (5, 4)) == 2 and f((5, 2), (5, 2)) is None and f((5, 3), (5, 2)) is None
    assert f((5, 1), (6, 1)) is None  # a different parent: not a sibling
    assert M.gap(((2, 0),), ((2, 1),)) == 0  # 2 -> 2A
    assert M.gap(((2, 1),), ((2, 2),)) == 0  # 2A -> 2B
    assert M.gap(((2, 1),), ((3, 0),)) == 0 and M.gap(((2, 0),), ((3, 0),)) == 0 and M.gap(((2, 0),), ((3, 1),)) == 0
    assert M.gap(((7, 0),), ((8, 3),)) == 2
    assert M.succ(((5, 0), (1, 0))) == ((5, 0), (2, 0))


# ------------------------------------------------------------------------------------------------------------------ the parse
def test_chain_drops_an_out_of_order_number() -> None:
    """The longest-increasing-chain rule, as a property of the stack: 5.14. in the middle of 5.1 ... 5.3 is left out."""
    got = labels("5. Section", "5.1. one", "5.14. a stray number", "5.2. two", "5.3. three")
    assert got == ["5", "5.1", "5.2", "5.3"], got


def test_nested_numbers_and_skipped_levels() -> None:
    got = labels("1. Scope", "1.1. text.", "1.1.1. more.", "1.2. text.", "2. Definitions", "2.1.1. a missing level.", "2.2. next.")
    assert got == ["1", "1.1", "1.1.1", "1.2", "2", "2.1.1", "2.2"], got


def test_wrapped_reference_is_rejected() -> None:
    got = labels("6.3. Text that ends with a sentence.", "6.4. A rule as specified in paragraph", "6.5. of this Regulation shall apply.",
                 "6.6. The next real paragraph.")
    assert "6.5" not in got and got[:3] == ["6.3", "6.4", "6.6"], got


def test_a_paragraph_after_and_is_kept() -> None:
    got = labels("5.2.1. the vehicle to be steered, and", "5.2.2. the vehicle to be moved, or", "5.2.3. a third.")
    assert got == ["5.2.1", "5.2.2", "5.2.3"], got


def test_scope_restarts_numbering() -> None:
    got = labels("1. A", "2. B", head("Annex 1 First"), "1. X", "1.1. Y", "2. Z", head("Annex 2 Second"), "1. Again")
    assert got == ["1", "2", "Annex 1 1", "Annex 1 1.1", "Annex 1 2", "Annex 2 1"], got


def test_compound_scope_and_appendix_successor_at_body_size() -> None:
    """R101: Annex 7 - Appendix 3 is bold at body size; it is the successor of Appendix 2, so it is a scope (no font threshold)."""
    doc = _parse(raws(head("Annex 1 Zero"), head("Annex 1 - Appendix 1 First"), "1. A", "1.1. B", head("Annex 1 - Appendix 2 Second"), "1. C",
                      ("Annex 1 - Appendix 3 Third", True, BODY), "1. Introduction", "1.1. D"))
    got = [n.label for n in doc.nodes]
    assert "Annex 1 Appendix 3" in got and "Annex 1 Appendix 3 1.1" in got, got


def test_repeated_appendix_id_is_not_a_scope() -> None:
    """R49: 'Appendix 3 - Item 1' inside Annex 2 - Appendix 3 repeats an id; it is not a successor, so it is not a heading."""
    lines = [head("Annex 1 Prior"), head("Annex 2 Two"), head("Annex 2 - Appendix 1 One"), "1. A", head("Annex 2 - Appendix 2 Two"), "1. A2",
             head("Annex 2 - Appendix 3 Three"), "1. B"]
    lines += [("Appendix 3 - Item 1", True, BODY), "text of the item.", ("Appendix 3 - Item 2", True, BODY), "more text.", "2. C"]
    doc = _parse(raws(*lines))
    scopes = [n.label for n in doc.nodes if n.kind not in ("para", "table")]
    assert scopes[-3:] == ["Annex 2 Appendix 1", "Annex 2 Appendix 2", "Annex 2 Appendix 3"] and len(scopes) == 5, scopes
    assert [n.label for n in doc.nodes if n.kind == "para"][-1] == "Annex 2 Appendix 3 2"


def test_carry_on_part_is_a_divider() -> None:
    """R67/R89/R163: numbering that goes on after 'Part II' makes it a divider, not a scope."""
    doc = _parse(raws(head("PART I - First"), "1. A", "2. B", "5. B5", "5.1. C", head("PART II - Second"), "6. D", "6.1. E", head("PART III - Third"), "7. F"))
    para = [n.label for n in doc.nodes if n.kind == "para"]
    dividers = [(n.label, n.scope) for n in doc.nodes if n.kind == "part"]
    assert para == ["1", "2", "5", "5.1", "6", "6.1", "7"], para
    assert dividers == [("Part I", ""), ("Part II", ""), ("Part III", "")], dividers


def test_restarting_part_is_a_scope() -> None:
    doc = _parse(raws(head("Annex 1 First"), head("Part 1 - One"), "1. A", "2. B", head("Part 2 - Two"), "1. C", "1.1. D"))
    para = [n.label for n in doc.nodes if n.kind == "para"]
    assert para == ["Annex 1 Part 1 1", "Annex 1 Part 1 2", "Annex 1 Part 2 1", "Annex 1 Part 2 1.1"], para


def test_list_items_stay_in_their_paragraph() -> None:
    """Letters and romans are in the tree but not citable nodes: the paragraph keeps them and the next number closes them."""
    doc = _parse(raws("5.1. The system shall", "(a) first;", "(b) second:", "(i) one;", "(ii) two;", "(c) third.", "5.2. Next."))
    assert [n.label for n in doc.nodes] == ["5.1", "5.2"]
    assert doc.nodes[0].text == ["5.1. The system shall", "(a) first;", "(b) second:", "(i) one;", "(ii) two;", "(c) third."]


def test_ambiguous_i_picks_the_reading_the_context_wants() -> None:
    def kinds(*lines):
        raw = raws(*lines)
        cands, best = M._parse_stack(raw, BODY, 57.0)
        return {raw[cands[pos].idx].text[:5]: marker.segs[0].key for pos, kind, stack, marker in M._events(best.trail)}
    after_h = kinds("1. A", "(a) one;", "(b) two;", "(c) x;", "(d) x;", "(e) x;", "(f) x;", "(g) x;", "(h) two;", "(i) three;", "(j) four.")
    assert after_h["(i) t"] == "(a)", after_h  # a letter: h, i, j
    nested = kinds("1. A", "(a) one:", "(i) first;", "(ii) second;", "(b) two.")
    assert nested["(i) f"] == "(r)", nested  # a roman first child of (a)


def test_dotless_legend_numbers_are_rejected_but_a_section_heading_with_children_is_kept() -> None:
    got = labels("3. Text.", "12 RF absorber", "4 Test requirements", "4.1. Conditions.", "4.2. More.")
    assert got == ["3", "4", "4.1", "4.2"], got


def test_body_text_lines_are_not_headings() -> None:
    doc = _parse(raws(head("Annex 1 First"), "1. A", "Annex 5 to this Regulation shall apply.", "2. B"))
    assert [n.label for n in doc.nodes] == ["Annex 1", "Annex 1 1", "Annex 1 2"]


def test_footnote_mark_lines_are_not_paragraphs() -> None:
    lines = raws("5.1. Text with a mark.", "15This provision does not apply", "5.2. Next.")
    got = [n.label for n in _parse(lines).nodes]
    assert got == ["5.1", "5.2"], got


def test_label_policy_is_the_only_gold_specific_part() -> None:
    assert M.LABEL_POLICY["list_items"] == "inline" and "annex" in M.LABEL_POLICY["scope_keywords"]


# ------------------------------------------------------------------------------------------------------------------ the PDFs
def _pdf(regulation: str, role: str = "base"):
    path = corpus.pdf_path(corpus.entry_for(regulation), role)
    if path is None:
        raise Skip(f"{regulation} {role} not fetched")
    return path


class Skip(Exception):
    pass


def test_corpus_r101_appendix_3_without_the_rescue_rule() -> None:
    doc = M.parse_pdf(_pdf("UN R101"), grids=False, induce=False)
    labels_ = {n.label for n in doc.nodes}
    assert "Annex 7 Appendix 3" in labels_ and "Annex 7 Appendix 3 1.1" in labels_


def test_corpus_r49_item_lines_are_not_headings() -> None:
    doc = M.parse_pdf(_pdf("UN R49"), grids=False, induce=False)
    assert not [n for n in doc.nodes if n.kind not in ("para", "table") and "Item" in n.text[0][:40]]


def test_corpus_carry_on_parts_are_dividers() -> None:
    for regulation in ("UN R67", "UN R89", "UN R163"):
        doc = M.parse_pdf(_pdf(regulation), grids=False, induce=False)
        parts = [n for n in doc.nodes if n.kind == "part"]
        assert parts and all(n.scope == "" for n in parts), regulation
        assert not [n for n in doc.nodes if n.kind == "para" and n.label.startswith("Part ")], regulation


def test_corpus_matches_the_rules_parser_on_the_anchored_regulations() -> None:
    from collections import Counter
    for regulation in ("UN R150", "UN R148", "UN R48", "UN R175"):
        path = _pdf(regulation)
        a = Counter((n.label, n.page_start) for n in P.parse_pdf(path, grids=False).nodes)
        b = Counter((n.label, n.page_start) for n in M.parse_pdf(path, grids=False, induce=False).nodes)
        assert a == b, (regulation, list((a - b).items())[:3], list((b - a).items())[:3])


# ------------------------------------------------------------------------------------------------------------------ runner
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
    raise SystemExit(run(globals(), sys.argv[1:]))
