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
