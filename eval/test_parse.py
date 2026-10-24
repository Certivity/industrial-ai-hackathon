#!/usr/bin/env python3
"""Tests of src/regcomp/parse.py: the pure functions without a PDF, then the rules as they show on the fetched regulations.

    python eval/test_parse.py            # unit tests, then the corpus tests if regulations/data has the PDFs
    python eval/test_parse.py --unit     # unit tests only, a second
    python -m pytest eval/test_parse.py  # the same functions under pytest (not required; pytest is not a dependency)

eval/anchors.py says that every expert label is on the right page, and eval/fidelity.py that the numbers of the expert
requirements are in the parsed text. These tests pin the rules those two cannot see, each with the case that made it:

  unit      the paragraph-number chain, wrapped references, unstyled headings, superscripts, the table-grid builder
  corpus    R150 Table 3 and Table A6-1 and R10 6.9.1 read as rows, the colour tables R48 draws without a caption (the neural
            layout gate of PyMuPDF 2 drops one of them), no fused exponent in R150 and R148, R10 Annex 5 keeps its heading

Plain functions named test_*; a failed assert is a failure, regcomp's Skip is a skip. The runner below is all that is needed.
"""

from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from regcomp import corpus  # noqa: E402
from regcomp import parse as P  # noqa: E402
from regcomp.parse import Node, ParsedDocument, _Line, _Piece  # noqa: E402


class Skip(Exception):
    pass


def skip(reason: str) -> None:
    try:
        import pytest
    except ImportError:
        raise Skip(reason)
    pytest.skip(reason)


# ------------------------------------------------------------------------------------------------------------ helpers
def lines_of(*texts: str, bold: bool = False, size: float = 10.5) -> list[_Line]:
    return [_Line(i, 1, t, bold, size, 0, None, (0.0, 10.0 * i, 100.0, 10.0 * i + 9)) for i, t in enumerate(texts)]


def starts_of(*texts: str, bold: bool = False) -> tuple[list[str], ParsedDocument]:
    """The lines that `_paragraph_starts` accepts as paragraph starts, in order, and the document with its counters."""
    doc = ParsedDocument(path=Path("t.pdf"), pages=1)
    doc.body_size = 10.5
    lines = lines_of(*texts, bold=bold)
    starts = P._paragraph_starts(lines, [""], doc)
    return [lines[i].text for i in sorted(starts)], doc


def node(label: str, text: list[str], pages: list[int], num: tuple[int, ...] = (), kind: str = "para") -> Node:
    return Node(kind, label, "", num, pages[0], pages[-1], text, pages)


# ------------------------------------------------------------------------------------------- the chain and the starts
def test_the_longest_chain_drops_numbers_that_only_look_like_paragraphs():
    items = [(0, (5,), True), (1, (5, 1), True), (2, (5, 2), True), (3, (1,), True), (4, (5, 3), True)]
    assert [idx for idx, _, _ in P._longest_chain(items)] == [0, 1, 2, 4]


def test_the_chain_does_not_need_consecutive_numbers():
    items = [(0, (6,), True), (1, (6, 1, 1), True), (2, (6, 2), True)]  # R150 goes from 6. straight to 6.1.1.
    assert [num for _, num, _ in P._longest_chain(items)] == [(6,), (6, 1, 1), (6, 2)]


def test_on_equal_length_the_dotted_number_wins():
    items = [(0, (3,), False), (1, (3,), True)]
    assert [idx for idx, _, _ in P._longest_chain(items)] == [1]


def test_a_numbered_line_after_the_word_paragraph_continues_a_reference():
    # without the rule 6.4 would join the chain (6, 6.1, 6.4) and take the place of the real 6.2
    found, doc = starts_of("6. Specifications", "6.1. As set out in paragraph", "6.4. of this Regulation, no value", "6.2. Second")
    assert found == ["6. Specifications", "6.1. As set out in paragraph", "6.2. Second"]
    assert doc.wrapped == [(1, "6.4. of this Regulation, no value", "")]


def test_wraps_reference_only_on_the_word_paragraph():
    assert P.wraps_reference("specified in paragraph")
    assert P.wraps_reference("the requirements of paragraphs")
    assert not P.wraps_reference("as set out in paragraph 6.4.")
    assert not P.wraps_reference("the lamp shall be red and")  # "and" ends real list items too (R13H 5.2.21.3.3)
    assert not P.wraps_reference("")


def test_an_unstyled_heading_without_its_dot_is_kept_when_its_first_paragraph_follows():
    found, _ = starts_of("4 Test requirements", "4.1. The limits apply", "4.2. Measure")  # R10 Annex 5
    assert found == ["4 Test requirements", "4.1. The limits apply", "4.2. Measure"]


def test_a_figure_legend_or_a_value_is_not_a_start():
    found, _ = starts_of("12 RF absorber material", "13 Ground plane", "60 V/m", "5.1. A paragraph")
    assert found == ["5.1. A paragraph"]


def test_a_bold_heading_without_its_dot_is_a_start():
    found, _ = starts_of("1 Scope", "2 Definitions", bold=True)  # R148 has no dot after 1
    assert found == ["1 Scope", "2 Definitions"]


def test_opens_section():
    assert P.opens_section((4,), (4, 1))
    assert P.opens_section((4, 1), (4, 1, 1))
    assert not P.opens_section((4,), (5,))
    assert not P.opens_section((4,), (4,))
    assert not P.opens_section((4,), None)


def test_a_table_cell_number_inside_a_scope_does_not_break_the_chain():
    found, _ = starts_of("5.1. First", "5.2. Second", "5.1. a cell", "5.3. Third")
    assert found == ["5.1. First", "5.2. Second", "5.3. Third"]


# --------------------------------------------------------------------------------------------- headings and labels
def test_scope_headings():
    assert P.ANNEX_APPENDIX.match("Annex 4 – Appendix 1").groups() == ("4", "1")  # en dash
    assert P.ANNEX_APPENDIX.match("ANNEX 3 - APPENDIX 1").groups() == ("3", "1")
    assert P.ANNEX.match("Annex 2A Photometric").group(1) == "2A"
    assert P.ANNEX.match("Annex 1a").group(1) == "1a"
    assert P.APPENDIX.match("Appendix 1 List of standards").group(1) == "1"
    for heading, part in (("Part 1 - Photometric", "1"), ("Part A: Position", "A"), ("Part B. Test", "B"), ("Part I - Scope", "I"),
                          ("Part 1 Essential requirements", "1"), ("Part of the lamp", None), ("Parts A and B", None),
                          ("Part 1", None)):  # a bare id with no title after it is not taken for a heading
        match = P.PART.match(heading)
        assert (match.group(1) if match else None) == part, heading


def test_table_captions_are_not_mentions():
    assert P.TABLE.match("Table 3 Requirements for RI values").group(1) == "3"
    assert P.TABLE.match("Table A6-1 Weathering").group(1) == "A6-1"
    assert P.TABLE.match("Table 2a").group(1) == "2a"  # bold alone is a caption; _build_nodes checks the weight
    assert P.TABLE.match("Table 3 shows the values") is None


def test_labels():
    assert P.scope_label("4", None, "1") == "Annex 4 Part 1"
    assert P.scope_label(None, "2", None) == "Appendix 2"
    assert P.scope_label(None, None, None) == ""
    assert P.make_label("", (3, 3, 1, 1)) == "3.3.1.1"
    assert P.make_label("Annex 4 Part 1", (1, 2)) == "Annex 4 Part 1 1.2"


def test_join_lines_joins_at_a_hyphen_without_a_space():
    assert P.join_lines(["Table A6-", "1: weathering"]) == "Table A6-1: weathering"
    assert P.join_lines(["wrapped", "line"]) == "wrapped line"


def test_a_list_dash_is_not_a_wrapped_hyphen():
    # R3 Annex 12 sets "- Heat: 48 h" as a '-' on a line of its own, then the item; a spaced dash ends a line the same way
    assert P.join_lines(["Tests:", "-", "Heat: 48 h", "-", "Colorimetry"]) == "Tests: - Heat: 48 h - Colorimetry"
    assert P.join_lines(["Colour -", "red"]) == "Colour - red"
    assert P.join_lines(["mirror-", "backed"]) == "mirror-backed"
    assert P.join_lines(["20-", "30 km/h"]) == "20-30 km/h"
    assert P.wrapped_at_hyphen("Table A6-") and not P.wrapped_at_hyphen("-") and not P.wrapped_at_hyphen("a -")


def test_page_of_gives_the_page_of_the_line_where_the_quote_starts():
    n = node("1", ["a b-", "c d", "e"], [1, 1, 2])
    assert n.body == "a b-c d e"
    assert (n.page_of("c d"), n.page_of("e"), n.page_of("absent")) == (1, 2, None)


def test_page_of_agrees_with_body_about_a_list_dash():
    n = node("1", ["Tests:", "-", "Heat: 48 h", "x-", "y"], [1, 1, 2, 2, 3])
    assert n.body == "Tests: - Heat: 48 h x-y"
    assert (n.page_of("Heat"), n.page_of("- Heat"), n.page_of("x-y")) == (2, 1, 2)


def test_a_restart_counts_a_left_out_one_with_a_sentence_and_a_second_item_behind_it():
    _, doc = starts_of("1. First paragraph of the text", "1.1. A sub paragraph of the text", "2. Second paragraph of the text",
                       "1.", "2.",  # table cells: a "2." behind the "1.", but no sentence after the number
                       "1. Additional information:...............", "2. Other information:...............",  # form fields with leaders
                       "1. Performance of electrical storage devices", "2. Capacity of the electrical supply")
    assert [r[1] for r in doc.restarts] == ["1. Performance of electrical storage devices"]
    _, before = starts_of("1. Performance of electrical storage devices", "2. Second paragraph of the text")  # nothing has passed 1 yet
    assert before.restarts == []
    _, form = starts_of("1. First paragraph of the text", "2. Second paragraph of the text", "3. Third paragraph of the text",
                        "1. Additional information (where applicable): see addendum")  # a form field: nothing goes on behind it
    assert form.restarts == [] and len(form.left_out) == 1


def test_a_missing_space_after_the_dot_still_starts_a_paragraph():
    # R162 5.1.2 and R48 6.3.6.1.2.2 print "5.1.2.An immobilizer ...": of the 47 lines of the base PDFs that start "<number>.<letter>", the
    # capital-then-lower-case form made 8 nodes (R162 2, R83 3, R48, R49, R100) and the rest ("4.a. Detected", "2.x.", "3.1.(A)") stay out
    found, _ = starts_of("5.1.1. First", "5.1.2.An immobilizer and its installation", "5.1.3. Third")
    assert found == ["5.1.1. First", "5.1.2.An immobilizer and its installation", "5.1.3. Third"]
    assert P.DOTTED.match("5.1.2.An immobilizer").group(1) == "5.1.2"
    assert not P.DOTTED.match("5.1.2.5 mm") and not P.DOTTED.match("3.5.mm") and not P.DOTTED.match("1.2.a)")


# ------------------------------------------------------------------------------------------ scopes from raw lines
BODY = 10.5


def raws_of(*items: tuple[str, bool, float]) -> list[P._Raw]:
    """Raw lines (text, bold, size) as `_raw_lines` makes them, one page, every line at x = 57."""
    return [P._Raw(1, text, bold, size, (57.0, 10.0 * i, 400.0, 10.0 * i + 9)) for i, (text, bold, size) in enumerate(items)]


def scopes_of(*items: tuple[str, bool, float]) -> tuple[list[tuple[str, str, str]], ParsedDocument]:
    """The headings `_scope_lines` finds, as (first 22 characters of the line, kind, scope), and the document that counted what it refused."""
    doc = ParsedDocument(path=Path("t.pdf"), pages=1)
    doc.body_size = BODY
    lines, scopes = P._scope_lines(raws_of(*items), BODY, doc)
    return [(line.text[:22], line.heading, scopes[line.scope]) for line in lines if line.heading], doc


def parsed_from(*items: tuple[str, bool, float]) -> ParsedDocument:
    """The whole text pipeline of parse_pdf on raw lines: scopes, starts, nodes, tree."""
    doc = ParsedDocument(path=Path("t.pdf"), pages=1)
    doc.body_size = BODY
    lines, scopes = P._scope_lines(raws_of(*items), BODY, doc)
    starts = P._paragraph_starts(lines, scopes, doc)
    P._build_nodes(lines, scopes, starts, doc)
    P._link_tree(doc)
    return doc


T = lambda text: (text, False, BODY)  # noqa: E731  a text line
H = lambda text: (text, True, 13.0)  # noqa: E731  a heading the size test takes
B = lambda text, size=BODY: (text, True, size)  # noqa: E731  a bold line at body size: the size test refuses it

APPENDIX_2 = [H("Annex 7 - Appendix 2 Alternative procedure"), T("1. Introduction"), T("1.1. The first text"), T("2. Procedure"), T("2.1. More")]


def test_a_bold_appendix_at_body_size_opens_a_scope_when_the_numbering_restarts_after_it():
    # R101 Annex 7 Appendix 3: bold, but 10.5 pt where Appendices 1 and 2 are 13 pt; its "1. Introduction" restarts the numbering
    found, doc = scopes_of(*APPENDIX_2, B("Annex 7 - Appendix 3 Determination of REESS current"), T("1. Introduction"), T("1.1. This appendix"))
    assert found == [("Annex 7 - Appendix 2 A", "annex-appendix", "Annex 7 Appendix 2"),
                     ("Annex 7 - Appendix 3 D", "annex-appendix", "Annex 7 Appendix 3")]
    assert doc.scope_rejects == []


def test_a_bold_appendix_whose_id_follows_the_scope_opens_one_without_a_restart():
    found, _ = scopes_of(*APPENDIX_2, B("Annex 7 - Appendix 3 Determination of REESS current"), T("5. Something else"))
    assert [kind for _, kind, scope in found] == ["annex-appendix", "annex-appendix"] and found[1][2] == "Annex 7 Appendix 3"


def test_a_bold_appendix_whose_id_does_not_follow_opens_one_when_only_the_numbering_restarts():
    found, doc = scopes_of(*APPENDIX_2, B("Annex 7 - Appendix 5 Determination of REESS current"), T("1. Introduction"))
    assert len(found) == 2 and found[1][2] == "Annex 7 Appendix 5" and doc.scope_rejects == []


def test_a_restart_needs_the_scope_to_have_passed_one():
    # nothing but a "1." before the heading: a form numbered from 1, not a scope that ended
    found, doc = scopes_of(H("Annex 7 - Appendix 2 Alternative procedure"), T("1. Introduction"),
                           B("Annex 7 - Appendix 5 Determination of REESS current"), T("1. Introduction"))
    assert len(found) == 1 and [r[3] for r in doc.scope_rejects] == ["no evidence"]


def test_a_bold_line_that_shows_neither_restart_nor_successor_is_refused_and_counted():
    found, doc = scopes_of(*APPENDIX_2, B("Annex 7 - Appendix 5 Determination of REESS current"), T("5. Something else"))
    assert len(found) == 1 and [r[3] for r in doc.scope_rejects] == ["no evidence"] and len(doc.unexplained_rejects) == 1


def test_a_line_that_repeats_the_id_of_its_scope_never_opens_one():
    # R49 Annex 9B Appendix 3 labels its items "Appendix 3 - Item 1"; the numbering does restart inside each of them
    found, doc = scopes_of(H("Annex 9B - Appendix 3 Documentation"), T("1. First"), T("1.1. Text"), T("2. Second"),
                           B("Appendix 3 - Item 1"), T("1. In the case where"), T("2. Another"))
    assert len(found) == 1 and [r[3] for r in doc.scope_rejects] == ["same id"] and doc.unexplained_rejects == []


def test_what_does_not_look_like_a_heading_is_refused_with_its_reason():
    for line, why in ((B("Annex 7 - Appendix 3 Determination of REESS current", 9.0), "small"),  # a footnote
                      (B("Annex 7 - Appendix 3 Determination of REESS current."), "sentence"),
                      (B("Annex 7 - Appendix 3 Determination of REESS current and REESS voltage of plug-in electric vehicles, as set out in the text of this regulation"), "long"),
                      (B("Annex 8 to this Regulation"), "lowercase")):  # a reference in running text (R149 "Annex 5 to this")
        found, doc = scopes_of(*APPENDIX_2, line, T("1. Introduction"))
        assert len(found) == 1 and [r[3] for r in doc.scope_rejects] == [why], (line, doc.scope_rejects)


def test_a_line_that_is_not_bold_never_opens_a_scope():
    found, doc = scopes_of(*APPENDIX_2, T("Annex 7 - Appendix 3 Determination of REESS current"), T("1. Introduction"))
    assert len(found) == 1 and doc.scope_rejects == []


def test_next_ids_of_annexes_and_appendices():
    assert P._next_ids(None) == {"1"} and "3" in P._next_ids("2") and "2B" in P._next_ids("2A") and "10" in P._next_ids("9")
    assert P._next_ids("X") == set()


def test_the_nodes_of_a_rescued_appendix_get_its_scope_in_their_labels_and_the_tree():
    doc = parsed_from(H("Annex 7 Road load determination"), *APPENDIX_2, B("Annex 7 - Appendix 3 Determination of REESS current"),
                      T("1. Introduction"), T("1.1. This Appendix defines the method"), T("2. Method"))
    by_label = {n.label: n for n in doc.nodes}
    assert "Annex 7 Appendix 3 1.1" in by_label and "Annex 7 Appendix 2 1.1" in by_label
    assert by_label["Annex 7 Appendix 3 1.1"].body.startswith("1.1. This Appendix defines")
    assert [n.label for n in doc.orphans] == []
    inner = by_label["Annex 7 Appendix 3 1.1"]
    assert doc.nodes[inner.parent].label == "Annex 7 Appendix 3 1"
    assert doc.nodes[doc.nodes[inner.parent].parent].label == "Annex 7 Appendix 3"
    assert doc.nodes[doc.nodes[doc.nodes[inner.parent].parent].parent].label == "Annex 7"
    assert inner.path.startswith("Annex 7 Road load") and inner.path.endswith("› 1 Introduction › 1.1") and "Appendix 3" in inner.path


# ----------------------------------------------------------------------------------------------------- parts and dividers
def test_a_top_level_part_that_carries_on_the_numbering_is_a_divider():
    # R89 and R163: "Part I" starts at 5 after 4.x, "Part II" at 9 after 8.x; the paragraphs are cited as printed
    doc = parsed_from(T("1. Scope"), T("4. Definitions"), T("4.1. A term"), H("Part I - Approval of alarm systems"), T("5. General"),
                      T("5.1. Text"), T("8. Marking"), H("Part II - Approval of a vehicle"), T("9. Fitting"), T("9.1. Text"))
    assert [n.label for n in doc.nodes if n.kind == "para"] == ["1", "4", "4.1", "5", "5.1", "8", "9", "9.1"]
    parts = [n for n in doc.nodes if n.kind == "part"]
    assert [(n.label, n.scope, n.parent) for n in parts] == [("Part I", "", -1), ("Part II", "", -1)]
    assert {n.scope for n in doc.nodes} == {""}


def test_a_top_level_part_that_starts_the_numbering_over_is_a_scope():
    doc = parsed_from(T("1. Scope"), T("2. Text"), T("3. More"), H("Part II - Approval of a vehicle"), T("1. Scope"), T("2. Text"))
    assert [n.label for n in doc.nodes if n.kind == "para"] == ["1", "2", "3", "Part II 1", "Part II 2"]
    assert next(n for n in doc.nodes if n.kind == "part").scope == "Part II"


def test_a_part_inside_an_annex_stays_a_scope():
    found, _ = scopes_of(H("Annex 4 Tests"), T("1. Text"), H("Part A: Position lamps"), T("1. Text"))
    assert found[-1] == ("Part A: Position lamps", "part", "Annex 4 Part A")


# ------------------------------------------------------------------------------------------------ text, hash and the tree
def test_structured_lines_break_before_list_items_and_footnotes_only():
    assert P.structured_lines(["5.1. The lamp:", "(a) is red;", "(b) is amber", "or white;", "(i) a", "-", "Heat: 48 h", "wraps on"]) == [
        "5.1. The lamp:", "(a) is red;", "(b) is amber or white;", "(i) a", "- Heat: 48 h wraps on"]
    assert P.structured_lines(["text", "1Note", "goes on", "text again"], [0, 1, 2, 0]) == ["text", "1Note goes on", "text again"]
    assert P.structured_lines(["a hyphen-", "ated word"]) == ["a hyphen-ated word"]


def test_the_hash_ignores_the_number_and_the_flow_of_a_paragraph_but_not_its_words():
    a = node("5.1", ["5.1. The lamp shall be", "red."], [1, 1], (5, 1))
    assert a.text_hash == node("6.2", ["6.2. The lamp shall be red."], [1], (6, 2)).text_hash
    assert a.text_hash != node("5.1", ["5.1. The lamp shall be amber."], [1], (5, 1)).text_hash
    inline = node("5.1", ["5.1. Lamps: (a) red; (b) amber or", "white."], [1, 1], (5, 1))
    listed = node("5.1", ["5.1. Lamps:", "(a) red;", "(b) amber or white."], [1, 1, 1], (5, 1))
    assert inline.text_hash == listed.text_hash  # a list set inline or one item to a line is the same paragraph
    assert inline.text_hash != node("5.1", ["5.1. Lamps: (a) red; (b) white."], [1], (5, 1)).text_hash


def test_the_hash_ignores_a_footnote_mark_and_number_but_keeps_an_exponent_and_the_footnote_text():
    def with_note(mark: str, number: str, power: str = "²", text: str = "This provision does not apply.") -> Node:
        n = node("5.1", [f"5.1. Shall not exceed 10{power} cd{mark}", f"{number}{text}"], [1, 1], (5, 1))
        n.note = [0, 1]
        return n
    assert with_note("¹", "1").text_hash == with_note("²", "2").text_hash == with_note("¹⁵", "15").text_hash  # renumbered in a new version
    assert with_note("¹", "1").text_hash != with_note("¹", "1", power="³").text_hash  # 10² is not 10³ (the mark is not the exponent)
    assert with_note("¹", "1").text_hash != with_note("¹", "1", text="This provision applies.").text_hash  # footnote text is binding


def test_model_text_has_a_table_once():
    n = node("6.9.1", ["6.9.1. Test pulses", "Pulse", "1", "500 pulses", "after the table"], [1] * 5, (6, 9, 1))
    n.grid, n.table_lines = "| Pulse | Number |\n| --- | --- |\n| 1 | 500 pulses |", [1, 2, 3]
    assert n.model_text == "6.9.1. Test pulses after the table\n\n" + n.grid
    assert n.body.count("500 pulses") == 1 and n.model_text.count("500 pulses") == 1
    n.grid, n.table_lines = None, []
    assert n.model_text == n.structured


def test_title_and_heading_are_the_first_words_without_the_number():
    n = node("6.10", ["6.10. Rear position lamps", "(a) text"], [1, 1], (6, 10))
    assert n.title() == "Rear position lamps (a) text" and n.title(10) == "Rear posit" and n.heading == n.title(90)


def test_title_joins_only_the_lines_it_needs_and_still_equals_the_start_of_the_body():
    # an annex heading holds pages of text and every node under it asks for its title (R49: 2.5 s became 5.4 s when it joined them all)
    lines = ["3.2.12.2.6.4.1. A well-", "known lamp shall", *[f"line {i} of the text with some words in it-" if i % 7 == 0 else f"line {i} of the text" for i in range(400)]]
    n = node("3.2.12.2.6.4.1", lines, [1] * len(lines), (3, 2, 12, 2, 6, 4, 1))
    for width in (10, 60, 70, 90, 500):
        assert n.title(width) == P.NUMBER_PREFIX.sub("", n.body)[:width], width
    assert n.title(20) == "A well-known lamp sh"


def test_orphans_are_paragraphs_whose_parent_number_is_missing():
    doc = ParsedDocument(path=Path("t.pdf"), pages=1)
    doc.nodes = [node("4.1", ["4.1. a"], [1], (4, 1)), node("4.2", ["4.2. b"], [1], (4, 2)),
                 node("5", ["5. c"], [1], (5,)), node("5.1", ["5.1. d"], [1], (5, 1))]
    assert [n.label for n in doc.orphans] == ["4.1", "4.2"]


# --------------------------------------------------------------------------------------------------- superscripts
def test_superscript_spans_are_written_raised():
    raised = lambda text, flags=1: P.span_text({"text": text, "flags": flags})  # noqa: E731
    assert raised("3") == "³"
    assert raised("-1") == "⁻¹"
    assert raised("−2") == "⁻²"  # the typographic minus
    assert raised(" 2 ") == " ² "  # the spaces around a mark are kept, or it fuses with the next word
    assert raised("10", flags=4) == "10"  # not a superscript
    assert raised("th") == "th" and raised("TM") == "TM"  # ordinal and trademark letters stay letters


def test_a_power_of_ten_does_not_fuse_into_its_base():
    spans = [{"text": "3.00∙10", "flags": 4}, {"text": "2", "flags": 5}, {"text": " cd", "flags": 4}]
    assert "".join(P.span_text(s) for s in spans) == "3.00∙10² cd"


# ------------------------------------------------------------------------------------------------------ table grids
def test_cell_text_puts_a_sign_printed_as_its_own_span_in_front():
    spans = [(22.0, 5.0, (0, 0), 14.0, "75 V"), (12.0, 5.0, (0, 0), 10.0, "-")]  # the stream has the sign last
    assert P._cell_text(spans, (0, 0, 30, 10)) == "-75 V"


def test_cell_text_joins_lines_top_to_bottom_and_at_hyphens():
    spans = [(10.0, 8.0, (0, 1), 2.0, "divergence"), (10.0, 3.0, (0, 0), 2.0, "Angle of"),
             (10.0, 18.0, (0, 2), 2.0, "Table A6-"), (10.0, 24.0, (0, 3), 2.0, "1")]
    assert P._cell_text(spans, (0, 0, 20, 12)) == "Angle of divergence"
    assert P._cell_text(spans, (0, 14, 20, 30)) == "Table A6-1"


def test_cell_text_ignores_spans_outside_the_cell():
    assert P._cell_text([(50.0, 5.0, (0, 0), 48.0, "elsewhere")], (0, 0, 30, 10)) == ""


def test_grid_rows_repeat_a_row_span_and_write_a_column_span_once():
    cells = [(0, 0, 10, 10), (10, 0, 30, 10),  # "Class" and a header "Angles" over two columns
             (0, 10, 10, 30), (10, 10, 20, 20), (20, 10, 30, 20),  # the key "IA" spans two rows
             (10, 20, 20, 30), (20, 20, 30, 30)]
    spans = [(5.0, 5.0, (0, 0), 1.0, "Class"), (20.0, 5.0, (0, 1), 12.0, "Angles"), (5.0, 20.0, (0, 2), 1.0, "IA"),
             (15.0, 15.0, (0, 3), 11.0, "1"), (25.0, 15.0, (0, 4), 21.0, "2"),
             (15.0, 25.0, (0, 5), 11.0, "3"), (25.0, 25.0, (0, 6), 21.0, "4")]
    assert P._grid_rows(cells, spans) == [["Class", "Angles", ""], ["IA", "1", "2"], ["IA", "3", "4"]]


def test_nearby_cell_edges_are_one_edge():
    cells = [(0, 0, 10, 10), (10.4, 0, 20, 10), (0, 10.3, 10, 20), (10.2, 10, 20, 20)]  # drawn rulings are not exactly aligned
    assert len(P._grid_rows(cells, []) ) == 2 and len(P._grid_rows(cells, [])[0]) == 2


def test_markdown_escapes_the_pipe_and_adds_a_separator():
    assert P._markdown([["a", "b|c"], ["1", "2"]]) == "| a | b\\|c |\n| --- | --- |\n| 1 | 2 |"


def _piece(page: int, top: float, bottom: float, rows: list[list[str]], columns: list[float] | None = None) -> _Piece:
    width = len(rows[0])
    columns = columns or [50.0 + 490.0 * i / width for i in range(width + 1)]  # evenly spaced rulings
    return _Piece(page, 842.0, (50.0, top, 540.0, bottom), rows, columns)


def test_a_table_cut_by_a_page_break_is_one_grid_and_a_repeated_header_is_dropped():
    first = _piece(12, 640, 780, [["Class", "Colour"], ["IA", "Red"]])
    second = _piece(13, 60, 200, [["Class", "Colour"], ["IIIA", "Amber"]])  # the header comes again
    assert P._render([first, second]) == P._markdown([["Class", "Colour"], ["IA", "Red"], ["IIIA", "Amber"]])


def test_a_header_that_the_next_page_does_not_repeat_stays_on_top():
    first = _piece(12, 640, 780, [["Class", "Colour"]])
    second = _piece(13, 60, 200, [["IA", "Red"]])
    assert P._render([first, second]) == P._markdown([["Class", "Colour"], ["IA", "Red"]])


def test_tables_that_only_follow_each_other_stay_apart():
    a = _piece(12, 100, 300, [["a", "b"]])
    for other in (_piece(12, 400, 500, [["c", "d"]]),  # same page
                  _piece(14, 60, 200, [["c", "d"]]),  # not the next page
                  _piece(13, 60, 200, [["c", "d", "e"]]),  # other columns
                  _piece(13, 500, 600, [["c", "d"]])):  # not at the head of the page
        assert P._render([a, other]).count("\n\n") == 1
    low = _piece(12, 640, 780, [["a", "b"]])
    assert P._render([low, _piece(13, 60, 200, [["c", "d"]])]).count("\n\n") == 0


def test_two_tables_with_as_many_columns_but_not_the_same_ones_stay_apart():
    # R48 2.11.2.3: the colour boundaries at the foot of page 14, their intersection points at the head of page 15
    boundaries = _piece(14, 654, 750, [["A12", "green boundary", "y = 1.417 x - 0.347"]], [57.0, 80.0, 156.0, 238.0])
    points = _piece(15, 63, 180, [["", "x", "y"], ["A1", "0.545", "0.425"]], [57.0, 79.0, 108.0, 138.0])
    assert P._render([boundaries, points]).count("\n\n") == 1
    shifted = _piece(15, 63, 180, [["", "x", "y"]], [57.0, 80.5, 156.5, 238.5])  # rulings a point off are the same rulings
    assert P._render([boundaries, shifted]).count("\n\n") == 0


def test_the_owner_of_a_box_is_the_node_that_holds_most_of_its_lines():
    lines = lines_of("a", "b", "c", "d")  # centres at y = 4.5, 14.5, 24.5, 34.5
    owners = [7, 9, 9, 12]
    assert P._owner_of((0, 10, 100, 30), lines, owners) == 9
    assert P._owner_of((0, 100, 100, 130), lines, owners) is None
    assert P._owner_of((0, 0, 100, 40), lines, [-1, -1, -1, 12]) == 12  # front matter does not vote


# --------------------------------------------------------------------------------------------------------- corpus
def _parse(regulation: str, grids: bool = True) -> ParsedDocument:
    pdf = corpus.pdf_path(corpus.entry_for(regulation), "base")
    if pdf is None:
        skip(f"{regulation}: the base PDF is not in regulations/data (python tools/fetch_regulations.py --role base --out regulations/data)")
    return P.parse_pdf(pdf, grids=grids)


def _rows(grid: str | None) -> list[str]:
    return (grid or "").splitlines()


def _find(doc: ParsedDocument, label: str) -> Node:
    return next(n for n in doc.nodes if n.label == label)


def test_corpus_r150_table_3_reads_as_rows_over_the_page_break():
    table = _find(_parse("UN R150"), "5.1.4.4.1. Table 3")
    rows = _rows(table.grid)
    assert (table.page_start, table.page_end) == (12, 13)
    assert "| IA, IB | Red | Angle of divergence α | 20' | 3.00∙10² | 2.00∙10² | 1.00∙10² | -- | -- | -- |" in rows  # G-0029
    assert "| IA, IB | Red | Angle of divergence α | 1°30' | 5∙10⁰ | 2.8∙10⁰ | 2.5∙10⁰ | -- | -- | -- |" in rows
    first = next(i for i, r in enumerate(rows) if r.startswith("| IA, IB | White |"))
    assert "Minimum requirements for RI values in mcd∙lx⁻¹" in rows[first - 1]  # the page 12 header is the page 13 rows' own: one grid
    assert sum(1 for r in rows if "Angle of divergence" in r) == 18
    assert (table.grid or "").count("\n\n") == 1  # only the note under the table, a 1 x 2 box of its own, is set apart


def test_corpus_r150_table_a6_1_joins_pages_46_and_47():
    table = _find(_parse("UN R150"), "Annex 6 Part 6 3. Table A6-1")
    assert (table.page_start, table.page_end) == (46, 47)
    text = table.grid or ""
    assert "TM1 - Black-standard thermometer" in text and "TM2 - Black-panel thermometer" in text
    assert "| 1 | 102 min dry 18 min water spray |" in text and "| 4 | 102 min dry 18 min water spray |" in text


def test_corpus_r10_6_9_1_has_the_test_pulses_although_its_tables_have_no_caption_line():
    node_ = _find(_parse("UN R10"), "6.9.1")
    rows = _rows(node_.grid)
    for row in ("| 1 | -75 V | -450 V | 500 pulses | III | III |", "| 2a | +37 V | +37 V | 500 pulses | I | III |",
                "| 2b | +10 V | +20 V | 10 pulses | II | III |", "| 3a | -112 V | -150 V | 1 h | I | III |",
                "| 3b | +75 V | +150 V | 1 h | I | III |"):
        assert row in rows, row


def test_corpus_r48_colour_tables_are_found_without_the_layout_gate():
    # R48 draws these without a caption. PyMuPDF 2's neural layout gate returns nothing for the intersection points at the
    # head of page 15 (the A1 to A4 coordinates of "Amber"), and they sit on a different set of rulings than the boundaries
    # above them on page 14, so the node holds two tables
    doc = _parse("UN R48")
    amber = _find(doc, "2.11.2.3")
    assert (amber.grid or "").count("\n\n") == 1
    assert "| A1 | 0.545 | 0.425 |" in amber.grid and "| A41 | white boundary | y = 0.790 - 0.670 x |" in amber.grid
    assert any("| W1 | 0.300 | 0.270 |" in (n.grid or "") for n in doc.nodes)
    assert doc.loose_grids == 0 and not doc.grid_errors


def test_corpus_exponents_are_not_fused_into_their_base():
    fused = re.compile(r"∙10(?=\d)")
    for regulation in ("UN R150", "UN R148"):  # R149 has 7 in its source: "9.00∙102 cd" is plain digits in the text layer
        doc = _parse(regulation, grids=False)
        assert not [n.label for n in doc.nodes if fused.search(n.body)], regulation
    assert "1.20∙10³" in _find(_parse("UN R150", grids=False), "5.1.4.4.1. Table 3").body


def test_corpus_r10_annex_5_keeps_its_unstyled_heading_4():
    doc = _parse("UN R10", grids=False)
    heading = _find(doc, "Annex 5 4")
    assert heading.body.startswith("4 Test requirements")
    assert not [n.label for n in doc.orphans if n.scope == "Annex 5"]


def test_corpus_a_wrapped_reference_is_not_a_paragraph():
    doc = _parse("UN R19", grids=False)  # Annex 2: "... according to paragraph / 6.4. of this Regulation, no measured value ..."
    assert not [n for n in doc.nodes if n.label == "Annex 2 6.4" and n.body.startswith("6.4. of this Regulation")]
    assert any(item[1].startswith("6.4. of this Regulation") for item in doc.wrapped)


def test_corpus_grids_can_be_skipped():
    doc = _parse("UN R150", grids=False)
    assert not doc.grids_built and doc.grids == 0 and all(n.grid is None for n in doc.nodes)
    assert _parse("UN R150").grids_built


def test_corpus_r101_appendix_3_is_a_scope_of_its_own():
    # bold at body size where Appendices 1 and 2 are 13 pt: the size test alone left its paragraphs in Appendix 2 (found by DeepSeek's
    # ds-phev-reess, which cited "Annex 7 Appendix 3 1.2" where our node was "Annex 7 Appendix 2 1.2")
    doc = _parse("UN R101", grids=False)
    inner = next(n for n in doc.nodes if n.body.startswith("1.1. This Appendix defines the method and required instrumentation to determine the REESS current"))
    assert (inner.scope, inner.label) == ("Annex 7 Appendix 3", "Annex 7 Appendix 3 1.1")
    assert any(n.label == "Annex 7 Appendix 3 1" and n.body.startswith("1. Introduction") for n in doc.nodes)
    assert "Annex 7 Appendix 2 2.2.4" in {n.label for n in doc.nodes}  # Appendix 2's own 2.2.4 (page 71) was left out of its chain before
    assert doc.unexplained_rejects == [] and {r[3] for r in doc.scope_rejects} <= {"same id"}


def test_corpus_parts_that_carry_on_the_numbering_are_not_in_the_labels():
    for regulation, label in (("UN R89", "21.1.2.1"), ("UN R163", "5.1")):  # R89: Part III holds 19-26; R163: Part I holds 5-8
        doc = _parse(regulation, grids=False)
        assert _find(doc, label).scope == "" and not [n for n in doc.nodes if n.kind == "para" and n.scope.startswith("Part")], regulation
        dividers = [n for n in doc.nodes if n.kind == "part"]
        assert dividers and all(n.scope == "" and n.parent == -1 and n.label.startswith("Part ") for n in dividers), regulation


def test_corpus_a_missing_space_after_the_dot_does_not_hide_the_paragraph():
    assert _find(_parse("UN R162", grids=False), "5.1.2").body.startswith("5.1.2.An immobilizer")
    assert _find(_parse("UN R48", grids=False), "6.3.6.1.2.2").body.startswith("6.3.6.1.2.2.The")


def test_corpus_the_tree_is_complete_and_the_table_hangs_under_its_paragraph():
    doc = _parse("UN R150", grids=False)
    table, nodes = _find(doc, "5.1.4.4.1. Table 3"), doc.nodes
    assert nodes[table.parent].label == "5.1.4.4.1" and nodes[table.parent].kind == "para"
    assert table.path.endswith("› Table 3") and " › 5.1.4.4.1 " in table.path  # the owner's number and title, then the table
    assert all(n.parent < i for i, n in enumerate(nodes))  # a parent comes first
    assert all(i in nodes[n.parent].children for i, n in enumerate(nodes) if n.parent >= 0)
    assert all(nodes[c].parent == i for i, n in enumerate(nodes) for c in n.children)
    scoped = next(n for n in nodes if n.scope.startswith("Annex") and n.kind == "para" and len(n.num) > 1)
    assert nodes[scoped.parent].scope == scoped.scope and scoped.path.startswith("Annex")  # an annex's paragraphs hang in its scope


def test_corpus_footnotes_are_flagged_where_they_sit():
    n = _find(_parse("UN R13H", grids=False), "Annex 6 4.4")  # "... the control mode⁴ of the anti-lock system." then footnote 4 on two lines
    assert n.note == [0, 1, 2] and n.text[1].startswith("4It is understood")
    assert n.structured.count("\n") == 1 and n.structured.split("\n")[1].startswith("4It is understood")


def test_corpus_a_restart_under_a_heading_the_parser_does_not_know_is_counted():
    doc = _parse("UN R13H", grids=False)  # Annex 4: plain "A." and "B." headings over paragraphs 1, 2, 3 (not a scope the gold names)
    assert any(scope == "Annex 4" for _, _, scope in doc.restarts)


def test_corpus_model_text_has_the_r10_pulses_once():
    n = _find(_parse("UN R10"), "6.9.1")
    assert n.grid and n.table_lines and n.body.count("500 pulses") >= 1
    assert n.model_text.count("500 pulses") == n.grid.count("500 pulses")


# --------------------------------------------------------------------------------------------------------- runner
def run_tests(namespace: dict, argv: list[str]) -> int:
    """Run the test_* functions of a module's namespace in file order; `--unit` leaves out test_corpus_*, which need the PDFs."""
    only_unit = "--unit" in argv
    tests = [(name, fn) for name, fn in sorted(namespace.items(), key=lambda kv: getattr(kv[1], "__code__", None) and kv[1].__code__.co_firstlineno or 0)
             if name.startswith("test_") and callable(fn)]
    failed = skipped = ran = 0
    for name, fn in tests:
        if only_unit and name.startswith("test_corpus_"):
            continue
        try:
            fn()
        except Skip as why:
            skipped += 1
            print(f"skip  {name}: {why}")
        except Exception:  # AssertionError, or a bug in the parser
            failed += 1
            print(f"FAIL  {name}")
            print("      " + traceback.format_exc().strip().replace("\n", "\n      "))
        else:
            ran += 1
    print(f"{ran} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    return run_tests(globals(), sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
