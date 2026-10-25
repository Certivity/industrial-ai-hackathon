"""The graph the agent walks: one regulation version parsed by the selected parser (store.parser_module: marker by default), with the views the agent needs (outline, table of contents,
subtree text, search, references) and the grounding check (is a quote really in a node, and on which page).

A node is addressed by its label, in the gold's format ("6.10.4.2", "Annex 4 Part 1 1.2", "5.1.4.4.1. Table 3"). The model only ever
names labels that this class resolves; the page and the paragraph of an emitted requirement are filled in from the node, never written
by the model.
"""

from __future__ import annotations

import difflib
import math
import os
import re
import threading
from collections import Counter, defaultdict
from typing import Iterable

from regcomp import corpus
from regcomp.parse import ParsedDocument, parse_pdf


def parser_name() -> str:
    """REGCOMP_PARSER: "marker" (default) or "rules"."""
    return os.environ.get("REGCOMP_PARSER", "marker")


def parser_module():
    """The module that parses regulation PDFs: the marker parser (generic lexer + stack parse with per-document induction, the default),
    or with REGCOMP_PARSER=rules the hand-crafted rule parser. The main goal, the regulation cards and the drift pipeline all use this."""
    if parser_name() == "rules":
        from regcomp import parse as module
    else:
        from regcomp import parse_marker as module
    return module


def _parser():
    return parser_module().parse_pdf


CONTENT = ("para", "table")
CHARS_PER_TOKEN = 3.3  # measured on the regulation text with the token counter: 2.3 for number-heavy text, about 4 for prose
FUZZY_QUOTE = 0.9


# ------------------------------------------------------------------------------------------------------------------ labels
def label_key(label) -> str:
    """The same paragraph written in the usual different ways gives the same key. This is tools/score_local.py::_paragraph_key (the
    platform's normalisation); eval/test_ai_agent.py checks that the two agree."""
    text = str(label or "").casefold().replace("§", " ")
    text = re.sub(r"[,;:()\[\]]", " ", text)
    text = re.sub(r"(?<![0-9a-z])\.|\.(?![0-9a-z])", " ", text)
    text = " ".join(text.split())
    text = re.sub(r"^(paragraphs?|para|par|section|clause)\s+", "", text)
    return text


REG_PREFIX = re.compile(r"^(?:un\s+)?(?:r|gtr|regulation(?:\s+no\.?)?)\s*\d+[a-z]?\s*[:,\-–|/]*\s*", re.I)


# ------------------------------------------------------------------------------------------------------------- text, search
STOP = frozenset("""a an and are as at be been being but by can for from has have if in into is it its may no not of on or such than that the
their then there these they this those to under up was were when where which while who with within would shall should must will any all each
other only also one two per used use using same""".split())


def stem(word: str) -> str:
    if len(word) <= 3:
        return word
    for suffix, replacement in (("ations", ""), ("ation", ""), ("ions", ""), ("ion", ""), ("ives", ""), ("ive", ""), ("ors", ""), ("or", ""),
                                ("ings", ""), ("ing", ""), ("ies", "y"), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: len(word) - len(suffix)] + replacement
            break
    return word[:-1] if len(word) > 4 and word[-1] == word[-2] and word[-1] not in "aeiou" else word


def words(text: str) -> list[str]:
    return [stem(w) for w in re.split(r"[^a-z0-9]+", text.lower()) if w and not w.isdigit() and w not in STOP]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.length = [len(d) for d in docs]
        self.avg = (sum(self.length) / len(docs)) if docs else 1.0
        df = Counter(t for c in self.tf for t in c)
        self.idf = {t: math.log(1 + (len(docs) - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self.posting: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(self.tf):
            for t in c:
                self.posting[t].append(i)

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for t in set(query):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in self.posting[t]:
                f = self.tf[i][t]
                out[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.length[i] / (self.avg or 1)))
        return out


THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def norm_tokens(text: str) -> list[str]:
    """Alphanumeric tokens, case-folded: a quote survives a dropped full stop, a table pipe, a wrapped hyphen, a changed space or a
    thousands separator ("1,500" and "1500" are the same token)."""
    return re.findall(r"[^\W_]+", THOUSANDS.sub("", text).casefold())


def _coherent_share(hay: list[str], needle: list[str]) -> float:
    """Share of `needle` found in `hay` in runs of at least 2 tokens (difflib), so scattered common words do not count."""
    sm = difflib.SequenceMatcher(None, hay, needle, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks() if b.size >= 2) / len(needle)


def find_run(hay: list[str], needle: list[str]) -> int:
    """Index where `needle` occurs as a contiguous run in `hay`, or -1."""
    if not needle or len(needle) > len(hay):
        return -1
    first, n = needle[0], len(needle)
    for i in range(len(hay) - n + 1):
        if hay[i] == first and hay[i:i + n] == needle:
            return i
    return -1


# ----------------------------------------------------------------------------------------------------------------- edges
NUM = r"\d+(?:\.\d+)*"
LIST = rf"((?:\s*(?:,|and/or|and|or|to)\s*{NUM}\.?)*)"
REF_OF_ANNEX = re.compile(rf"\bparagraphs?\s+({NUM})\.?{LIST}\s+of\s+(?:Part\s+([A-Z]|\d+)\s+of\s+)?Annex\s+(\d+[A-Za-z]?)")
REF_ANNEX_FIRST = re.compile(rf"\bAnnex\s+(\d+[A-Za-z]?),?\s*(?:Part\s+([A-Z]|\d+),?\s*)?paragraphs?\s+({NUM})\.?{LIST}")
REF_OF_REG = re.compile(rf"\bparagraphs?\s+({NUM})\.?{LIST}\s+of\s+(this|UN)\s+Regulation(?:\s+No\.?\s*(\d+[A-Z]?))?")
REF_PLAIN = re.compile(rf"\bparagraphs?\s+({NUM})\.?(?:\s*\([a-z]+\))*{LIST}")
CITE_REG = re.compile(r"\b(?:UN\s+)?Regulations?\s+(?:Nos?\.?\s*)?([1-9]\d*(?:-?[A-Z])?(?:\s*(?:,|and/or|and|or)\s*(?:Nos?\.?\s*)?[1-9]\d*(?:-?[A-Z])?)*)")


def _numbers(first: str, rest: str) -> list[tuple[int, ...]]:
    return [tuple(int(x) for x in s.split(".")) for s in [first, *re.findall(NUM, rest or "")]]


def cited_regulations(text: str) -> list[str]:
    """'UN R48' style names of the regulations a text cites ("UN Regulation No. 7", "Regulations Nos. 13 and 13-H"). A number with a
    leading zero ("00 series") is not a regulation."""
    return ["UN R" + x.replace("-", "") for m in CITE_REG.finditer(text) for x in re.findall(r"\d+(?:-?[A-Z])?", m.group(1))]


def fmt_pages(a: int, b: int) -> str:
    return f"p{a}" if a == b else f"p{a}-{b}"


class RegGraph:
    """One regulation version as a tree of nodes. Built on regcomp.parse (grids included, so tables read as one row per line)."""

    def __init__(self, reg: str, role: str = "base", grids: bool = True, doc: ParsedDocument | None = None):
        entry = corpus.entry_for(reg)
        if doc is None:
            path = corpus.pdf_path(entry, role)
            if path is None:
                raise FileNotFoundError(f"the {role} PDF of {reg} is not in regulations/data; run tools/fetch_regulations.py --out regulations/data")
            doc = _parser()(path, grids=grids)
        self.reg, self.role, self.title = reg, role, entry["title"]
        self.version = corpus.version_label(entry, role)
        self.doc = doc
        self.nodes = self.doc.nodes
        n = len(self.nodes)
        self.parent = [getattr(x, "parent", -1) for x in self.nodes]
        self.children: list[list[int]] = [[] for _ in range(n)]
        for i, p in enumerate(self.parent):
            if 0 <= p < n and p != i:
                self.children[p].append(i)
        seen: Counter = Counter()
        self.ids: list[str] = []
        for node in self.nodes:  # labels are unique in practice; a repeat gets a suffix so that every node stays addressable
            base = node.label or f"node p{node.page_start}"
            seen[base] += 1
            self.ids.append(base if seen[base] == 1 else f"{base} [{seen[base]}]")
        self.by_id = {name: i for i, name in enumerate(self.ids)}
        self._by_key: dict[str, int] = {}
        for i, name in enumerate(self.ids):
            self._by_key.setdefault(label_key(name), i)
        self.text = [getattr(x, "model_text", None) or x.body for x in self.nodes]
        self.depth = [0] * n
        for i in range(n):
            if self.parent[i] >= 0:
                self.depth[i] = self.depth[self.parent[i]] + 1
        # subtree sizes, bottom-up (a parent always precedes its children in document order)
        self.sub_chars = [len(t) for t in self.text]
        self.sub_content = [1 if x.kind in CONTENT else 0 for x in self.nodes]
        self.sub_pages = [(x.page_start, x.page_end) for x in self.nodes]
        for i in range(n - 1, -1, -1):
            p = self.parent[i]
            if p >= 0:
                self.sub_chars[p] += self.sub_chars[i]
                self.sub_content[p] += self.sub_content[i]
                a, b = self.sub_pages[p], self.sub_pages[i]
                self.sub_pages[p] = (min(a[0], b[0]), max(a[1], b[1]))
        self._lock = threading.Lock()
        self._bm25: BM25 | None = None
        self._search_ids: list[int] = []
        self._ntok: dict[int, list[str]] = {}
        self._edges: tuple[list, list] | None = None

    # ------------------------------------------------------------------------------------------------------------- addressing
    def resolve(self, text: str | None) -> int | None:
        """The node a label names, tolerating the usual spellings ('paragraph 6.10.', 'UN R48 6.10', 'annex 6  part 4')."""
        if not text:
            return None
        text = text.strip()
        if text in self.by_id:
            return self.by_id[text]
        for candidate in (text, REG_PREFIX.sub("", text)):
            found = self._by_key.get(label_key(candidate))
            if found is not None:
                return found
        return None

    def suggest(self, text: str, n: int = 4) -> list[str]:
        keys = difflib.get_close_matches(label_key(REG_PREFIX.sub("", text or "")), list(self._by_key), n=n, cutoff=0.6)
        return [self.ids[self._by_key[k]] for k in keys]

    def subtree(self, i: int) -> list[int]:
        """The node and all its descendants in document order."""
        out, stack = [], [i]
        while stack:
            j = stack.pop()
            out.append(j)
            stack.extend(self.children[j])
        return sorted(out)

    def contained(self, i: int, j: int) -> bool:
        """Whether node j is node i or one of its descendants."""
        while j >= 0:
            if j == i:
                return True
            j = self.parent[j]
        return False

    def is_content(self, i: int) -> bool:
        return self.nodes[i].kind in CONTENT

    def tokens_of(self, chars: int) -> int:
        return round(chars / CHARS_PER_TOKEN)

    def page_range(self, i: int) -> str:
        return fmt_pages(*self.sub_pages[i])

    def heading(self, i: int, width: int = 80) -> str:
        return re.sub(r"\s+", " ", self.nodes[i].title(width)).strip()

    # ---------------------------------------------------------------------------------------------------------------- views
    def line(self, i: int, indent: int = 0) -> str:
        n = self.nodes[i]
        size = f"{self.sub_content[i]} nodes ~{self.sub_chars[i] / CHARS_PER_TOKEN / 1000:.1f}k tok" if self.children[i] else "leaf"
        kind = "" if n.kind == "para" else f" [{n.kind}]"
        return f"{'  ' * indent}{self.ids[i]}{kind} | {self.heading(i, 76)} | {self.page_range(i)} | {size}"

    def outline(self) -> str:
        """Every section (a node with children, an annex, an appendix or a part) with its size, indented by depth. Leaves are not listed:
        a section's own text and its leaves are read with read_node."""
        rows = []
        for i, n in enumerate(self.nodes):
            if self.children[i] or n.kind not in CONTENT:
                rows.append(self.line(i, min(self.depth[i], 6)))
        return "\n".join(rows)

    def toc(self, i: int | None, depth: int = 1, limit: int = 120) -> str:
        """The children of node i (the top level when i is None), `depth` levels down."""
        tops = [j for j in range(len(self.nodes)) if self.parent[j] < 0] if i is None else self.children[i]
        rows: list[str] = []

        def walk(js: list[int], level: int) -> None:
            for j in js:
                if len(rows) >= limit:
                    return
                rows.append(self.line(j, level))
                if level + 1 < depth:
                    walk(self.children[j], level + 1)

        walk(tops, 0)
        if len(rows) >= limit:
            rows.append(f"... more than {limit} entries; ask for a narrower node")
        return "\n".join(rows) if rows else "(no children)"

    def render(self, idxs: Iterable[int]) -> str:
        """Nodes as the model reads them: <node id=... page=... parent=...> text </node>. A table node carries its markdown grid."""
        out = []
        for i in idxs:
            n = self.nodes[i]
            attrs = [f'id="{self.ids[i].replace(chr(34), chr(39))}"']
            if n.kind != "para":
                attrs.append(f'kind="{n.kind}"')
            attrs.append(f'page="{n.page_start if n.page_start == n.page_end else f"{n.page_start}-{n.page_end}"}"')
            if self.parent[i] >= 0:
                attrs.append(f'parent="{self.ids[self.parent[i]].replace(chr(34), chr(39))}"')
            out.append(f"<node {' '.join(attrs)}>\n{self.text[i]}\n</node>")
        return "\n".join(out)

    # --------------------------------------------------------------------------------------------------------------- search
    def search(self, query: str, top_k: int = 8, within: int | None = None) -> list[tuple[int, float]]:
        """BM25 over each content node's own text together with its breadcrumb (the titles of its ancestors)."""
        with self._lock:
            if self._bm25 is None:
                self._search_ids = [i for i, n in enumerate(self.nodes) if n.kind in CONTENT]
                self._bm25 = BM25([words(getattr(self.nodes[i], "path", "") + " " + self.text[i]) for i in self._search_ids])
        scores = self._bm25.scores(words(query))
        pool = None if within is None else set(self.subtree(within))
        ranked = sorted(((self._search_ids[k], s) for k, s in scores.items() if pool is None or self._search_ids[k] in pool),
                        key=lambda item: -item[1])
        return ranked[:top_k]

    # --------------------------------------------------------------------------------------------------------------- edges
    def edges(self) -> tuple[list, list]:
        """(refs, cites): refs are (source, target or None, other regulation or None) for 'paragraph 5.8.1' style references; cites are
        (source, 'UN R7') for citations of other regulations."""
        with self._lock:
            if self._edges is None:
                by_key: dict = {}
                for i, node in enumerate(self.nodes):
                    if node.kind == "para":
                        by_key.setdefault((node.scope, node.num), i)
                refs, cites = [], []
                for i, node in enumerate(self.nodes):
                    if node.kind not in CONTENT:
                        continue
                    body, claimed = node.body, []
                    for pattern, form in ((REF_OF_ANNEX, "annex"), (REF_ANNEX_FIRST, "annex_first"), (REF_OF_REG, "reg"), (REF_PLAIN, "plain")):
                        for m in pattern.finditer(body):
                            if any(a <= m.start() < b for a, b in claimed):
                                continue
                            claimed.append((m.start(), m.end()))
                            scope = node.scope
                            if form == "annex":
                                first, rest, part, annex = m.groups()
                                scope = f"Annex {annex}" + (f" Part {part}" if part else "")
                            elif form == "annex_first":
                                annex, part, first, rest = m.groups()
                                scope = f"Annex {annex}" + (f" Part {part}" if part else "")
                            elif form == "reg":
                                first, rest, which, number = m.groups()
                                if which == "UN" and number:
                                    refs += [(i, None, f"UN R{number}") for _ in _numbers(first, rest)]
                                    continue
                                scope = ""
                            else:
                                first, rest = m.groups()
                            for num in _numbers(first, rest):
                                target = by_key.get((scope, num))
                                if target is None and form == "plain":
                                    target = by_key.get(("", num))
                                refs.append((i, target, None))
                    cites += [(i, r) for r in cited_regulations(body)]
                self._edges = (refs, cites)
            return self._edges

    def references(self, i: int) -> dict:
        refs, cites = self.edges()
        out = [j for s, j, other in refs if s == i and j is not None and j != i]
        incoming = [s for s, j, other in refs if j == i and s != i]
        return {"refers_to": list(dict.fromkeys(out)), "referred_by": list(dict.fromkeys(incoming)),
                "cites": list(dict.fromkeys(r for s, r in cites if s == i and r != self.reg))}

    def cited_in(self, idxs: Iterable[int]) -> dict[str, dict]:
        """Other regulations cited by the text of these nodes: {'UN R7': {'count': 2, 'nodes': [...], 'snippet': '...'}}."""
        found: dict[str, dict] = {}
        for i in idxs:
            body = self.nodes[i].body
            for m in CITE_REG.finditer(body):
                for reg in ["UN R" + x.replace("-", "") for x in re.findall(r"\d+(?:-?[A-Z])?", m.group(1))]:
                    if reg == self.reg:
                        continue
                    row = found.setdefault(reg, {"count": 0, "nodes": [], "snippet": ""})
                    row["count"] += 1
                    if self.ids[i] not in row["nodes"] and len(row["nodes"]) < 6:
                        row["nodes"].append(self.ids[i])
                    if not row["snippet"]:
                        row["snippet"] = body[max(0, m.start() - 140): m.end() + 100].replace("\n", " ")
        return found

    # ------------------------------------------------------------------------------------------------------------- grounding
    def _tokens(self, i: int) -> list[str]:
        toks = self._ntok.get(i)
        if toks is None:
            toks = self._ntok[i] = norm_tokens(self.text[i])
        return toks

    def locate(self, quote: str, node: int | None, pool: Iterable[int]) -> tuple[int, float] | None:
        """The node (among `pool`, the named one first) whose text holds `quote`, with the share of the quote found there: 1.0 for a verbatim
        run of tokens, at least FUZZY_QUOTE for a near copy, else None. A quote of fewer than 3 tokens proves nothing and is refused."""
        needle = norm_tokens(quote)
        if len(needle) < 3:
            return None
        order = ([node] if node is not None else []) + [j for j in pool if j != node]
        best: tuple[int, float] | None = None
        for j in order:
            hay = self._tokens(j)
            if find_run(hay, needle) >= 0:
                return j, 1.0
            if len(hay) >= 3:
                share = _coherent_share(hay, needle)
                if share >= FUZZY_QUOTE and (best is None or share > best[1]):
                    best = (j, share)
        return best

    def page_of(self, i: int, quote: str) -> int:
        """Page of the line of node i where `quote` starts; the first page of the node when the quote sits in a table grid or cannot be placed."""
        node = self.nodes[i]
        needle = norm_tokens(quote)[:5]
        stream: list[tuple[str, int]] = []
        for line, page in zip(node.text, node.pages):
            stream += [(t, page) for t in norm_tokens(line)]
        hay = [t for t, _ in stream]
        at = find_run(hay, needle) if len(needle) >= 3 else -1
        return stream[at][1] if at >= 0 else node.page_start
