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

Paragraph starts are the longest increasing chain of the numbers found in a scope. That keeps the real numbering and drops what
only looks like it (table cells, wrapped lines that begin with a reference, figure legends) without needing the numbers to be
consecutive, which they are not.
"""

from __future__ import annotations

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
DOTTED = re.compile(r"^(\d+(?:\.\d+)*)\.(?:\s+|$)")
DOTLESS = re.compile(r"^(\d+(?:\.\d+)*)\s+(?=[A-Z])")
FIGURE = re.compile(r"\bFigures?\s+((?:[A-Z]\d+-)?(?:[IVXLC]+|\d+)[a-z]?)\b")
ROMAN_PART = re.compile(r"^([IVX]+)\.\s+(\S.*)$")  # GTR layout: "I. Statement of technical rationale", "II. Text of the Regulation"
NUMBER_PREFIX = re.compile(r"^\d+(?:\.\d+)*\.?\s*")
HYPHEN_WRAP = re.compile(r"\w-$")
HEADING_RATIO = 1.15  # headings are about 1.24x the body font in every PDF; the renderer scales pages, so compare, never hard-code
BIG_JUMP = 3  # a gap in the numbers of a chain larger than this is reported (a paragraph may have been lost)
SUPERSCRIPT = str.maketrans("0123456789+-−", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻")
SUPERSCRIPT_CHARS = set("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


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

    @property
    def body(self) -> str:
        return join_lines(self.text)

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
                raws.append(_Raw(number, text, bool(spans[0]["flags"] & 16), spans[0]["size"], tuple(line["bbox"])))
    return raws


def _body_size(raws: list[_Raw]) -> float:
    weight: dict[float, int] = defaultdict(int)
    for raw in raws:
        weight[round(raw.size, 1)] += len(raw.text)
    return max(weight, key=weight.__getitem__) if weight else 10.5


def _scope_lines(raws: list[_Raw], body_size: float) -> tuple[list[_Line], list[str]]:
    """Tag every line with the scope (annex, appendix, part) it sits in, and mark the scope headings."""
    lines: list[_Line] = []
    scopes = [""]
    annex = appendix = part = None
    heavy = HEADING_RATIO * body_size
    for raw in raws:
        text, heading = raw.text, None
        if raw.bold and raw.size >= heavy:
            if (m := ANNEX_APPENDIX.match(text)):
                annex, appendix, part, heading = m.group(1), m.group(2) or "1", None, "annex-appendix"
            elif (m := ANNEX.match(text)):
                annex, appendix, part, heading = m.group(1), None, None, "annex"
            elif (m := APPENDIX.match(text)):
                annex, appendix, part, heading = None, m.group(1), None, "appendix"
            elif not (annex or appendix) and (m := PART.match(text)):
                part, heading = m.group(1), "part"  # a top-level part of the regulation (R163: Part I, Part II)
            elif not (annex or appendix) and (m := ROMAN_PART.match(text)):
                # a GTR is "I. rationale" then "II. Text of the Regulation", which cites like the body of any regulation
                part, heading = (None if m.group(2).lower().startswith("text of the regulation") else m.group(1)), "part"
        if heading is None and raw.bold and (annex or appendix) and (m := PART.match(text)):
            part, heading = m.group(1), "part"
        if heading:
            scopes.append(scope_label(annex, appendix, part))
        lines.append(_Line(len(lines), raw.page, text, raw.bold, raw.size, len(scopes) - 1, heading, raw.bbox))
    return lines, scopes


def _number(match: re.Match) -> tuple[int, ...]:
    return tuple(int(x) for x in match.group(1).split("."))


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
        for (_, before, _), (_, after, _) in zip(chain, chain[1:]):
            size = _jump(before, after)
            if size > BIG_JUMP:
                doc.jumps.append((scopes[scope_id], ".".join(map(str, before)), ".".join(map(str, after)), size))
    return starts


def _build_nodes(lines: list[_Line], scopes: list[str], starts: dict[int, tuple[int, ...]], doc: ParsedDocument) -> list[int]:
    """Cut the lines into nodes. A table belongs to the nearest open paragraph whose own text names it, else to the latest one.
    Returns, for every line, the index in doc.nodes of the node that holds it (-1 for the front matter)."""
    current: Node | None = None
    last_para: Node | None = None
    open_paras: list[Node] = []  # the latest paragraph and its ancestors
    scope_id = 0
    owners = [-1] * len(lines)
    holder = -1
    for line in lines:
        if line.scope != scope_id:
            scope_id, open_paras, last_para = line.scope, [], None
        scope, page = scopes[scope_id], line.page
        if line.heading:
            current = Node(line.heading, scope, scope, (), page, page, [line.text], [page])
            doc.nodes.append(current)
            holder = len(doc.nodes) - 1
        elif line.idx in starts:
            num = starts[line.idx]
            current = last_para = Node("para", make_label(scope, num), scope, num, page, page, [line.text], [page])
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
            current = Node("table", label, scope, owner.num if owner else (), page, page, [line.text], [page])
            doc.nodes.append(current)
            holder = len(doc.nodes) - 1
        elif current is None:
            doc.front_chars += len(line.text)
        else:
            current.text.append(line.text)
            current.pages.append(page)
            current.page_end = page
        owners[line.idx] = holder
    return owners


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


def _owner_of(box: Box, lines: list[_Line], owners: list[int]) -> int | None:
    """The node that holds most of the text lines inside the box (a line is inside when its centre is); None if there are none."""
    x0, y0, x1, y1 = box
    votes: Counter[int] = Counter()
    for line in lines:
        lx0, ly0, lx1, ly1 = line.bbox
        if x0 <= (lx0 + lx1) / 2 <= x1 and y0 <= (ly0 + ly1) / 2 <= y1 and owners[line.idx] >= 0:
            votes[owners[line.idx]] += 1
    return min(votes, key=lambda node: (-votes[node], node)) if votes else None


def _attach_grids(pdf: pymupdf.Document, lines: list[_Line], owners: list[int], doc: ParsedDocument) -> None:
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
    for owner, found in pieces.items():
        doc.nodes[owner].grid = _render(sorted(found, key=lambda p: (p.page, p.box[1])))
    doc.grids = len(pieces)
    doc.grids_built = True


def parse_pdf(path: str | Path, grids: bool = True) -> ParsedDocument:
    """Parse one regulation PDF. `grids=False` skips the table grids (Node.grid stays None), which is the slow part: about
    0.1 s for each page that draws rulings, so a few seconds a regulation. The label and page checks do not need them."""
    pdf = pymupdf.open(path)
    doc = ParsedDocument(path=Path(path), pages=pdf.page_count)
    raws = _raw_lines(pdf, doc)
    doc.body_size = _body_size(raws)
    lines, scopes = _scope_lines(raws, doc.body_size)
    starts = _paragraph_starts(lines, scopes, doc)
    owners = _build_nodes(lines, scopes, starts, doc)
    if grids:
        _attach_grids(pdf, lines, owners, doc)
    return doc
