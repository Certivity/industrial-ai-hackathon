"""Parse a Certivity-rendered UN Regulation PDF into scoped paragraph and table nodes.

    from regcomp.parse import parse_pdf
    doc = parse_pdf("regulations/data/UN_R150/base/UN_R150_base.pdf")
    node = next(n for n in doc.nodes if n.label == "3.3.1.1")       # node.page_start, node.page_end, node.body

Deterministic, no model calls. Needs PyMuPDF (pip install pymupdf). The rules come from the data exploration in
spec/finding/finding.md, and eval/anchors.py has to stay at 100% after any change here.

What it relies on, all seen in the fetched PDFs:
  * a footer "UN R150, version 1.2.1 | page 7 of 54" on every page: dropped, and N is the physical page the gold cites
  * exponents and footnote marks as superscript spans: written "10²", never fused into "102"
  * scope headings in a heavy font (bold and about 1.24x the body size): "Annex 4", "Annex 2A", "Annex 1a", "ANNEX 1",
    "Annex 4 - Appendix 1", "Appendix 1", and a top-level "Part I - ..." (R163). Inside an annex, "Part 1 - ...",
    "Part A: ...", "Part B. ..." (bold). The paragraph numbering restarts inside every scope
  * numbered paragraphs "3.3.1.1. text", and headings that lost their final dot ("5.7 Title", "1 Scope")
  * footnotes set inline under the paragraph that cites them: a raised mark in the text, and a line that opens with a bare number
    in a smaller font ("15This provision does not apply ..."), which is Node.note_starts and stays out of Node.text_hash's numbers

Paragraph starts are the longest increasing chain of the numbers found in a scope. That keeps the real numbering and drops what
only looks like it (table cells, wrapped lines that begin with a reference, figure legends) without needing the numbers to be
consecutive, which they are not.

A scope heading is told by its style (bold, 1.15x the body size). A bold, short, titled line that matches a scope pattern but fails
the size test (R101 Annex 7 Appendix 3 is bold at body size) opens a scope anyway when the numbering restarts after it or its id
follows the scope it sits in; one that repeats the id of its own scope never does (R49 "Appendix 3 - Item 1"). A top-level
"Part I" whose numbers carry on from the paragraphs before it (R89, R163) is a divider, not a scope: its paragraphs are cited by
their printed number ("21.1.2.1", not "Part III 21.1.2.1").

The tree (parent, children, path) and the hash are filled in by parse_pdf, so that nothing else has to rebuild them.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

FOOTER = re.compile(r"^UN (?:R|GTR )\d+[A-Z]?, version [\d.]+ \| page (\d+) of (\d+)$")
ANNEX_APPENDIX = re.compile(r"^(?i:annex)\s+(\d+[A-Za-z]?)\s*[-–]\s*(?i:appendix)(?:\s+(\d+))?\b")
ANNEX = re.compile(r"^(?i:annex)\s+(\d+[A-Za-z]?)\b")
APPENDIX = re.compile(r"^(?i:appendix)\s+(\d+)\b")
PART = re.compile(r"^(?i:part)\s+([IVX]+|[A-Z]|\d+)\b(?:\s*[-–:.]|\s+(?=[A-Z]))")
TABLE = re.compile(r"^Table\s+([A-Z]?\d+[a-z]?(?:-\d+)?)(?:\s+(?=[A-Z])|\s*$)")
DOTTED = re.compile(r"^(\d+(?:\.\d+)*)\.(?:\s+|$|(?=[A-Z][a-z]))")  # a few sources set no space after the dot ("5.1.2.An immobilizer")
DOTLESS = re.compile(r"^(\d+(?:\.\d+)*)\s+(?=[A-Z])")
FIGURE = re.compile(r"\bFigures?\s+((?:[A-Z]\d+-)?(?:[IVXLC]+|\d+)[a-z]?)\b")
ROMAN_PART = re.compile(r"^([IVX]+)\.\s+(\S.*)$")  # GTR layout: "I. Statement of technical rationale", "II. Text of the Regulation"
NUMBER_PREFIX = re.compile(r"^\d+(?:\.\d+)*\.?\s*")
HYPHEN_WRAP = re.compile(r"\w-$")
LIST_ITEM = re.compile(r"^(?:\((?:[a-z]{1,2}|[ivxlc]{1,5}|\d{1,2})\)|[-–•]\s+\S|[-–•]$)")  # "(a)", "(iii)", "(1)", "- text", a lone "-"
HEADING_RATIO = 1.15  # headings are about 1.24x the body font in every PDF; the renderer scales pages, so compare, never hard-code
RESCUE_RATIO = 0.95  # a bold scope line that fails the size test is still taken for a heading only at body size or above (not a footnote)
RESCUE_LENGTH = 110  # ... and no longer than this
NOTE_LEAD = 0.8  # a footnote opens with its number in a font at most this share of the body size ...
NOTE_BODY = 0.92  # ... and goes on in a font under this share
BIG_JUMP = 3  # a gap in the numbers of a chain larger than this is reported (a paragraph may have been lost)
SUPERSCRIPT = str.maketrans("0123456789+-−", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻")
SUPERSCRIPT_CHARS = set("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
RAISED_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
RAISED_RUN = re.compile(f"(?<![0-9{RAISED_DIGITS}])([{RAISED_DIGITS}]+)")
UNRAISE = str.maketrans(RAISED_DIGITS, "0123456789")


def span_text(span: dict) -> str:
    """A span's text. A superscript (an exponent, a footnote mark) is written in superscript characters, as the gold writes
    "3.00∙10²"; joined as it is, it would fuse into its base ("3.00∙102"). Superscript letters (ordinals) stay as they are."""
    text = span["text"]
    core = text.strip()
    if not span["flags"] & 1 or not core:
        return text
    raised = core.translate(SUPERSCRIPT)
    return text.replace(core, raised, 1) if set(raised) <= SUPERSCRIPT_CHARS else text  # spaces around the mark are kept


def wrapped_at_hyphen(text: str) -> bool:
    """Whether a line ends in a hyphen inside a word ('Table A6-'), where Chrome wrapped it. A dash that stands alone or follows a
    space is a list bullet or punctuation ('-' then 'Heat: 48 h'): the next line is a new word. That is 1,461 of the 2,235
    line-end hyphens of the base regulations."""
    return HYPHEN_WRAP.search(text) is not None


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines. A line wrapped at a hyphen ('Table A6-' / '1:') joins with no space, any other with one."""
    out = ""
    for line in lines:
        out = line if not out else (out + line if wrapped_at_hyphen(out) else out + " " + line)
    return out


def scope_label(annex: str | None, appendix: str | None, part: str | None) -> str:
    """'Annex 4 Appendix 1 Part 2' for the pieces that are set; '' for the body of the regulation."""
    pieces = (f"Annex {annex}" if annex else "", f"Appendix {appendix}" if appendix else "", f"Part {part}" if part else "")
    return " ".join(p for p in pieces if p)


def make_label(scope: str, num: tuple[int, ...]) -> str:
    """The gold's paragraph label: '3.3.1.1' in the body, 'Annex 4 Part 1 1.2' inside a scope."""
    return (scope + " " if scope else "") + ".".join(map(str, num))


def structured_lines(lines: list[str], note: list[int] | tuple[int, ...] = ()) -> list[str]:
    """The lines of a node as a reader should see them. The renderer wraps lines at its own width, so a line that goes on is joined to
    the one before; but a list item ("(a)", "(iii)", "- text", a lone "-") and a footnote each start a line of their own, which
    `join_lines` (and so `Node.body`) throws away. `note` is Node.note: 1 opens a footnote, 2 goes on with it."""
    flag = lambda i: note[i] if 0 <= i < len(note) else 0  # noqa: E731
    out: list[str] = []
    for i, line in enumerate(lines):
        if not out or LIST_ITEM.match(line) or flag(i) == 1 or (flag(i - 1) and not flag(i)):
            out.append(line)
        else:
            out[-1] = join_lines([out[-1], line])
    return out


@dataclass
class Node:
    kind: str  # "para" or "table", or the kind of heading: "annex", "annex-appendix", "appendix", "part"
    label: str  # the gold's format: "3.3.1.1", "Annex 4 Part 1 1.2", "5.1.4.4.1. Table 3"
    scope: str  # "" in the body, else "Annex 4 Part 1"
    num: tuple[int, ...]  # numbering inside the scope; () for headings
    page_start: int
    page_end: int
    text: list[str] = field(default_factory=list)  # the node's own lines; sub-paragraphs are separate nodes
    pages: list[int] = field(default_factory=list)  # page of each line in `text`
    grid: str | None = None  # the ruled tables inside this node as markdown grids (blank line between tables), else None
    note: list[int] = field(default_factory=list)  # per line of `text`: 0 text, 1 opens a footnote ("15This provision ..."), 2 goes on with one
    table_lines: list[int] = field(default_factory=list)  # indexes in `text` of the lines that lie inside a gridded table
    parent: int = -1  # index in ParsedDocument.nodes of the enclosing node (a paragraph's parent paragraph, else its scope's heading); -1: none
    children: list[int] = field(default_factory=list)  # indexes of the nodes whose parent this is, in document order
    path: str = ""  # breadcrumb: "6 Specifications › 6.10 Rear position lamps › 6.10.4.2"; the scope's heading comes first in an annex

    @property
    def body(self) -> str:
        return join_lines(self.text)

    def title(self, width: int = 80) -> str:
        """The first words of the node without its number: a section's heading, or the start of a paragraph. Only the lines that can
        reach `width` are joined: an annex heading holds pages of text, and every node under it asks for its title."""
        head, size = [], 0
        for line in self.text:
            head.append(line)
            size += len(line) + 1
            if size > width + 40:  # the number prefix is 16 characters at most in practice
                break
        return NUMBER_PREFIX.sub("", join_lines(head))[:width]

    @property
    def heading(self) -> str:
        return self.title(90)

    @property
    def structured(self) -> str:
        """`body` with a line break before every list item and footnote: what an extractor should read."""
        return "\n".join(structured_lines(self.text, self.note))

    @property
    def model_text(self) -> str:
        """`structured` without the lines of the ruled tables, then the tables once, as the markdown grid. `body` has the table
        flattened in reading order and `grid` has it again; a reader given both sees every value twice."""
        skip = set(self.table_lines)
        keep = [i for i in range(len(self.text)) if i not in skip]
        text = "\n".join(structured_lines([self.text[i] for i in keep], [self.note[i] if i < len(self.note) else 0 for i in keep]))
        return text + ("\n\n" + self.grid if self.grid else "")

    @property
    def text_hash(self) -> str:
        """A hash of what the node says, for telling a changed paragraph from a renumbered or re-flowed one (spec/proposal.md B1). It
        covers the words of the node without its own number, footnote text included (it is binding), and ignores what a new version
        renumbers or re-sets: the number of a footnote and the raised mark that cites it in the node, line breaks, and whether a list
        is set inline or one item to a line (a layout change is not a changed paragraph, and a false "modified" is the costly error).
        An exponent is kept: "10²" has its base before it and stays; a footnote mark whose number matches a footnote of this node goes."""
        lines = list(self.text)
        flag = lambda i: self.note[i] if i < len(self.note) else 0  # noqa: E731
        numbers = {m.group(0) for i, line in enumerate(lines) if flag(i) == 1 and (m := re.match(r"\d+", line))}
        for i, line in enumerate(lines):
            if flag(i) == 1:
                lines[i] = re.sub(r"^\d+\s*", "", line)
            elif numbers:
                lines[i] = RAISED_RUN.sub(lambda m: "" if m.group(1).translate(UNRAISE) in numbers else m.group(0), line)
        if lines:
            lines[0] = NUMBER_PREFIX.sub("", lines[0])
        return hashlib.sha1(" ".join(join_lines(lines).split()).encode("utf-8")).hexdigest()[:16]

    @property
    def figure_refs(self) -> list[str]:
        return sorted(set(FIGURE.findall(self.body)))

    def page_of(self, quote: str) -> int | None:
        """Page of the line where `quote` starts (copy it from `body`), or None if it is not in this node."""
        joined, starts = "", []
        for line in self.text:
            if joined and not wrapped_at_hyphen(joined):
                joined += " "
            starts.append(len(joined))
            joined += line
        at = joined.find(quote)
        if at < 0:
            return None
        return self.pages[max(i for i, start in enumerate(starts) if start <= at)]


@dataclass
class ParsedDocument:
    path: Path
    pages: int
    nodes: list[Node] = field(default_factory=list)
    candidates: int = 0  # numbered lines that might start a paragraph
    left_out: list[tuple[int, str, str]] = field(default_factory=list)  # (page, line, scope): candidates not in the chain
    wrapped: list[tuple[int, str, str]] = field(default_factory=list)  # (page, line, scope): numbered lines that end a reference
    jumps: list[tuple[str, str, str, int]] = field(default_factory=list)  # (scope, before, after, size): gaps inside a chain
    footers: int = 0  # footer lines found
    footer_mismatches: list[tuple[int, str]] = field(default_factory=list)  # footer whose page number is not the physical page
    image_pages: list[int] = field(default_factory=list)  # pages that carry a raster image (figures, formulas)
    front_chars: int = 0  # text before the first heading or paragraph (title block, introduction)
    body_size: float = 0.0  # the dominant font size (by characters); headings are told from body text by comparing with it
    grids_built: bool = False  # whether Node.grid was looked for: a None grid then means "no ruled table", not "not tried"
    grids: int = 0  # nodes that got a grid
    loose_grids: int = 0  # ruled tables that sit on no node's text (a table on a page of figures)
    grid_errors: list[tuple[int, str]] = field(default_factory=list)  # (page, error) where find_tables() failed
    scope_rejects: list[tuple[int, str, str, str]] = field(default_factory=list)  # (page, line, scope, why): bold lines that read as a scope heading and were not taken for one
    restarts: list[tuple[int, str, str]] = field(default_factory=list)  # (page, line, scope): a left-out "1." after the chain had passed 1; the numbering restarted
    fallback_grids: int = 0  # captioned tables that got their grid from the text-position fallback, not from ruling lines

    @property
    def unexplained_rejects(self) -> list[tuple[int, str, str, str]]:
        """Scope-like bold lines nobody can explain: not a repeat of the id of the scope they sit in, not too long or a sentence,
        not set below body size. R101's missing Appendix 3 was one of these before the restart rule took it in."""
        return [item for item in self.scope_rejects if item[3] == "no evidence"]

    @property
    def lost_starts(self) -> list[tuple[int, str, str]]:
        """Left-out lines with sentence text after the number: probable real paragraphs, unlike table cells and legends."""
        return [item for item in self.left_out if len(NUMBER_PREFIX.sub("", item[1])) >= 25]

    @property
    def orphans(self) -> list[Node]:
        """Paragraphs whose parent number has no node in their scope: a heading was lost (R40's "1 2. DEFINITIONS")."""
        have = {(n.scope, n.num) for n in self.nodes if n.kind == "para"}
        return [n for n in self.nodes if n.kind == "para" and len(n.num) > 1 and (n.scope, n.num[:-1]) not in have]


Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points, origin top left


@dataclass
class _Raw:
    page: int
    text: str
    bold: bool
    size: float
    bbox: Box
    lead_digit: bool = False  # the first span is a bare number and more text follows in another span: where a footnote starts


@dataclass
class _Line:
    idx: int
    page: int
    text: str
    bold: bool
    size: float
    scope: int  # index into the list of scope labels
    heading: str | None  # the kind of scope heading this line is, if it is one
    bbox: Box
    note: int = 0  # 0 text, 1 opens a footnote, 2 goes on with one
    label: str = ""  # of a heading: the label of its node ("Part I" for a divider, whose scope is the one it sits in)


def _raw_lines(pdf: pymupdf.Document, doc: ParsedDocument) -> list[_Raw]:
    """The text lines of every page in reading order, without the footers (which are counted and checked on the way)."""
    raws: list[_Raw] = []
    for number, page in enumerate(pdf, start=1):
        if page.get_images():
            doc.image_pages.append(number)
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                text = "".join(span_text(s) for s in spans).strip()
                if not text:
                    continue
                if (m := FOOTER.match(text)):
                    doc.footers += 1
                    if int(m.group(1)) != number or int(m.group(2)) != pdf.page_count:
                        doc.footer_mismatches.append((number, text))
                    continue
                lead = len(spans) > 1 and spans[0]["text"].strip().isdigit() and len(spans[0]["text"].strip()) <= 2
                raws.append(_Raw(number, text, bool(spans[0]["flags"] & 16), spans[0]["size"], tuple(line["bbox"]), lead))
    return raws


def _body_size(raws: list[_Raw]) -> float:
    weight: dict[float, int] = defaultdict(int)
    for raw in raws:
        weight[round(raw.size, 1)] += len(raw.text)
    return max(weight, key=weight.__getitem__) if weight else 10.5


def _number(match: re.Match) -> tuple[int, ...]:
    return tuple(int(x) for x in match.group(1).split("."))


def _numbered(text: str) -> tuple[int, ...] | None:
    """The number a line starts with, if it could start a paragraph (the test of _paragraph_starts, before its filters)."""
    m = DOTTED.match(text)
    if m is None and len(text) <= 120:
        m = DOTLESS.match(text)
    return _number(m) if m else None


def _next_ids(identifier: str | None) -> set[str]:
    """The ids an annex or appendix may carry right after `identifier`: 7 -> 8 (or 8A), 2A -> 2B; nothing yet -> 1."""
    if identifier is None:
        return {"1"}
    m = re.fullmatch(r"(\d+)([A-Za-z]?)", identifier)
    if m is None:
        return set()
    number, letter = int(m.group(1)), m.group(2)
    out = {str(number + 1), f"{number + 1}A", f"{number + 1}a"}
    if letter:
        out.add(f"{number}{chr(ord(letter) + 1)}")
    return out


def _scope_match(text: str) -> tuple[str, str | None, str | None, re.Match] | None:
    """(kind, annex, appendix, match) of a line that starts like an annex, annex-appendix or bare appendix heading."""
    if (m := ANNEX_APPENDIX.match(text)):
        return "annex-appendix", m.group(1), m.group(2) or "1", m
    if (m := ANNEX.match(text)):
        return "annex", m.group(1), None, m
    if (m := APPENDIX.match(text)):
        return "appendix", None, m.group(1), m
    return None


def _repeats(kind: str, annex: str | None, appendix: str | None, current: tuple[str | None, str | None]) -> bool:
    """Whether a heading carries the id of the scope it would sit in (R49's "Appendix 3 - Item 1" inside Annex 9B Appendix 3)."""
    here_annex, here_appendix = current
    return {"annex": annex == here_annex, "annex-appendix": (annex, appendix) == (here_annex, here_appendix),
            "appendix": appendix == here_appendix}[kind]


def _follows(kind: str, annex: str | None, appendix: str | None, current: tuple[str | None, str | None]) -> bool:
    """Whether a heading's id is the next one after the scope it would sit in (Appendix 3 after Appendix 2 of the same annex)."""
    here_annex, here_appendix = current
    if kind == "annex":
        return annex in _next_ids(here_annex)
    if kind == "appendix":
        return appendix in _next_ids(here_appendix)
    return (annex == here_annex and appendix in _next_ids(here_appendix)) or (annex in _next_ids(here_annex) and appendix == "1")


def _rescued(raw: _Raw, scope_kind: tuple, body_size: float, current: tuple[str | None, str | None], restart: bool) -> tuple[bool, str]:
    """Whether a bold scope-like line that failed the size test is a scope heading after all, and if not, why. It has to look like a
    heading (short, no sentence mark at its end, not set below body size, a title that does not start in lower case) and show it opens
    a scope: the numbering restarts after it, or its id follows the one it sits in. A repeat of its own scope's id never does."""
    kind, annex, appendix, m = scope_kind
    text = raw.text
    title = text[m.end():].lstrip(" -–:.")
    if len(text) > RESCUE_LENGTH:
        return False, "long"
    if text.rstrip().endswith((".", ",", ";")):
        return False, "sentence"
    if raw.size < RESCUE_RATIO * body_size:
        return False, "small"
    if title[:1].islower():
        return False, "lowercase"
    if _repeats(kind, annex, appendix, current):
        return False, "same id"
    if restart or _follows(kind, annex, appendix, current):
        return True, ""
    return False, "no evidence"


def _scope_lines(raws: list[_Raw], body_size: float, doc: ParsedDocument | None = None) -> tuple[list[_Line], list[str]]:
    """Tag every line with the scope (annex, appendix, part) it sits in, and mark the scope headings. The style test (bold and heavy)
    finds the headings; the restart rule takes in a bold one that is only at body size; a top-level Part that carries on the numbering
    is a divider and opens no scope."""
    lines: list[_Line] = []
    scopes = [""]
    annex = appendix = part = None
    heavy = HEADING_RATIO * body_size
    following: list[tuple[int, ...] | None] = [None] * len(raws)  # the number of the next numbered line, for each line
    ahead = None
    for i in range(len(raws) - 1, -1, -1):
        following[i] = ahead
        ahead = _numbered(raws[i].text) or ahead
    last = None  # the number of the latest dotted numbered line
    passed_one = False  # the scope in force has had a number above 1
    note = 0
    for i, raw in enumerate(raws):
        text, heading, label, divider = raw.text, None, "", False
        if raw.bold and raw.size >= heavy:
            if (found := _scope_match(text)):
                heading, annex, appendix, part = found[0], found[1], found[2], None
            elif not (annex or appendix) and (m := PART.match(text)):
                heading, label = "part", f"Part {m.group(1)}"
                # numbering that goes on from the paragraphs before it makes the Part a divider (R89, R163); one that goes back
                # (to 1, usually) a scope of its own
                divider = following[i] is None or last is None or following[i] > last
                if not divider:
                    part = m.group(1)
            elif not (annex or appendix) and (m := ROMAN_PART.match(text)):
                # a GTR is "I. rationale" then "II. Text of the Regulation", which cites like the body of any regulation
                part, heading = (None if m.group(2).lower().startswith("text of the regulation") else m.group(1)), "part"
        elif raw.bold and (found := _scope_match(text)):
            taken, why = _rescued(raw, found, body_size, (annex, appendix), following[i] == (1,) and passed_one)
            if taken:
                heading, annex, appendix, part = found[0], found[1], found[2], None
            elif doc is not None:
                doc.scope_rejects.append((raw.page, text[:60], scopes[-1], why))
        if heading is None and raw.bold and (annex or appendix) and (m := PART.match(text)):
            part, heading = m.group(1), "part"
        if heading and not divider:
            scopes.append(scope_label(annex, appendix, part))
            last, passed_one = None, False
        elif (m := DOTTED.match(text)) and heading is None:
            last = _number(m)
            passed_one = passed_one or last > (1,)
        if raw.lead_digit and raw.size < NOTE_LEAD * body_size:
            note = 1
        elif note and raw.size < NOTE_BODY * body_size and not raw.bold:
            note = 2
        else:
            note = 0
        lines.append(_Line(len(lines), raw.page, text, raw.bold, raw.size, len(scopes) - 1, heading, raw.bbox, note,
                           label or (scopes[-1] if heading else "")))
    return lines, scopes


def _longest_chain(items: list[tuple[int, tuple[int, ...], bool]]) -> list[tuple[int, tuple[int, ...], bool]]:
    """Longest strictly increasing run (tuple order) of (line, number, dotted); ties prefer dotted numbers and earlier lines."""
    if not items:
        return []
    best, back = [0.0] * len(items), [-1] * len(items)
    for i, (_, num, dotted) in enumerate(items):
        gain = 1.0 + (0.001 if dotted else 0.0)
        best[i] = gain
        for j in range(i):
            if items[j][1] < num and best[j] + gain > best[i]:
                best[i], back[i] = best[j] + gain, j
    k = max(range(len(items)), key=best.__getitem__)
    chain = []
    while k != -1:
        chain.append(items[k])
        k = back[k]
    return chain[::-1]


def _jump(before: tuple[int, ...], after: tuple[int, ...]) -> int:
    """How far the number moved at the first place where the two differ (a first child reports its own number)."""
    for a, b in zip(before, after):
        if a != b:
            return b - a
    return after[len(before)] if len(after) > len(before) else 0


def wraps_reference(previous: str) -> bool:
    """A numbered line right after "... specified in paragraph" continues the reference ("6.4. of this Regulation, ...")."""
    words = previous.split()
    return bool(words) and words[-1].lower() in ("paragraph", "paragraphs")


def opens_section(num: tuple[int, ...], following: tuple[int, ...] | None) -> bool:
    """Whether the next numbered line of the scope is a sub-paragraph of `num` ("4 Test requirements" then "4.1.")."""
    return following is not None and len(following) > len(num) and following[: len(num)] == num


def _paragraph_starts(lines: list[_Line], scopes: list[str], doc: ParsedDocument) -> dict[int, tuple[int, ...]]:
    """Line index -> number, for the lines that start a paragraph."""
    candidates: dict[int, list[tuple[int, tuple[int, ...], bool]]] = defaultdict(list)
    weak: set[int] = set()  # unstyled "4 Test requirements": kept only if its first sub-paragraph follows
    for line in lines:
        if line.heading:
            continue
        m = DOTTED.match(line.text)
        dotted = m is not None
        if m is None and len(line.text) <= 120:
            m = DOTLESS.match(line.text)
        if m is None:
            continue
        if line.idx and wraps_reference(lines[line.idx - 1].text):
            doc.wrapped.append((line.page, line.text[:60], scopes[line.scope]))
            continue
        num = _number(m)
        # without its final dot a number is a heading if nested or styled; a bare "12 RF absorber" is a figure legend, unless
        # a "12.1" follows it
        if not dotted and len(num) < 2 and not line.bold and line.size < HEADING_RATIO * doc.body_size:
            weak.add(line.idx)
        candidates[line.scope].append((line.idx, num, dotted))
    starts: dict[int, tuple[int, ...]] = {}
    for scope_id, items in candidates.items():
        items[:] = [item for k, item in enumerate(items)
                    if item[0] not in weak or opens_section(item[1], items[k + 1][1] if k + 1 < len(items) else None)]
        chain = _longest_chain(items)
        kept = {idx for idx, _, _ in chain}
        starts.update({idx: num for idx, num, _ in chain})
        doc.candidates += len(items)
        doc.left_out += [(lines[idx].page, lines[idx].text[:60], scopes[scope_id]) for idx, _, _ in items if idx not in kept]
        # a "1." left out after the chain went past 1 is a restart, when a sentence follows the number and the next left-out line goes
        # on with the new run ("2." or "1.1."): a bare "1." is a table cell, "1. Additional information:......" a form field, and a
        # lone "1. ... see addendum" in a communication form has nothing behind it; none of them starts a paragraph
        passed = next((idx for idx, num, _ in chain if num > (1,)), None)
        out = [(idx, num, dotted) for idx, num, dotted in items if idx not in kept]
        doc.restarts += [(lines[idx].page, lines[idx].text[:60], scopes[scope_id]) for k, (idx, num, dotted) in enumerate(out)
                         if num == (1,) and dotted and passed is not None and idx > passed
                         and len(NUMBER_PREFIX.sub("", lines[idx].text)) >= 25 and "...." not in lines[idx].text
                         and k + 1 < len(out) and out[k + 1][1] in ((2,), (1, 1))]
        for (_, before, _), (_, after, _) in zip(chain, chain[1:]):
            size = _jump(before, after)
            if size > BIG_JUMP:
                doc.jumps.append((scopes[scope_id], ".".join(map(str, before)), ".".join(map(str, after)), size))
    return starts


def _build_nodes(lines: list[_Line], scopes: list[str], starts: dict[int, tuple[int, ...]],
                 doc: ParsedDocument) -> tuple[list[int], list[int]]:
    """Cut the lines into nodes. A table belongs to the nearest open paragraph whose own text names it, else to the latest one.
    Returns, for every line, the index in doc.nodes of the node that holds it (-1 for the front matter) and its position in that
    node's text. Nodes get their tree fields from _link_tree afterwards."""
    current: Node | None = None
    last_para: Node | None = None
    open_paras: list[Node] = []  # the latest paragraph and its ancestors
    scope_id = 0
    owners = [-1] * len(lines)
    slots = [-1] * len(lines)
    holder = -1
    for line in lines:
        if line.scope != scope_id:
            scope_id, open_paras, last_para = line.scope, [], None
        scope, page = scopes[scope_id], line.page
        if line.heading:
            current = Node(line.heading, line.label or scope, scope, (), page, page, [line.text], [page], note=[line.note])
            doc.nodes.append(current)
            holder = len(doc.nodes) - 1
        elif line.idx in starts:
            num = starts[line.idx]
            current = last_para = Node("para", make_label(scope, num), scope, num, page, page, [line.text], [page], note=[line.note])
            doc.nodes.append(current)
            holder = len(doc.nodes) - 1
            while open_paras and open_paras[-1].num != num[: len(open_paras[-1].num)]:
                open_paras.pop()
            open_paras.append(current)
        elif (m := TABLE.match(line.text)) and (line.bold or m.end() < len(line.text)):
            mention = re.compile(rf"\bTable {re.escape(m.group(1))}\b")
            owner = next((n for n in reversed(open_paras) if mention.search(n.body)), last_para)
            base = owner.label if owner else scope
            label = (base + ". " if base else "") + f"Table {m.group(1)}"
            current = Node("table", label, scope, owner.num if owner else (), page, page, [line.text], [page], note=[line.note])
            doc.nodes.append(current)
            holder = len(doc.nodes) - 1
        elif current is None:
            doc.front_chars += len(line.text)
        else:
            current.text.append(line.text)
            current.pages.append(page)
            current.note.append(line.note)
            current.page_end = page
        owners[line.idx] = holder
        slots[line.idx] = len(doc.nodes[holder].text) - 1 if holder >= 0 else -1
    return owners, slots


def _scope_parent(scope: str) -> str:
    """'Annex 4 Appendix 1 Part 2' -> 'Annex 4 Appendix 1': the scope an inner scope sits in."""
    return " ".join(re.findall(r"(?:Annex|Appendix|Part) \S+", scope)[:-1])


def _link_tree(doc: ParsedDocument) -> None:
    """Fill in parent, children and path of every node. A paragraph hangs under the nearest earlier paragraph of its scope whose
    number is a prefix of its own (5.1.4.2 under 5.1.4, or under 5.1 when the source has no 5.1.4), else under its scope's heading;
    a table under the paragraph that names it, else under its scope's heading; an inner scope under the scope around it."""
    nodes = doc.nodes
    heads: dict[str, int] = {}
    by_key: dict[tuple[str, tuple[int, ...]], int] = {}
    for i, n in enumerate(nodes):
        if n.kind not in ("para", "table"):
            if n.scope:  # a divider ("Part I" of R89) has no scope and is not an anchor for anything
                heads.setdefault(n.scope, i)
        elif n.kind == "para":
            by_key.setdefault((n.scope, n.num), i)
    for i, n in enumerate(nodes):
        if n.kind not in ("para", "table"):
            n.parent = heads.get(_scope_parent(n.scope), -1) if n.scope else -1
        elif n.kind == "para":
            up = next((by_key[(n.scope, n.num[:k])] for k in range(len(n.num) - 1, 0, -1) if by_key.get((n.scope, n.num[:k]), i) < i), -1)
            n.parent = up if up != -1 else heads.get(n.scope, -1)
        else:  # a table hangs under the paragraph that names it
            owner = by_key.get((n.scope, n.num)) if n.num else None
            n.parent = owner if owner is not None and owner < i else heads.get(n.scope, -1)
        n.children = []
    for i, n in enumerate(nodes):
        if n.parent >= 0:
            nodes[n.parent].children.append(i)
    piece: dict[int, str] = {}  # what an ancestor shows in a breadcrumb, made once
    for n in nodes:
        pieces, up = [], n.parent
        while up >= 0:
            ancestor = nodes[up]
            if up not in piece:
                piece[up] = (ancestor.title(70) if ancestor.kind not in ("para", "table") else
                             f"{'.'.join(map(str, ancestor.num))} {ancestor.title(60)}".strip())
            pieces.append(piece[up])
            up = ancestor.parent
        own = ".".join(map(str, n.num)) if n.kind == "para" else n.label.rsplit(". ", 1)[-1] if n.kind == "table" else n.title(70)
        n.path = " › ".join([*reversed(pieces), own])


# ------------------------------------------------------------------------------------------------------------------ grids
# A table's text comes out of the line pass as one string in reading order ("... 20' 1.20∙10³ 8.00∙10² ... ------1°30' ..."),
# which loses which value sits under which column. The cells are cut out again from the ruling lines and written as a
# markdown grid, so that "IA, IB | Red | 20' | 3.00∙10² | 2.00∙10² | 1.00∙10²" can be read off one row.

GRID_TOL = 1.5  # points: cell edges closer than this are the same edge
CONTINUES_BELOW = 0.6  # a table that goes on over the page break ends below this share of the page height ...
CONTINUES_ABOVE = 0.4  # ... and goes on above this share of the next page


def _finder_options() -> dict:
    """PyMuPDF 2.x gates find_tables() with a neural layout model whenever onnxruntime is importable. That is slow (0.4 s a
    page against 0.1 s), differs between machines, and dropped a real table (R48 p15, the colour boundaries at the top of the
    page). use_layout=False asks for the ruling lines only; older PyMuPDF versions have no such switch and need none."""
    try:  # Page.find_tables is a (self, **kwargs) wrapper; the parameters are those of the function in pymupdf.table
        return {"use_layout": False} if "use_layout" in inspect.signature(pymupdf.table.find_tables).parameters else {}
    except (AttributeError, TypeError, ValueError):
        return {}


def _ruled(page: pymupdf.Page) -> bool:
    """Whether the page draws at least two horizontal and two vertical rulings, which find_tables() needs; a cheap gate that
    keeps it away from the 70% of pages without a table. Checked on the 3,029 pages of the 56 base PDFs: 2,106 are skipped, and
    find_tables() finds no table on any of them."""
    horizontal = vertical = 0
    for drawing in page.get_cdrawings():
        for item in drawing["items"]:
            if item[0] == "l":
                (x0, y0), (x1, y1) = item[1], item[2]
                width, height = abs(x1 - x0), abs(y1 - y0)
                if height < 1 and width > 8:
                    horizontal += 1
                elif width < 1 and height > 8:
                    vertical += 1
            elif item[0] == "re":
                x0, y0, x1, y1 = item[1]
                width, height = abs(x1 - x0), abs(y1 - y0)
                if height < 2 and width > 8:
                    horizontal += 1
                elif width < 2 and height > 8:
                    vertical += 1
                elif width > 8 and height > 8:  # a filled cell is four rulings
                    horizontal, vertical = horizontal + 2, vertical + 2
    return horizontal >= 2 and vertical >= 2


Span = tuple[float, float, tuple[int, int], float, str]  # centre x, centre y, (block, line), left x, text


def _page_spans(page: pymupdf.Page) -> list[Span]:
    spans: list[Span] = []
    for b, block in enumerate(page.get_text("dict")["blocks"]):
        for l, line in enumerate(block.get("lines", [])):
            for span in line["spans"]:
                if span["text"].strip():
                    x0, y0, x1, y1 = span["bbox"]
                    spans.append(((x0 + x1) / 2, (y0 + y1) / 2, (b, l), x0, span_text(span)))
    return spans


def _cell_text(spans: list[Span], box: Box) -> str:
    """The text of the spans whose centre is in the box, lines top to bottom and spans left to right, so a sign printed as its
    own span ("-" before "75 V") and an exponent stay where they were set."""
    x0, y0, x1, y1 = box
    lines: dict[tuple[int, int], list[tuple[float, float, str]]] = defaultdict(list)
    for cx, cy, key, left, text in spans:
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            lines[key].append((left, cy, text))
    ordered = sorted(lines.values(), key=lambda parts: (round(min(p[1] for p in parts)), min(p[0] for p in parts)))
    texts = ["".join(text for _, _, text in sorted(parts, key=lambda p: p[0])) for parts in ordered]
    return re.sub(r"\s+", " ", join_lines([t.strip() for t in texts])).strip()


def _edges(values: list[float]) -> list[float]:
    out: list[float] = []
    for value in sorted(values):
        if not out or value - out[-1] > GRID_TOL:
            out.append(value)
    return out


def _nearest(edges: list[float], value: float) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - value))


def _grid_rows(cells: list[Box], spans: list[Span]) -> list[list[str]]:
    """Rows of cell texts from the cell rectangles of a table. A cell that spans rows is repeated in each of them (a key such as
    "IA, IB | Red" then stands on every row it covers); one that spans columns is written once, at its first column."""
    xs = _edges([c[0] for c in cells] + [c[2] for c in cells])
    ys = _edges([c[1] for c in cells] + [c[3] for c in cells])
    grid: list[list[str]] = [[""] * (len(xs) - 1) for _ in range(len(ys) - 1)]
    for cell in cells:
        c0 = _nearest(xs, cell[0])
        r0, r1 = _nearest(ys, cell[1]), _nearest(ys, cell[3])
        text = _cell_text(spans, cell)
        for r in range(r0, max(r1, r0 + 1)):
            grid[r][c0] = text
    return grid


@dataclass
class _Piece:
    """One ruled table as found on one page."""
    page: int
    page_height: float
    box: Box
    rows: list[list[str]]
    columns: list[float]  # x of the vertical rulings


def _continues(above: _Piece, below: _Piece) -> bool:
    """Whether `below`, at the top of the next page, is the rest of `above`: the vertical rulings in the same places, one table
    near the foot of its page and the other near the head of the next. Two tables that only follow each other (R48 2.11.2.3: the
    colour boundaries, then their intersection points) have as many columns but not the same ones."""
    return (below.page == above.page + 1 and len(below.columns) == len(above.columns)
            and all(abs(a - b) <= 2 * GRID_TOL for a, b in zip(above.columns, below.columns))
            and above.box[3] > CONTINUES_BELOW * above.page_height and below.box[1] < CONTINUES_ABOVE * below.page_height)


def _markdown(rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows]
    lines.insert(1, "|" + " --- |" * len(rows[0]))
    return "\n".join(lines)


def _render(pieces: list[_Piece]) -> str:
    """The tables of one node as markdown. A table cut by a page break is one grid: a header that the next page repeats is
    dropped, one that it does not repeat stays on top of the first page's rows."""
    tables: list[list[list[str]]] = []
    previous: _Piece | None = None
    for piece in pieces:
        if previous is not None and _continues(previous, piece):
            skip = 0
            while skip < min(len(piece.rows), len(tables[-1])) and piece.rows[skip] == tables[-1][skip]:
                skip += 1
            tables[-1] += piece.rows[skip:]
        else:
            tables.append(list(piece.rows))
        previous = piece
    return "\n\n".join(_markdown(rows) for rows in tables)


def _lines_in(box: Box, lines: list[_Line]) -> list[_Line]:
    """The text lines inside the box (a line is inside when its centre is)."""
    x0, y0, x1, y1 = box
    return [line for line in lines if x0 <= (line.bbox[0] + line.bbox[2]) / 2 <= x1 and y0 <= (line.bbox[1] + line.bbox[3]) / 2 <= y1]


def _owner_of(box: Box, lines: list[_Line], owners: list[int]) -> int | None:
    """The node that holds most of the text lines inside the box (a line is inside when its centre is); None if there are none."""
    votes: Counter[int] = Counter(owners[line.idx] for line in _lines_in(box, lines) if owners[line.idx] >= 0)
    return min(votes, key=lambda node: (-votes[node], node)) if votes else None


def _attach_grids(pdf: pymupdf.Document, lines: list[_Line], owners: list[int], slots: list[int], doc: ParsedDocument) -> None:
    """Give every node the ruled tables that lie on its text: its own table, or one that sits inside a paragraph without a
    caption of its own (R10 6.9.1: Tables 3a and 3b hold the seven test pulses)."""
    options = _finder_options()
    by_page: dict[int, list[_Line]] = defaultdict(list)
    for line in lines:
        by_page[line.page].append(line)
    pieces: dict[int, list[_Piece]] = defaultdict(list)
    for number, page in enumerate(pdf, start=1):
        if not _ruled(page):
            continue
        try:
            found = page.find_tables(**options).tables
        except Exception as error:  # one odd page must not cost the parse; eval/health.py reports it
            doc.grid_errors.append((number, repr(error)[:80]))
            continue
        spans: list[Span] | None = None
        for table in found:
            cells = [tuple(cell) for cell in table.cells if cell]
            if len(cells) < 2:  # a ruled box around one paragraph is not a table
                continue
            spans = spans if spans is not None else _page_spans(page)
            rows = _grid_rows(cells, spans)
            if not any(any(row) for row in rows):
                continue
            box = (min(c[0] for c in cells), min(c[1] for c in cells), max(c[2] for c in cells), max(c[3] for c in cells))
            owner = _owner_of(box, by_page[number], owners)
            if owner is None:
                doc.loose_grids += 1
            else:
                columns = _edges([c[0] for c in cells] + [c[2] for c in cells])
                pieces[owner].append(_Piece(number, page.rect.height, box, rows, columns))
                inside = [slots[line.idx] for line in _lines_in(box, by_page[number]) if owners[line.idx] == owner]
                doc.nodes[owner].table_lines += inside
    for owner, found in pieces.items():
        doc.nodes[owner].grid = _render(sorted(found, key=lambda p: (p.page, p.box[1])))
        doc.nodes[owner].table_lines = sorted(set(doc.nodes[owner].table_lines))
    doc.grids = len(pieces)
    doc.grids_built = True


def parse_pdf(path: str | Path, grids: bool = True) -> ParsedDocument:
    """Parse one regulation PDF. `grids=False` skips the table grids (Node.grid stays None), which is the slow part: about
    0.1 s for each page that draws rulings, so a few seconds a regulation. The label and page checks do not need them."""
    pdf = pymupdf.open(path)
    doc = ParsedDocument(path=Path(path), pages=pdf.page_count)
    raws = _raw_lines(pdf, doc)
    doc.body_size = _body_size(raws)
    lines, scopes = _scope_lines(raws, doc.body_size, doc)
    starts = _paragraph_starts(lines, scopes, doc)
    owners, slots = _build_nodes(lines, scopes, starts, doc)
    _link_tree(doc)
    if grids:
        _attach_grids(pdf, lines, owners, slots, doc)
    return doc
