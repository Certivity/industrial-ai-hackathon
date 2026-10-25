"""A generic structure parser for the UN regulation PDFs: a marker lexer and a stack parse scored by beam search.

    from regcomp.parse_marker import parse_pdf          # same contract as regcomp.parse.parse_pdf
    doc = parse_pdf("regulations/data/UN_R150/base/UN_R150_base.pdf")

The hand-crafted parser (regcomp.parse) has one rule per numbering scheme (scope headings by style, Part dividers, the rescue of a bold
Appendix at body size, the longest increasing chain of dotted numbers). This one has no per-scheme rules:

1. LEX.  Every line start is read as a marker signature: the leading token is split into components, each with a family (ARABIC,
   LOWER, UPPER, ROMAN, ROMAN_UP, and ARABIC with a letter suffix, "2A"), a decoration (".", ")", "(...)") and an optional keyword
   (Annex, Appendix, Part). "5.1.4." is N.N.N.; "(ii)" is (r); "Annex 2A" is Annex N+A; "Annex 4 - Appendix 1" is two segments. A token
   like "i" is ambiguous (letter 9 or roman 1) and gets both readings; the parse picks one.
2. TWO RELATIONS.  Each family has a successor function and a first value (always 1). Sibling: the same signature and the last
   component is a successor of the previous one (gaps allowed, at a cost). Child: a dotted extension of an open node (2.5 then
   2.5.1), or any signature at its first value (1., (a), A., Appendix 1).
3. STACK + BEAM.  Candidate lines are taken in reading order; for each one the options are reject (body text, a wrapped reference),
   or, for each open level of the stack, sibling (pop to the level and replace) or first child (push). Keyword headings may also be a
   divider that leaves the stack alone (a carry-on "Part III"). Each option is scored by gap size, layout evidence (bold, size,
   margin, what the previous line ended with, what follows the number) and a bonus for nesting the way this signature nested before.
   A beam of states keeps the best paths; the best final path is the structure.
4. LABEL POLICY (the only gold-specific part, LABEL_POLICY below).  The parse gives the whole tree; the policy says which levels are
   citable nodes (scope headings, dotted numbers) and which stay inside their paragraph (letters and romans).

Tables, footnote marks, footers, line extraction and table grids come from regcomp.parse and are not structure logic.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pymupdf

from regcomp import parse as base
from regcomp.parse import ParsedDocument, _attach_grids, _body_size, _build_nodes, _Line, _link_tree, _Raw, _raw_lines

# ------------------------------------------------------------------------------------------------------------------ label policy
LABEL_POLICY = {
    "scope_keywords": ("annex", "appendix", "part"),  # keyword markers that open a scope (kept as a path "Annex 4 Appendix 1 Part 2")
    "citable_dotted": True,                           # a dotted number (N, N.N, N.N.N ...) is a citable paragraph
    "bare_appendix_resets_annex": True,               # a stand-alone "Appendix 1" is cited "Appendix 1 1.2", whatever annex it sits in
    "list_items": "inline",                           # letters, romans and the like stay in the text of their paragraph
}

# ------------------------------------------------------------------------------------------------------------------ parameters
BEAM = 12
GAP_COST = 0.08       # per skipped number, capped at GAP_CAP numbers
GAP_CAP = 12
SKIP_COST = 0.5       # per missing level of a dotted number (6.1 with no 6 open)
FIRST_GAP_COST = 1.0  # a keyword heading that starts above its first value (Annex 3 with no Annex 1 or 2)
POP_COST = 0.35       # popping a level to push a first child of a shallower one
KEYWORD_POP = 0.25    # a first-child keyword heading that closes a keyword scope
DIVIDER_COST = 0.3
CHILD_COST = 0.3
NEST_BONUS = 0.3
LIST_BASE = 0.6       # a list item is worth less than a paragraph
SIZE_HEAVY = 1.15
SIZE_SMALL = 0.9
REF_WORDS = frozenset("paragraph paragraphs annex annexes appendix appendices table tables figure figures part parts section sections "
                      "item items point points no to of in by see with from under per than".split())
SCOPE_RANK = {"annex": 0, "appendix": 1, "part": 2}  # a keyword scope sits under one of lower rank: Annex 4 > Appendix 1 > Part 2
FIRST_DESC_COST = 0.25  # a dotted number that opens a fresh scope above its first value (10 first in a new Part)
DIVIDER_CLASH = 1.0
RANK_CLASH = 0.6      # an Appendix under a Part, a Part under an Appendix: the usual order is Annex > Appendix > Part, but not always
KEYWORDS = {"annex": "Annex", "appendix": "Appendix", "part": "Part"}

# ------------------------------------------------------------------------------------------------------------------ the lexer
ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
COMP = r"\d+[A-Za-z]?|[A-Za-z]+"
KEYWORD_SEG = re.compile(rf"(?i:(annex|appendix|part))\s+({COMP})(?![A-Za-z0-9])")
BARE_KEYWORD = re.compile(r"(?i:(appendix|part))(?![A-Za-z0-9])")
JOIN = re.compile(r"\s*[-–‑—,]?\s*")
PAREN = re.compile(r"\(([A-Za-z]{1,5}|\d{1,3})\)(?=\s|$)")
CLOSE = re.compile(r"([A-Za-z]{1,5}|\d{1,3})\)(?=\s|$)")
DOTTED = re.compile(r"(\d+(?:\.\d+)*)(\.)?")
LETTER_DOT = re.compile(r"([A-Za-z]{1,5})\.(?=\s)")
FIRST = (1, 0)  # every family starts at 1


def roman_value(text: str) -> int | None:
    """Value of a canonical roman numeral ("iv" 4; "iiii" and "vx" are not numerals), else None."""
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


@dataclass(frozen=True)
class Seg:
    """One marker component group: 'Annex 4' is a segment, 'Appendix 1' another, '5.1.4.' one with three components."""
    kw: str       # "", "annex", "appendix", "part"
    key: str      # the signature without decoration for dotted numbers: "N.N.N", "Annex N+A", "(r)", "A."
    val: tuple    # components, each (number, letter-index): (5,0),(1,0),(4,0); "2A" is (2,1); "iii" is (3,0)
    raw: str      # as typed ("4", "2A", "iii", "5.1.4")
    sig: str = ""  # the lexical signature with the letter suffix ("Annex N+A"); `key` is the family the relations compare ("Annex N")

    @property
    def dotted(self) -> bool:
        return not self.kw and self.key.startswith("N") and set(self.key) <= set("N.")

    @property
    def first(self) -> bool:
        return all(v == FIRST for v in self.val)


@dataclass(frozen=True)
class Marker:
    segs: tuple[Seg, ...]
    deco: str   # ".", ")", "()" or "" (no decoration: a heading that lost its final dot)
    rest: str   # the text after the marker


def _letter_readings(token: str, deco: str) -> list[Seg]:
    """The readings of a letter token: a single letter is a LOWER or UPPER letter; a run of roman letters is a roman numeral; a lone
    "i", "v", "x", ... is both."""
    out: list[Seg] = []
    fam = "()" if deco == "()" else ")" if deco == ")" else "."
    wrap = (lambda f: f"({f})") if deco == "()" else (lambda f: f + fam)
    if len(token) == 1:
        out.append(Seg("", wrap("a" if token.islower() else "A"), ((ord(token.lower()) - 96, 0),), token))
    value = roman_value(token) if token.isalpha() else None
    if value is not None and (token.islower() or token.isupper()):
        out.append(Seg("", wrap("r" if token.islower() else "R"), ((value, 0),), token))
    return out


def _comp_readings(text: str, kw: str) -> list[Seg]:
    """The readings of the component after a keyword: 4, 2A, 1a, I, A."""
    if (m := re.fullmatch(r"(\d+)([A-Za-z]?)", text)):
        n, s = int(m.group(1)), m.group(2)
        letter = (ord(s.lower()) - 96) if s else 0
        return [Seg(kw, f"{KEYWORDS[kw]} N", ((n, letter),), text, f"{KEYWORDS[kw]} N" + (("+a" if s.islower() else "+A") if s else ""))]
    out = []
    if len(text) == 1 and text.isalpha():
        out.append(Seg(kw, f"{KEYWORDS[kw]} " + ("a" if text.islower() else "A"), ((ord(text.lower()) - 96, 0),), text))
    value = roman_value(text) if text.isalpha() else None
    if value is not None and (text.isupper() or text.islower()):
        out.append(Seg(kw, f"{KEYWORDS[kw]} " + ("r" if text.islower() else "R"), ((value, 0),), text))
    return out


def lex(text: str) -> list[Marker]:
    """Every reading of the marker at the start of a line (none if the line has no marker)."""
    # a keyword marker: "Annex 4", "Annex 2A", "Appendix 1", "Part I", "Annex 4 - Appendix 1"
    if (m := KEYWORD_SEG.match(text)):
        chains: list[list[Seg]] = [[s] for s in _comp_readings(m.group(2), m.group(1).lower())]
        pos = m.end()
        while chains:
            j = JOIN.match(text, pos)
            if j is None:
                break
            nxt = KEYWORD_SEG.match(text, j.end())
            readings = _comp_readings(nxt.group(2), nxt.group(1).lower()) if nxt else []
            if nxt is not None and readings:
                if nxt.group(1).lower() == chains[0][0].kw:
                    break
                chains = [c + [r] for c in chains for r in readings]
                pos = nxt.end()
                continue
            if (bare := BARE_KEYWORD.match(text, j.end())) and bare.group(1).lower() != chains[0][0].kw:
                # "Annex 2B - Appendix Containers only": a keyword with no number is the only one, so the first
                kw = bare.group(1).lower()
                chains = [c + [Seg(kw, f"{KEYWORDS[kw]} N", (FIRST,), "1")] for c in chains]
                pos = bare.end()
            break
        rest = text[pos:].lstrip(" -–:.")
        return [Marker(tuple(c), "", rest) for c in chains]
    if text.startswith("("):
        if (m := PAREN.match(text)):
            tok = m.group(1)
            segs = [Seg("", "(N)", ((int(tok), 0),), tok)] if tok.isdigit() else _letter_readings(tok, "()")
            return [Marker((s,), "()", text[m.end():].lstrip()) for s in segs]
        return []
    if text[:1].isdigit():
        if (m := DOTTED.match(text)):
            after = text[m.end():]
            if m.group(2):  # "5.1.4." followed by a space, the end, or a capital with no space ("5.1.2.An immobilizer")
                if not (after == "" or after[0].isspace() or re.match(r"[A-Z][a-z]", after)):
                    return []
                deco = "."
            else:  # no final dot: a heading ("5.7 Title", "1 Scope") needs a capital after a space, and not a whole sentence
                if len(text) > 120 or not re.match(r"\s+[A-Z]", after):
                    # "12)" style numbers fall through to the close-paren reading
                    return _close_paren(text)
                deco = ""
            comps = m.group(1).split(".")
            seg = Seg("", ".".join(["N"] * len(comps)), tuple((int(c), 0) for c in comps), m.group(1))
            return [Marker((seg,), deco, after.lstrip())]
        return []
    if text[:1].isalpha():
        if (m := LETTER_DOT.match(text)):
            return [Marker((s,), ".", text[m.end():].lstrip()) for s in _letter_readings(m.group(1), ".")]
        return _close_paren(text)
    return []


def _close_paren(text: str) -> list[Marker]:
    if (m := CLOSE.match(text)):
        tok = m.group(1)
        segs = [Seg("", "N)", ((int(tok), 0),), tok)] if tok.isdigit() else _letter_readings(tok, ")")
        return [Marker((s,), ")", text[m.end():].lstrip()) for s in segs]
    return []


# ------------------------------------------------------------------------------------------------------------------ relations
def gap(prev: tuple, cur: tuple) -> int | None:
    """How many values were skipped going from `prev` to `cur` (same signature, only the last component differs), None if `cur` is
    not a successor. A component with a letter suffix has two successors: 2 -> 2A, 2 -> 3 (and 3A); 2A -> 2B, 2A -> 3."""
    if prev[:-1] != cur[:-1]:
        return None
    (n, s), (m, t) = prev[-1], cur[-1]
    if m == n:
        return t - s - 1 if t > s else None
    if m > n:
        return (m - n - 1) + max(t - 1, 0)
    return None


def succ(val: tuple) -> tuple:
    """The plain successor of a value (last component + 1)."""
    (n, s) = val[-1]
    return val[:-1] + ((n + 1, 0),)


# ------------------------------------------------------------------------------------------------------------------ the parse
@dataclass(frozen=True)
class Frame:
    key: str
    val: tuple
    kw: str
    raw: str
    dotted: bool
    solo: bool = False  # a keyword heading that stood alone on its line ("Appendix 1"), not in a compound ("Annex 4 - Appendix 1")


@dataclass
class Cand:
    idx: int          # index in the raw lines
    markers: list[Marker]
    gain: float       # evidence of the line, before the structure terms


@dataclass
class State:
    score: float
    stack: tuple[Frame, ...]
    mem: tuple        # ((key, val), ...) of the last keyword heading of each signature (for dividers)
    nest: frozenset   # (key, parent key) pairs seen so far
    trail: tuple | None  # (previous trail, candidate position, kind, stack after, segs) of the accepted candidates

    def sig(self) -> tuple:
        return tuple((f.key, f.val) for f in self.stack), self.mem


def _frame(seg: Seg, solo: bool = False) -> Frame:
    return Frame(seg.key, seg.val, seg.kw, seg.raw, seg.dotted, solo)


def _keyword_options(stack: tuple[Frame, ...], seg: Seg, lo: int, allow_equal: bool, solo: bool) -> list[tuple[tuple[Frame, ...], float, int]]:
    """Ways a keyword segment can go onto the stack, looking at the frames from `lo` up: sibling of an open frame, equal to one (the
    first half of "Annex 4 - Appendix 1"), or a first child (also one that starts above its first value, at a cost). A keyword may only
    sit under one of lower rank (Annex, Appendix, Part), and closes any of equal or higher rank for free. Returns (stack after,
    structure cost, `lo` for the next segment)."""
    out: list[tuple[tuple[Frame, ...], float, int]] = []
    rank = SCOPE_RANK[seg.kw]
    for j in range(lo, len(stack)):
        f = stack[j]
        if f.key != seg.key:
            continue
        if allow_equal and f.val == seg.val:
            out.append((stack, 0.0, j + 1))
        elif (g := gap(f.val, seg.val)) is not None:
            out.append((stack[:j] + (_frame(seg, solo),), GAP_COST * min(g, GAP_CAP), j + 1))
    kw_at = [k for k, f in enumerate(stack) if f.kw and k >= lo]
    first_gap = sum(v[0] - 1 for v in seg.val) if len(seg.val) == 1 else 99
    for a in {lo, *(k + 1 for k in kw_at)}:
        popped = stack[a:]
        if any(f.key == seg.key for f in popped):  # that is a sibling, handled above
            continue
        parent = stack[a - 1] if a else None
        clash = parent is not None and SCOPE_RANK.get(parent.kw, -1) >= rank
        if clash and parent.kw == seg.kw:
            continue
        cost = (RANK_CLASH if clash and lo == 0 else 0.0) + KEYWORD_POP * sum(1 for f in popped if f.kw and SCOPE_RANK[f.kw] < rank) + (0.0 if seg.first else FIRST_GAP_COST * min(first_gap, 4))
        if seg.first or first_gap <= 4:
            out.append((stack[:a] + (_frame(seg, solo),), cost, a + 1))
    return out


def _dotted_option(stack: tuple[Frame, ...], seg: Seg) -> tuple[tuple[Frame, ...], float] | None:
    """A dotted number goes under its deepest open prefix (5.1.4 under 5.1), or under the scope; it has to be above the number that
    stood there before (5.1.4 after 5.1.3 or after 5.1.3.2; 5.1.3 after 5.1.4 is out of order). Missing levels and skipped numbers cost."""
    root = max((k + 1 for k, f in enumerate(stack) if f.kw), default=0)
    val = seg.val
    base_at, prefix_len = root, 0
    for j in range(len(stack) - 1, root - 1, -1):
        f = stack[j]
        if f.dotted and len(f.val) < len(val) and val[: len(f.val)] == f.val:
            base_at, prefix_len = j + 1, len(f.val)
            break
    if base_at < len(stack) and stack[base_at].dotted:
        before = stack[base_at].val
        d = next((i for i, (a, b) in enumerate(zip(before, val)) if a != b), None)
        if d is None or val[d] < before[d]:
            return None
        g = max(val[d][0] - before[d][0] - 1, 0) + sum(c[0] - 1 for c in val[d + 1:])
        # the levels above this number that an earlier sibling already went without are not missing again
        skip = (len(val) - 1) - max(prefix_len, min(d, len(val) - 1))
        return stack[:base_at] + (_frame(seg),), GAP_COST * min(g, GAP_CAP) + SKIP_COST * skip
    else:
        g = (val[prefix_len][0] - 1) + sum(c[0] - 1 for c in val[prefix_len + 1:])
        if prefix_len == 0:
            g = FIRST_DESC_COST / GAP_COST * min(g, 8)
    skip = len(val) - prefix_len - 1
    return stack[:base_at] + (_frame(seg),), GAP_COST * min(g, GAP_CAP * 4) + SKIP_COST * skip


def _list_options(stack: tuple[Frame, ...], seg: Seg) -> list[tuple[tuple[Frame, ...], float]]:
    """A list item (letter, roman, number in brackets): the sibling of the nearest open frame with its signature, or a first child."""
    out: list[tuple[tuple[Frame, ...], float]] = []
    for j in range(len(stack) - 1, -1, -1):
        f = stack[j]
        if f.key == seg.key:
            if (g := gap(f.val, seg.val)) is not None:
                out.append((stack[:j] + (_frame(seg),), GAP_COST * min(g, GAP_CAP) * 2))
            break
    if seg.first:
        for a in range(len(stack), max(len(stack) - 4, 0) - 1, -1):
            if any(f.key == seg.key for f in stack[a:]):
                continue
            parent = stack[a - 1] if a else None
            out.append((stack[:a] + (_frame(seg),), CHILD_COST + POP_COST * (len(stack) - a) + (0.3 if parent is None or parent.kw else 0.0)))
    return out


def _transitions(state: State, marker: Marker) -> Iterable[tuple[str, tuple[Frame, ...], tuple, float]]:
    """(kind, stack after, memory after, structure cost) for accepting this reading in this state."""
    segs = marker.segs
    first = segs[0]
    if first.kw:
        results: list[tuple[tuple[Frame, ...], float, int]] = [(state.stack, 0.0, 0)]
        for n, seg in enumerate(segs):
            nxt: list[tuple[tuple[Frame, ...], float, int]] = []
            for stack, cost, lo in results:
                nxt += [(s, cost + c, k) for s, c, k in _keyword_options(stack, seg, lo, allow_equal=n < len(segs) - 1, solo=len(segs) == 1)]
            results = nxt
        mem = dict(state.mem)
        for seg in segs:
            mem[seg.key] = seg.val
        mem_t = tuple(sorted(mem.items()))
        for stack, cost, _ in results:
            yield "scope", stack, mem_t, cost
        if len(segs) == 1:  # a heading that opens no scope: the numbering goes on after it
            last = dict(state.mem).get(first.key)
            g = 0 if (last is None and first.first) else (gap(last, first.val) if last is not None else None)
            if g is not None:
                same = any(f.key == first.key for f in state.stack)  # a divider beside an open scope of its own kind is inconsistent
                yield "divider", state.stack, mem_t, DIVIDER_COST + GAP_COST * min(g, GAP_CAP) + (DIVIDER_CLASH if same else 0.0)
        return
    if first.dotted:
        if (opt := _dotted_option(state.stack, first)):
            yield "para", opt[0], state.mem, opt[1]
        return
    for stack, cost in _list_options(state.stack, first):
        yield "item", stack, state.mem, cost


def _evidence(raw: _Raw, prev: _Raw | None, marker: Marker, body: float, margin: float) -> float:
    """What the line itself says about being a marker: layout and the text around the number. No structure here."""
    seg = marker.segs[0]
    ratio = raw.size / body if body else 1.0
    e = 0.0
    if abs(raw.bbox[0] - margin) > 4:
        e -= 0.6
    if seg.kw:
        e += 0.6 if raw.bold else -2.0  # a heading is set in bold; a line of running text that starts "Annex 5 to this" is not
        e += 0.5 if ratio >= SIZE_HEAVY else 0.0
        e -= 1.5 if ratio < SIZE_SMALL else 0.0
        e -= 1.0 if raw.text.rstrip().endswith((".", ",", ";")) else 0.0
        e -= 1.0 if len(raw.text) > 110 else 0.0
        e -= 1.0 if marker.rest[:1].islower() else 0.0
        return 1.0 + e
    base_gain = 1.0 if seg.dotted else LIST_BASE
    if raw.bold:
        e += 0.3
    if ratio >= SIZE_HEAVY:
        e += 0.3
    if ratio < SIZE_SMALL:
        e -= 1.5
    if prev is not None:
        end = prev.text.rstrip()[-1:]
        words = prev.text.split()
        if end in ".:;" or not end:
            pass
        elif words and words[-1] == words[-1].lower() and words[-1].strip("(),") in REF_WORDS:
            e -= 1.2  # "... in paragraph" / "6.4." : a wrapped reference
        else:
            e -= 0.3
    if not marker.rest:
        e -= 0.4
    elif marker.rest[:1].islower():
        e -= 0.2
    if marker.deco == "" and seg.dotted:
        e -= (0.4 if len(seg.val) > 1 else 1.3) - (0.9 if (raw.bold or ratio >= SIZE_HEAVY) else 0.0)
    return base_gain + e


def _parse_stack(raws: list[_Raw], body: float, margin: float) -> tuple[list[Cand], State]:
    cands: list[Cand] = []
    for i, raw in enumerate(raws):
        markers = lex(raw.text)
        if markers:
            cands.append(Cand(i, markers, 0.0))
    beam = [State(0.0, (), (), frozenset(), None)]
    for pos, cand in enumerate(cands):
        raw = raws[cand.idx]
        prev = raws[cand.idx - 1] if cand.idx else None
        nxt: dict[tuple, State] = {}

        def offer(state: State) -> None:
            k = state.sig()
            if k not in nxt or nxt[k].score < state.score:
                nxt[k] = state

        for st in beam:
            offer(st)  # reject
            for marker in cand.markers:
                evidence = _evidence(raw, prev, marker, body, margin)
                for kind, stack, mem, cost in _transitions(st, marker):
                    if kind == "divider":
                        offer(State(st.score + evidence - cost, stack, mem, st.nest, (st.trail, pos, kind, stack, marker)))
                        continue
                    parent = stack[-len(marker.segs) - 1].key if len(stack) > len(marker.segs) else ""
                    pair = (stack[-1].key, parent)
                    bonus = NEST_BONUS if pair in st.nest else 0.0
                    offer(State(st.score + evidence - cost + bonus, stack, mem, st.nest | {pair}, (st.trail, pos, kind, stack, marker)))
        beam = sorted(nxt.values(), key=lambda s: -s.score)[:BEAM]
    _parse_stack.last_beam = beam
    return cands, beam[0]


def _events(trail: tuple | None) -> list[tuple]:
    out = []
    while trail is not None:
        out.append(trail[1:])
        trail = trail[0]
    return out[::-1]


def _scope_of(stack: tuple[Frame, ...]) -> str:
    """The scope label of a stack: its keyword frames in order, "Annex 4 Appendix 1 Part 2"."""
    path: list[str] = []
    for f in stack:
        if f.kw in LABEL_POLICY["scope_keywords"]:
            if f.kw == "appendix" and f.solo and LABEL_POLICY["bare_appendix_resets_annex"]:
                path = []
            path.append(f"{KEYWORDS[f.kw]} {f.raw}")
    return " ".join(path)


def parse_pdf(path: str | Path, grids: bool = True) -> ParsedDocument:
    """Parse one regulation PDF with the marker lexer and the stack parse. Same contract as regcomp.parse.parse_pdf."""
    pdf = pymupdf.open(path)
    doc = ParsedDocument(path=Path(path), pages=pdf.page_count)
    raws = _raw_lines(pdf, doc)
    return _finish(pdf, doc, raws, grids)


def _margin(raws: list[_Raw]) -> float:
    return Counter(round(r.bbox[0]) for r in raws).most_common(1)[0][0] if raws else 0.0


def _finish(pdf, doc: ParsedDocument, raws: list[_Raw], grids: bool, body_size: float | None = None) -> ParsedDocument:
    doc.body_size = body_size or _body_size(raws)
    cands, best = _parse_stack(raws, doc.body_size, _margin(raws))
    lines, scopes, starts = _lines_from_parse(raws, cands, best, doc)
    owners, slots = _build_nodes(lines, scopes, starts, doc)
    _link_tree(doc)
    if grids and pdf is not None:
        _attach_grids(pdf, lines, owners, slots, doc)
    return doc


def _lines_from_parse(raws: list[_Raw], cands: list[Cand], best: State, doc: ParsedDocument):
    """Apply the label policy to the best parse: scope of every line, scope headings, dividers, and the dotted numbers that start paragraphs."""
    events = {cands[pos].idx: (kind, stack, marker) for pos, kind, stack, marker in _events(best.trail)}
    scopes = [""]
    heading_of: dict[int, tuple[str, str]] = {}
    starts: dict[int, tuple[int, ...]] = {}
    lines: list[_Line] = []
    note = 0
    scope_id = 0
    doc.candidates = len(cands)
    for i, raw in enumerate(raws):
        heading = label = None
        if (ev := events.get(i)):
            kind, stack, marker = ev
            segs = marker.segs
            if kind == "scope":
                scope = _scope_of(stack)
                scopes.append(scope)
                scope_id = len(scopes) - 1
                heading = "annex-appendix" if len(segs) > 1 else segs[0].kw
            elif kind == "divider":
                heading, label = segs[0].kw, f"{KEYWORDS[segs[0].kw]} {segs[0].raw}"
            elif kind == "para" and LABEL_POLICY["citable_dotted"]:
                starts[i] = tuple(c[0] for c in segs[0].val)
            # kind == "item": a list item stays in the text of its paragraph (LABEL_POLICY["list_items"])
        elif markers_dotted(raw.text):
            doc.left_out.append((raw.page, raw.text[:60], scopes[scope_id]))
        if raw.lead_digit and raw.size < base.NOTE_LEAD * doc.body_size:
            note = 1
        elif note and raw.size < base.NOTE_BODY * doc.body_size and not raw.bold:
            note = 2
        else:
            note = 0
        lines.append(_Line(len(lines), raw.page, raw.text, raw.bold, raw.size, scope_id, heading, raw.bbox, note,
                           label or (scopes[scope_id] if heading else "")))
    return lines, scopes, starts


def markers_dotted(text: str) -> bool:
    return any(m.segs[0].dotted for m in lex(text))


def parse_raws(raws: list[_Raw], pages: int = 1, grids: bool = False, body_size: float | None = None) -> ParsedDocument:
    """The parse on lines that are already extracted (tests, the scalability benchmark); no PDF, so no table grids."""
    return _finish(None, ParsedDocument(path=Path("<lines>"), pages=pages), raws, False, body_size)
