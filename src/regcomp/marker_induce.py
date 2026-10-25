"""Per-document induction for the marker parser: what a document's numbering scheme is, learned from that document.

    from regcomp import marker_induce as mi       # used by regcomp.parse_marker (REGCOMP_PARSER=marker, REGCOMP_MARKER_INDUCE=0 switches it off)

parse_marker.py used to carry what someone learned by exploring the UNECE PDFs: the keywords Annex / Appendix / Part, their rank, the
hand-set evidence weights, the reference-word list, the rule that letters and romans are list items. This module replaces each by a
statistic of the document at hand. Built in: arithmetic on ordinals (arabic, letters, roman numerals), the reading order of lines, and the
global hyperparameters below.

  1. SHAPES.  Every line start is reduced to a marker: optional leading word, optional prefix symbol, components of an ordinal class
     (N arabic, a/A letter, r/R roman, N+a with a letter suffix) joined by dots, a decoration ("." ")" "(...)" none). "5.1.4." is N.N.N.,
     "(ii)" is (r), "Article 3" is `article` N, "S5.2" is S N.N, "§ 4" is § N. A lone "i" has a letter and a roman reading.
  2. FAMILIES.  A shape is a marker family when its instances, in this document, form ordinal successor sequences (1,2,3 / a,b,c /
     2,2A,2B,3 / 5.1 then 5.1.1). Dotted numbers of any depth are one family. A leading word that starts such a sequence at least twice,
     in heading-like lines (set apart: bold, bigger, or a short line that does not wrap on), is a keyword; it is a SCOPE keyword when the
     numbering restarts after it and does not resume the numbers before it ("Annex 2" then "1."). A figure caption or a divider that
     leaves the enclosing numbering to resume afterwards is not. The rank between two scope keywords is read from which one restarts the
     other, and from compound headings ("Annex 4 - Appendix 1": the first word contains the second).
  3. TYPOGRAPHY.  Lines are clustered by (bold, size against the body, indent against the margin). With the vertical space above, what the
     previous line ended with, the length of the line and the kind of text after the marker, these are the observed features.
  4. SELF-CALIBRATED EVIDENCE.  A naive-Bayes weight per (family, feature value) is estimated on the document: positives are the readings
     that sit in a successor sequence (in a second round, the readings the first decoding accepted), negatives the others, shrunk toward
     the pooled weights of the same role. Gap and missing-level costs come from this document's own histogram of gaps.
  5. LIST FAMILIES.  A non-dotted family whose values recur again and again (every list has its (a)) is a list-item family and stays in the
     text of its paragraph; any other becomes a citable node. Read off recurrence, not off a letter or roman rule.
  6. CONFIDENCE.  Share of body text inside nodes x share of markers with no break in the sequence x granularity of the nodes.

The decoding (beam over a stack, sibling / child / divider relations) stays in parse_marker.py. The model fallback is marker_outline.py.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pymupdf

from regcomp import parse as base
from regcomp.parse import Node, ParsedDocument, _attach_grids, _body_size, _Line, _Raw, join_lines, span_text

# ------------------------------------------------------------------------------------------------------------------ hyperparameters
BEAM = 12              # states kept per candidate line
MIN_COUNT = 3          # instances a family needs to be a marker family
KEYWORD_MIN = 2        # instances a leading word needs to be a scope keyword ("at least k times")
LINKED_MIN = 0.5       # share of a family's instances that sit in a successor sequence
HEADING_MIN = 0.6      # share of a keyword's instances in heading-like lines
RESTART_MIN = 0.5      # share of a keyword's instances after which the numbering restarts
LINK_WINDOW = 4        # a successor is looked for among this many earlier instances of the family
LINK_GAP = 3           # largest gap (skipped numbers) of a successor link
CONTAIN_MIN = 2        # restarts of one keyword after another needed to say the second sits in the first
LIST_RECURRENCE = 3.0  # a family whose values recur this often and that has no dotted extension is a list-item family
CALIB_W = 0.5          # damping of the naive-Bayes sum (the features are correlated)
LLR_CAP = 2.0
SHRINK = 5.0           # pseudo-instances pulling a family toward its role's pooled weights
CALIB_COST = 0.4       # scale from the log-probability of a gap / missing level to a decoding cost
GAP_CAP = 12
POP_COST = 0.35        # popping open levels to push a first child of a shallower one
CHILD_COST = 0.3
NEST_BONUS = 0.3
RANK_CLASH = 0.6       # a scope keyword under one that is not known to contain it
KEYWORD_POP = 0.25     # a scope keyword that closes an outer scope
FIRST_GAP_COST = 1.0   # a scope keyword that starts above its first value
FIRST_DESC_COST = 0.25
REPEAT_COST = 0.5      # a scope heading that repeats the id of an open scope
RESTART_COST = 1.5     # the dotted class back at 1 with no keyword to explain it
LIST_BASE = 0.6        # a list item is worth less than a paragraph
CONFIDENCE_MIN = 0.55  # under this, the model fallback is used (when a model is configured)
NODE_PAGE_CHARS = 3200 # the text of a page, for the granularity part of the confidence

ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
FIRST = (1, 0)


# ------------------------------------------------------------------------------------------------------------------ ordinals
def roman_value(text: str) -> int | None:
    total, previous = 0, 0
    for ch in reversed(text.lower()):
        v = ROMAN_VALUES.get(ch)
        if v is None:
            return None
        total, previous = (total - v, previous) if v < previous else (total + v, v)
    return total if total and to_roman(total).lower() == text.lower() else None


def to_roman(value: int) -> str:
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                 (5, "V"), (4, "IV"), (1, "I")):
        while value >= v:
            out, value = out + s, value - v
    return out


def gap(prev: tuple, cur: tuple) -> int | None:
    """Numbers skipped going from `prev` to `cur` (same prefix, only the last component differs); None if `cur` is no successor.
    A component with a letter suffix has two successors: 2 -> 2A and 2 -> 3."""
    if len(prev) != len(cur) or prev[:-1] != cur[:-1]:
        return None
    (n, s), (m, t) = prev[-1], cur[-1]
    if m == n:
        return t - s - 1 if t > s else None
    if m > n:
        return (m - n - 1) + max(t - 1, 0)
    return None


# ------------------------------------------------------------------------------------------------------------------ the lexer
@dataclass(frozen=True)
class Seg:
    """One marker segment. `word` is the lowercased leading word ("" if none), `cls` the ordinal class of each component."""
    word: str
    pre: str
    cls: tuple
    val: tuple    # ((number, suffix index), ...)
    raw: str      # as printed, without decoration: "5.1.4", "iv", "2A"
    deco: str     # ".", ")", "()" or ""
    shown: str = ""  # the word as printed ("Annex", "ANNEX")

    @property
    def dotted(self) -> bool:
        return not self.word and all(c == "N" for c in self.cls) and self.deco in (".", "")

    @property
    def fam(self) -> str:
        if self.dotted:
            return f"{self.pre}D"
        return f"{self.word}|{self.pre}|{'.'.join(c.split('+')[0] for c in self.cls)}|{self.deco}"

    @property
    def first(self) -> bool:
        return all(v == FIRST for v in self.val)

    @property
    def shape(self) -> str:
        """The shape as a reader would write it: `Article N`, `§ N`, `S N.N`, `N.N.N.`, `(a)`, `r)`."""
        core = ".".join(self.cls)
        core = {"()": f"({core})", ")": f"{core})", ".": f"{core}.", "": core}[self.deco]
        return " ".join(x for x in (self.word.capitalize(), self.pre, core) if x) if self.word or self.pre.startswith("§") else self.pre + core


@dataclass(frozen=True)
class Marker:
    segs: tuple[Seg, ...]
    deco: str
    rest: str


COMP_NUM = r"\d+(?:\.\d+)*"
WORD_LED = re.compile(rf"(?P<w>[^\W\d_]{{2,}})\s+(?P<pre>[§#]\s?)?(?P<tok>{COMP_NUM}[A-Za-z]?|[A-Z]|[IVXLCDM]{{2,}})(?![^\W_])", re.U)
JOIN = re.compile(r"\s*[-–‑—,:]?\s*")
PAREN = re.compile(r"\(([A-Za-z]{1,5}|\d{1,3})\)(?=\s|$)")
CLOSE = re.compile(r"([A-Za-z]{1,5}|\d{1,3})\)(?=\s|$)")
DOTTED = re.compile(rf"(?P<pre>[§#]\s?|[A-Z](?=\d))?(?P<num>{COMP_NUM})(?P<dot>\.)?")
LETTER_DOT = re.compile(r"([A-Za-z]{1,5})\.(?=\s)")


def _letter_segs(token: str, deco: str, word: str = "", shown: str = "") -> list[Seg]:
    out: list[Seg] = []
    if len(token) == 1 and token.isalpha():
        out.append(Seg(word, "", ("a" if token.islower() else "A",), ((ord(token.lower()) - 96, 0),), token, deco, shown))
    value = roman_value(token) if token.isalpha() else None
    if value is not None and (token.islower() or token.isupper()):
        out.append(Seg(word, "", ("r" if token.islower() else "R",), ((value, 0),), token, deco, shown))
    return out


def _token_segs(token: str, word: str, shown: str, pre: str = "") -> list[Seg]:
    """The readings of the component group after a leading word: 4, 2A, 4.2, I, A."""
    if (body := re.fullmatch(rf"({COMP_NUM})([A-Za-z]?)", token)):
        comps, suffix = body.group(1).split("."), body.group(2)
        val = [(int(c), 0) for c in comps]
        cls = ["N"] * len(comps)
        if suffix:
            val[-1] = (val[-1][0], ord(suffix.lower()) - 96)
            cls[-1] = "N+a" if suffix.islower() else "N+A"
        return [Seg(word, pre.strip(), tuple(cls), tuple(val), token, "", shown)]
    return _letter_segs(token, "", word, shown)


def _lex_word(text: str, pos: int = 0) -> tuple[list[Seg], int] | None:
    m = WORD_LED.match(text, pos)
    if not m:
        return None
    segs = _token_segs(m.group("tok"), m.group("w").lower(), m.group("w"), m.group("pre") or "")
    return (segs, m.end()) if segs else None


def lex(text: str) -> list[Marker]:
    """Every reading of the marker at the start of a line (none if the line has no marker)."""
    text = text.strip()
    if not text:
        return []
    got = _lex_word(text)
    if got:
        segs, pos = got
        chains: list[list[Seg]] = [[s] for s in segs]
        out = [Marker(tuple(c), "", text[pos:].lstrip(" -–:.")) for c in chains]
        while True:  # "Annex 4 - Appendix 1": every length of the chain is a reading, the decoding keeps the one whose words are keywords
            j = JOIN.match(text, pos)
            nxt = _lex_word(text, j.end()) if j else None
            if not nxt or any(nxt[0][0].word == c.word for ch in chains for c in ch):
                break
            chains = [c + [r] for c in chains for r in nxt[0]]
            pos = nxt[1]
            out += [Marker(tuple(c), "", text[pos:].lstrip(" -–:.")) for c in chains]
        return out
    if text.startswith("("):
        if (m := PAREN.match(text)):
            tok = m.group(1)
            segs = [Seg("", "", ("N",), ((int(tok), 0),), tok, "()")] if tok.isdigit() else _letter_segs(tok, "()")
            return [Marker((s,), "()", text[m.end():].lstrip()) for s in segs]
        return []
    if text[0].isdigit() or (m0 := DOTTED.match(text)) and m0.group("pre"):
        m = DOTTED.match(text)
        if m:
            after = text[m.end():]
            num = m.group("num")
            if m.group("dot"):
                if not (after == "" or after[0].isspace() or re.match(r"[^\W\d_][^\W\d_]", after) and after[0].isupper() and after[1].islower()):
                    return []
                deco = "."
            else:
                deep = num.count(".") >= 2 and re.match(r"\s+[^\W\d_]{2,}", after)
                heading = re.match(r"\s+(?=[^\W\d_])", after) and not after.lstrip()[:1].islower()
                if len(text) > 120 or not (heading or deep):
                    return _close_paren(text) if not m.group("pre") else []
                deco = ""
            comps = num.split(".")
            seg = Seg("", (m.group("pre") or "").strip(), tuple("N" for _ in comps), tuple((int(c), 0) for c in comps), num, deco)
            return [Marker((seg,), deco, after.lstrip())]
        return []
    if text[0].isalpha():
        if (m := LETTER_DOT.match(text)):
            return [Marker((s,), ".", text[m.end():].lstrip()) for s in _letter_segs(m.group(1), ".")]
        return _close_paren(text)
    return []


def _close_paren(text: str) -> list[Marker]:
    if (m := CLOSE.match(text)):
        tok = m.group(1)
        segs = [Seg("", "", ("N",), ((int(tok), 0),), tok, ")")] if tok.isdigit() else _letter_segs(tok, ")")
        return [Marker((s,), ")", text[m.end():].lstrip()) for s in segs]
    return []


# ------------------------------------------------------------------------------------------------------------------ line extraction
def extract(pdf: pymupdf.Document, doc: ParsedDocument) -> list[_Raw]:
    """The text lines in reading order with size, bold, position; the lines that repeat in the page margins (running headers and footers,
    page numbers: the line with its digits blanked, in the top or bottom 12% of at least 40% of the pages) are dropped and counted."""
    raws: list[_Raw] = []
    heights: dict[int, float] = {}
    for number, page in enumerate(pdf, start=1):
        heights[number] = page.rect.height
        if page.get_images():
            doc.image_pages.append(number)
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                text = "".join(span_text(s) for s in spans).strip()
                if not text:
                    continue
                lead = len(spans) > 1 and spans[0]["text"].strip().isdigit() and len(spans[0]["text"].strip()) <= 2
                raws.append(_Raw(number, text, bool(spans[0]["flags"] & 16), spans[0]["size"], tuple(line["bbox"]), lead))
    return drop_margins(raws, heights, doc)


def drop_margins(raws: list[_Raw], heights: dict[int, float], doc: ParsedDocument) -> list[_Raw]:
    pages = max(len(heights), 1)
    seen: dict[str, set[int]] = defaultdict(set)
    zone = lambda r: r.bbox[3] < 0.12 * heights.get(r.page, 1e9) or r.bbox[1] > 0.88 * heights.get(r.page, 0)  # noqa: E731
    key = lambda r: re.sub(r"\d+", "#", " ".join(r.text.split()))  # noqa: E731
    for r in raws:
        if zone(r):
            seen[key(r)].add(r.page)
    need = max(3, math.ceil(0.4 * pages)) if pages >= 4 else pages + 1
    gone = {k for k, v in seen.items() if len(v) >= need}
    kept = [r for r in raws if not (zone(r) and key(r) in gone)]
    doc.footers = len(raws) - len(kept)
    return kept


# ------------------------------------------------------------------------------------------------------------------ induction
def is_dotted(fam: str) -> bool:
    return fam.endswith("D") and "|" not in fam


def word_of(fam: str) -> str:
    return fam.split("|")[0] if "|" in fam else ""


def role_of(fam: str) -> str:
    return "dotted" if is_dotted(fam) else "keyword" if word_of(fam) else "item"


@dataclass
class Cand:
    idx: int                                        # index in the raw lines
    markers: list[Marker]
    feats: list[tuple] = field(default_factory=list)  # per reading: the observed features of the line
    ev: list[float] = field(default_factory=list)     # per reading: evidence (log-odds scale), set by calibrate()


def heading_like(raws: list[_Raw], i: int, body: float) -> bool:
    """A line that is set apart: bold, bigger than the body, or a short line that is not a sentence and does not wrap on from the line
    before it."""
    raw = raws[i]
    if raw.bold or raw.size >= 1.08 * body:
        return True
    prev = raws[i - 1].text.rstrip() if i and raws[i - 1].page == raw.page else ""
    return len(raw.text.split()) <= 8 and not raw.text.rstrip().endswith((".", ":", ";", ",")) and (not prev or prev.endswith((".", ":", ";")))


def margin_of(raws: list[_Raw]) -> float:
    return Counter(round(r.bbox[0]) for r in raws).most_common(1)[0][0] if raws else 0.0


def cluster_of(raw: _Raw, body: float, margin: float) -> str:
    """Typographic cluster: bold, size against the body (0.05 steps), indent against the margin (0.8 body sizes a step)."""
    return f"{'b' if raw.bold else 'r'}{round(raw.size / body / 0.05) * 0.05:.2f}i{round((raw.bbox[0] - margin) / (0.8 * body))}"


def line_features(raws: list[_Raw], i: int, body: float, margin: float) -> tuple:
    raw = raws[i]
    prev = raws[i - 1] if i else None
    if prev is None or prev.page != raw.page:
        above = "top"
    else:
        space = (raw.bbox[1] - prev.bbox[3]) / max(raw.size, 1.0)
        above = "tight" if space < 0.15 else "normal" if space < 0.6 else "open"
    end = "start"
    if prev is not None:
        e = prev.text.rstrip()[-1:]
        end = "stop" if e in ".:;" else "comma" if e == "," else "other"
    words = len(raw.text.split())
    return (cluster_of(raw, body, margin), above, end, "short" if words <= 8 else "mid" if words <= 25 else "long",
            "term" if raw.text.rstrip().endswith((".", ";", ":")) else "open")


def rest_kind(marker: Marker) -> str:
    r = marker.rest
    return "empty" if not r else "lower" if r[:1].islower() else "upper" if r[:1].isupper() else "other"


def related(dotted: bool, a: tuple, b: tuple) -> bool:
    """Whether value b follows value a in one numbering: a sibling with a small gap, a first child (dotted), or an ancestor's successor."""
    if len(a) == len(b):
        g = gap(a, b)
        return g is not None and g <= LINK_GAP
    if dotted and len(b) == len(a) + 1:
        return b[:len(a)] == a and b[-1] == FIRST
    if dotted and len(b) < len(a):
        g = gap(a[:len(b)], b)
        return g is not None and g <= LINK_GAP
    return False


@dataclass
class Induction:
    body: float
    margin: float
    cands: list[Cand]
    stream: dict[str, list[tuple[int, int, int]]]       # family -> [(candidate position, reading, segment)]
    linked: set[tuple[int, int]]
    families: dict[str, dict]
    keywords: dict[str, dict]
    rank: dict[str, int]
    listlike: set[str]
    gap_costs: list[float]
    skip_cost: float
    surface: dict[str, str]
    clusters: Counter
    scope_words: set | None = None


def attach_features(raws: list[_Raw], cands: list[Cand], body: float, margin: float) -> None:
    for c in cands:
        lf = line_features(raws, c.idx, body, margin)
        c.feats = [lf + (rest_kind(m),) for m in c.markers]


def induce(raws: list[_Raw], body: float, cands: list[Cand] | None = None, discover: bool = True) -> Induction:
    """The statistics of one document. With `cands` (readings already lexed, as `view` objects) the keywords are not discovered again."""
    margin = margin_of(raws)
    clusters: Counter = Counter()
    for raw in raws:
        clusters[cluster_of(raw, body, margin)] += len(raw.text)
    if cands is None:
        cands = []
        for i, raw in enumerate(raws):
            markers = lex(raw.text)
            if markers:
                cands.append(Cand(i, markers))
        attach_features(raws, cands, body, margin)
    stream: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for p, c in enumerate(cands):
        titled = heading_like(raws, c.idx, body)
        for r, m in enumerate(c.markers):
            for k, s in enumerate(m.segs):
                if titled or not s.word:  # a leading word in running text ("Annex 6 of this Regulation") is a reference, not a marker
                    stream[s.fam].append((p, r, k))
    val_of = lambda p, r, k: cands[p].markers[r].segs[k].val  # noqa: E731
    linked: set[tuple[int, int]] = set()
    for fam, seq in stream.items():
        window = LINK_WINDOW if is_dotted(fam) else 3
        for n, (p, r, k) in enumerate(seq):
            for q, r2, k2 in seq[max(0, n - window):n]:
                if q != p and related(is_dotted(fam), val_of(q, r2, k2), val_of(p, r, k)):
                    linked.update(((p, r), (q, r2)))
                    break
    families = {}
    for fam, seq in stream.items():
        n = len(seq)
        pos = sum(1 for p, r, _ in seq if (p, r) in linked)
        families[fam] = {"n": n, "linked": pos, "share": pos / n}
    # gaps seen between linked neighbours: the cost of a gap is how rare it is in this document
    gaps: Counter = Counter()
    for fam, seq in stream.items():
        if families[fam]["n"] < MIN_COUNT or families[fam]["share"] < LINKED_MIN:
            continue
        for n, (p, r, k) in enumerate(seq):
            for q, r2, k2 in seq[max(0, n - 3):n][::-1]:
                g = gap(val_of(q, r2, k2), val_of(p, r, k)) if q != p else None
                if g is not None and g <= GAP_CAP:
                    gaps[g] += 1
                    break
    total = sum(gaps.values()) + GAP_CAP + 1
    probs = [(gaps[g] + 1) / total for g in range(GAP_CAP + 1)]
    gap_costs = [max(0.0, min(2.0, CALIB_COST * math.log(probs[0] / probs[g]))) for g in range(GAP_CAP + 1)]
    # how often a deeper number appears with no parent number before it: the cost of a missing level
    seen: set[tuple] = set()
    deep = missing = 0
    for p, r, k in stream.get("D", []):
        v = val_of(p, r, k)
        if len(v) >= 2:
            deep += 1
            missing += 0 if v[:-1] in seen else 1
        seen.add(v)
    m = (missing + 1) / (deep + 2)
    skip_cost = max(0.2, min(1.5, CALIB_COST * math.log((1 - m) / m))) if deep else 0.5
    shown: dict[str, Counter] = defaultdict(Counter)
    for c in cands:
        for s in c.markers[0].segs:
            if s.word:
                shown[s.word][s.shown] += 1
    surface = {w: cnt.most_common(1)[0][0] for w, cnt in shown.items()}
    ind = Induction(body, margin, cands, dict(stream), linked, families, {}, {}, set(), gap_costs, skip_cost, surface, clusters)
    if discover:
        _keywords(ind, raws)
        ind.scope_words = {w for w, k in ind.keywords.items() if k['scope']}
    _list_families(ind)
    return ind


def _restart_after(ind: Induction, upto: dict[int, int]) -> dict[int, bool]:
    """For a candidate position holding a keyword instance: whether the numbering restarts after it and stays restarted. The next dotted
    number is at its first value, and the numbers that follow do not go back to carry on from the number before the keyword (a figure
    caption, a table, a divider is an interlude: the enclosing numbering resumes; a scope is not). `upto[p]` is the position of the next
    instance of any keyword. Only dotted numbers that sit in a successor sequence count (a wrapped reference "6.18. of this" does not). Missing when none follows."""
    cands = ind.cands
    dotted = [(p, c.markers[0].segs[0].val) for p, c in enumerate(cands) if c.markers[0].segs[0].dotted and (p, 0) in ind.linked]
    positions = [p for p, _ in dotted]
    out: dict[int, bool] = {}
    import bisect
    for p in upto:
        k = bisect.bisect_right(positions, p)
        if k >= len(dotted):
            continue
        end = upto[p]
        before = dotted[k - 1][1] if k else None
        window = [(q, v) for q, v in dotted[k:k + 80] if q < end]
        if not window:
            continue
        first = window[0][1]
        if not all(c == FIRST for c in first) or (before is not None and related(True, before, first)):
            out[p] = False
            continue
        run_last, resumed = first, False
        for n, (_, v) in enumerate(window[1:], start=1):
            if related(True, run_last, v):
                run_last = v
            elif before is not None and related(True, before, v) and n + 1 < len(window) and related(True, v, window[n + 1][1]):
                resumed = True  # a number that carries on the one before the keyword, and is itself carried on: not a stray cell
                break
        out[p] = not resumed
    return out


def _keywords(ind: Induction, raws: list[_Raw]) -> None:
    """Scope keywords of this document, and the rank between them."""
    cands = ind.cands
    words = {word_of(f) for f in ind.families if word_of(f)}
    headings = sorted({p for f in ind.families if word_of(f) for p, r, _ in ind.stream[f] if (p, r) in ind.linked})  # a window ends at the next one
    for word in words:
        fams = [f for f in ind.families if word_of(f) == word]
        n = sum(ind.families[f]["n"] for f in fams)
        linked = sum(ind.families[f]["linked"] for f in fams)
        if n < KEYWORD_MIN or linked / n < LINKED_MIN:
            continue
        lines = sorted({p for f in fams for p, r, _ in ind.stream[f] if (p, r) in ind.linked})
        if len(lines) < KEYWORD_MIN:
            continue
        heading = sum(1 for p in lines if heading_like(raws, cands[p].idx, ind.body)) / len(lines)
        after = _restart_after(ind, {p: next((q for q in headings if q > p), len(cands)) for p in lines})
        obs = [after[p] for p in lines if p in after]
        restart = sum(obs) / len(obs) if obs else 1.0  # nothing numbered follows: the words are all there is to scope
        ind.keywords[word] = {"n": len(lines), "heading": round(heading, 2), "restart": round(restart, 2), "observed": len(obs),
                              "scope": heading >= HEADING_MIN and restart >= RESTART_MIN, "lines": lines}
    scopes = [w for w, k in ind.keywords.items() if k["scope"]]
    contains: dict[tuple[str, str], int] = {}
    compound: Counter = Counter()  # "Annex 4 - Appendix 1": the first word contains the second; one line says more than a restart count
    for c in cands:
        for ws in {tuple(s.word for s in m.segs) for m in c.markers if len(m.segs) > 1 and all(s.word in scopes for s in m.segs)}:
            for x in range(len(ws)):
                for y in range(x + 1, len(ws)):
                    compound[(ws[x], ws[y])] += 1
    for a in scopes:
        for b in scopes:
            if a == b:
                continue
            votes = tot = 0
            pa = ind.keywords[a]["lines"]
            for x, start in enumerate(pa):
                end = pa[x + 1] if x + 1 < len(pa) else len(cands)
                inside = [q for q in ind.keywords[b]["lines"] if start < q < end]
                if inside:
                    tot += 1
                    votes += 1 if any(s.word == b and s.first for m in cands[inside[0]].markers for s in m.segs) else 0
            if tot < CONTAIN_MIN and not compound[(a, b)]:  # one restart is no pattern
                continue
            votes, tot = votes + compound[(a, b)], tot + compound[(a, b)]
            if tot and votes >= 0.6 * tot:
                contains[(a, b)] = votes
    for pair in [p for p in contains if (p[1], p[0]) in contains]:  # both ways: the compound headings decide, else neither
        if compound[pair] > compound[(pair[1], pair[0])]:
            contains.pop((pair[1], pair[0]), None)
        elif compound[pair] == compound[(pair[1], pair[0])]:
            contains.pop(pair, None)
    closure = set(contains)
    grew = True
    while grew:
        grew = False
        for (a, b) in list(closure):
            for (c, d) in list(closure):
                if b == c and (a, d) not in closure:
                    closure.add((a, d))
                    grew = True
    ind.rank = {w: sum(1 for (_, b) in closure if b == w) for w in scopes}


def _list_families(ind: Induction) -> None:
    """List-item families: the values of the family recur again and again in the document (every list has its (a)). The dotted class and
    the scope keywords are never list items."""
    for fam, seq in ind.stream.items():
        if is_dotted(fam) or word_of(fam):
            continue
        st = ind.families[fam]
        if st["n"] < MIN_COUNT or st["share"] < LINKED_MIN:
            continue
        values = Counter(ind.cands[p].markers[r].segs[k].val for p, r, k in seq if (p, r) in ind.linked)
        if values and sum(values.values()) / len(values) >= LIST_RECURRENCE:
            ind.listlike.add(fam)


# ------------------------------------------------------------------------------------------------------------------ calibration
def usable(ind: Induction, m: Marker) -> bool:
    """A reading is offered to the decoding when each segment is of a marker family (and, for a leading word, of a scope keyword)."""
    for s in m.segs:
        st = ind.families.get(s.fam)
        if st is None or st["n"] < MIN_COUNT or st["share"] < LINKED_MIN:
            if not (s.word and st is not None and st["n"] >= KEYWORD_MIN and st["share"] >= LINKED_MIN):
                return False
        if s.word and ind.scope_words is not None and s.word not in ind.scope_words:
            return False
    return True


def calibrate(ind: Induction, positive: set[tuple[int, int]]) -> None:
    """Naive-Bayes evidence per (family, feature value) estimated on this document: positives are the readings in `positive`, negatives
    every other reading. Sets Cand.ev: the log-odds of being a marker from the line's own look."""
    nf = len(ind.cands[0].feats[0]) if ind.cands else 0
    fam_pos: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(nf)])
    fam_neg: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(nf)])
    count_pos: Counter = Counter()
    count_neg: Counter = Counter()
    for p, c in enumerate(ind.cands):
        for r, m in enumerate(c.markers):
            fam = m.segs[0].fam
            tab, cnt = (fam_pos, count_pos) if (p, r) in positive else (fam_neg, count_neg)
            cnt[fam] += 1
            for j, v in enumerate(c.feats[r]):
                tab[fam][j][v] += 1
    role_pos: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(nf)])
    role_neg: dict[str, list[Counter]] = defaultdict(lambda: [Counter() for _ in range(nf)])
    role_np: Counter = Counter()
    role_nn: Counter = Counter()
    for fam in set(count_pos) | set(count_neg):
        role = role_of(fam)
        role_np[role] += count_pos[fam]
        role_nn[role] += count_neg[fam]
        for j in range(nf):
            role_pos[role][j].update(fam_pos[fam][j])
            role_neg[role][j].update(fam_neg[fam][j])

    def prob(table: list[Counter], total: int, pooled: list[Counter], pooled_total: int, j: int, v: str) -> float:
        distinct = len(set(pooled[j]) | {v}) + 1
        pool = (pooled[j][v] + 1) / (pooled_total + distinct)
        return (table[j][v] + SHRINK * pool) / (total + SHRINK)

    for c in ind.cands:
        c.ev = []
        for r, m in enumerate(c.markers):
            fam = m.segs[0].fam
            role = role_of(fam)
            prior = math.log((count_pos[fam] + 1) / (count_neg[fam] + 1))
            e = max(-1.5, min(0.5, prior))
            s = 0.0
            for j, v in enumerate(c.feats[r]):
                lp = math.log(prob(fam_pos[fam], count_pos[fam], role_pos[role], role_np[role], j, v))
                ln = math.log(prob(fam_neg[fam], count_neg[fam], role_neg[role], role_nn[role], j, v))
                s += max(-LLR_CAP, min(LLR_CAP, lp - ln))
            c.ev.append(e + CALIB_W * s)




# ------------------------------------------------------------------------------------------------------------------ the scheme
@dataclass
class Scheme:
    """What the marker parser needs to know about a document's numbering. CLASSIC (parse_marker.py) is the one fixed by hand; `discover`
    builds one from the document."""
    induced: bool
    surface: dict[str, str]            # scope keyword (lowercase) -> the way the document prints it
    rank: dict[str, int]               # scope keyword -> how many scope keywords contain it
    gap_costs: list[float] | None = None   # cost of skipping g numbers; None: linear (parse_marker.GAP_COST)
    skip_cost: float | None = None     # cost of a missing level of a dotted number; None: parse_marker.SKIP_COST
    bare: tuple[str, ...] = ()         # keywords that may stand with no number after another one ("Annex 2B - Appendix Containers only")
    bare_resets: bool = False          # a stand-alone "Appendix 1" is cited without its annex (a gold convention, classic only)
    report: dict = field(default_factory=dict)


def discover(raws: list[_Raw], body: float) -> Scheme:
    """Pass 1: the scope keywords, their rank, the cost of gaps and of missing levels, all from the lines of this document."""
    ind = induce(raws, body)
    words = sorted(ind.scope_words or ())
    keywords = {w: {k: v for k, v in info.items() if k != "lines"} | {"rank": ind.rank.get(w)} for w, info in ind.keywords.items()}
    return Scheme(True, {w: ind.surface.get(w, w.capitalize()) for w in words}, {w: ind.rank.get(w, 0) for w in words}, ind.gap_costs, ind.skip_cost,
                  tuple(words), False, {"keywords": keywords, "gap_costs": [round(c, 2) for c in ind.gap_costs[:4]], "skip_cost": round(ind.skip_cost, 2),
                                       "clusters": len(ind.clusters)})


def fam_of(seg, deco: str) -> str:
    """The family of a parse_marker Seg: dotted numbers of any depth are one; a keyword segment is its own."""
    if seg.dotted:
        return "D"
    return f"{seg.kw}||{seg.key}|{'' if seg.kw else deco}"


def view(marker) -> Marker:
    """A parse_marker Marker as this module's Marker, so that the statistics run on the readings the parser decodes."""
    segs = []
    for s in marker.segs:
        cls = tuple(s.key.split(".")) if s.dotted else (s.key,)
        segs.append(Seg(s.kw, "", cls, s.val, s.raw, "" if s.kw else marker.deco, s.key.split(" ")[0] if s.kw else ""))
    return Marker(tuple(segs), marker.deco, marker.rest)


@dataclass
class Evidence:
    """Per candidate and reading: whether the reading is offered, and its evidence; recalibrated from an accepted parse."""
    ind: Induction
    use: list[list[bool]]
    listlike: set[str]

    @property
    def ev(self) -> list[list[float]]:
        return [c.ev for c in self.ind.cands]

    def recalibrate(self, accepted: set[tuple[int, int]]) -> None:
        calibrate(self.ind, accepted)


def prepare(raws: list[_Raw], mcands: list, body: float, scheme: Scheme) -> Evidence:
    """Pass 2: statistics on the readings the marker lexer produced (`mcands`: objects with .idx and .markers)."""
    vc = [Cand(c.idx, [view(m) for m in c.markers]) for c in mcands]
    attach_features(raws, vc, body, margin_of(raws))
    ind = induce(raws, body, vc, discover=False)
    ind.scope_words = set(scheme.surface)
    calibrate(ind, ind.linked)
    return Evidence(ind, [[usable(ind, m) for m in c.markers] for c in vc], ind.listlike)


def confidence(raws: list[_Raw], nodes: list, front_chars: int, pages: int, regular: int, markers: int) -> dict:
    """Coverage (share of body text inside nodes) x consistency (share of accepted markers that follow their sequence) x granularity (share of
    the text not sitting in a node longer than two pages)."""
    total = sum(len(r.text) for r in raws) or 1
    coverage = (total - front_chars) / total
    consistency = regular / markers if markers else 0.0
    page_chars = total / max(pages, 1)
    big = sum(size for n in nodes if (size := sum(len(t) for t in n.text)) > 2 * max(page_chars, NODE_PAGE_CHARS * 0.25))
    granularity = 1.0 - big / total
    conf = coverage * consistency * granularity if nodes else 0.0
    return {"confidence": round(conf, 3), "coverage": round(coverage, 3), "consistency": round(consistency, 3), "granularity": round(granularity, 3),
            "breaks": markers - regular, "markers": markers, "nodes": len(nodes)}
