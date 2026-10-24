#!/usr/bin/env python3
"""Mapping simulation: spec -> graph of regulations -> how much of the gold can be reached, stage by stage. No model calls.

    python eval/simulate_mapping.py                                    # R150, R148, R48, R10 + 6 random ones (seed 20261024)
    python eval/simulate_mapping.py --seed 3 --csv spec/testing/mapping-sim.csv
    python eval/simulate_mapping.py --selection picks.json             # score a selection made elsewhere (an LLM walk, by hand)

What it does (the letters are the sections of the printed report). The gold (cases/dev-rear-lamp/expected.json) is only used to
score; nothing is selected with it. The profile is read from spec.md (functions, parts, materials); electronics in the materials add
an ESA item.
  A. Parse the regulations with regcomp.parse and build the graph: parent, REFERS_TO and CITES_REG edges.
  B. Check that every gold requirement lands on a node with its label and page.
  C. Regulation level: rank a card per regulation (title, section 1, depth-2 table of contents) against the profile with BM25,
     then apply a vehicle-category facet and SUPERSEDES (read from each regulation's own introduction).
  D. Section level: pick subtree roots lexically (heading only, or heading plus text) and compare with the gold-touched roots;
     oracle rows show what each kind of section contributes. Page and regulation level use tools/score_local.py. Also search as a
     safety net, and what a regulation-level error costs.
  E. Requirement level: how much of each gold requirement sits in its anchor node, and an extractive floor (every sentence of the
     selected nodes matched 1:1 with the gold by lexical cosine, a crude stand-in for the platform's judge).
Everything lexical here is a floor: what a selector without a language model reaches. The gap to the oracle is what the model has to close.

A --selection file is a JSON list of {"regulation": "UN R48", "root": "6.10"} (a body section of depth 2, or an annex scope such
as "Annex 6 Part 4"); it is scored exactly like the built-in selectors.
Needs PyMuPDF and the base PDFs: python tools/fetch_regulations.py --role base --out regulations/data
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import sys
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pymupdf

sys.dont_write_bytecode = True  # importing tools/score_local.py must not leave a __pycache__ in the repo
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from regcomp import corpus  # noqa: E402
from regcomp.parse import NUMBER_PREFIX, ParsedDocument, parse_pdf  # noqa: E402
from score_local import _paragraph_key, score as platform_score  # noqa: E402

CASE = ROOT / "cases" / "dev-rear-lamp"
SEED = 20261024  # the date the simulation was first run
REG_THETA = 0.4  # regulation kept when its score is at least this fraction of the best one (fixed before looking at results)
ITEM_TOP, ITEM_THETA = 3, 0.5  # per profile item: its best 3 roots, and only those scoring at least half of the best
ROOT_KIND = ("annex", "annex-appendix", "appendix", "part")


# ------------------------------------------------------------------------------------------------ text, BM25, metrics
STOP = set("""a an and are as at be been being but by can for from has have if in into is it its may no not of on or such than that
the their then there these they this those to under up was were when where which while who with within would shall should must will
any all each other only also one two per used use using same""".split())
GENERIC = set("""regulation regulations vehicle vehicles type approval approved paragraph paragraphs annex part table figure requirement
requirements applicant manufacturer specification specifications""".split())


def stem(word: str) -> str:
    """A small suffix stripper: it only has to equate lamp/lamps, signal/signalling, reflect/reflective/reflector."""
    if len(word) <= 3:
        return word
    for suffix, replacement in (("ations", ""), ("ation", ""), ("ions", ""), ("ion", ""), ("ives", ""), ("ive", ""), ("ors", ""),
                                ("or", ""), ("ings", ""), ("ing", ""), ("ies", "y"), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: len(word) - len(suffix)] + replacement
            break
    return word[:-1] if len(word) > 4 and word[-1] == word[-2] and word[-1] not in "aeiou" else word  # signall -> signal


def tokens(text: str) -> list[str]:
    words = (w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and not w.isdigit() and w not in STOP and w not in GENERIC)
    return [stem(w) for w in words]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.length = [len(d) for d in docs]
        self.avg = sum(self.length) / len(docs) if docs else 1.0
        df = Counter(t for c in self.tf for t in c)
        self.idf = {t: math.log(1 + (len(docs) - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, dl in zip(self.tf, self.length):
            s = 0.0
            for t in set(query):
                if (f := tf.get(t, 0)):
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avg or 1)))
            out.append(s)
        return out


def f2(p: float, r: float) -> float:
    return 0.0 if p + r == 0 else 5 * p * r / (4 * p + r)


def prf(tp: int, n_selected: int, n_gold: int) -> tuple[float, float, float]:
    p, r = (tp / n_selected if n_selected else 0.0), (tp / n_gold if n_gold else 0.0)
    return p, r, f2(p, r)


# ------------------------------------------------------------------------------------------------------ the profile
def read_spec(path: Path) -> dict:
    """spec.md -> product, vehicle category, functions, parts, materials (component, material)."""
    sections: dict[str, list[str]] = defaultdict(list)
    current, text = None, path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
        elif current:
            sections[current].append(line)
    bullets = lambda key: [l.strip()[1:].strip() for l in sections.get(key, []) if l.strip().startswith("- ")]
    materials = []
    for line in sections.get("materials", []):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and not set(cells[0]) <= set("- ") and cells[0].lower() != "component":
            materials.append((cells[0], cells[1]))
    return {"text": text, "category": " ".join(sections.get("vehicle category", [])).strip(), "functions": bullets("function"),
            "parts": bullets("main parts"), "materials": materials}


ELECTRONICS = re.compile(r"\b(LED|PCB|electronic|electrical|sensor|ECU|controller|circuit|battery|motor|software|display)\b", re.I)


def profile_items(spec: dict, infer: bool) -> list[tuple[str, str]]:
    """One query per function and per part. `infer` adds what a reader deduces from the materials: LED modules on a PCB make the
    lamp an electrical/electronic sub-assembly (ESA), which brings electromagnetic compatibility in."""
    items = [("function: " + f, f) for f in spec["functions"]] + [("part: " + p, p) for p in spec["parts"]]
    if infer and any(ELECTRONICS.search(material) for _, material in spec["materials"]):
        items.append(("derived: electronics", "electrical electronic sub-assembly ESA electromagnetic compatibility"))
    return items


# ----------------------------------------------------------------------------------------------------------- the graph
NUM = r"\d+(?:\.\d+)*"
LIST = rf"((?:\s*(?:,|and/or|and|or|to)\s*{NUM}\.?)*)"
REF_OF_ANNEX = re.compile(rf"\bparagraphs?\s+({NUM})\.?{LIST}\s+of\s+(?:Part\s+([A-Z]|\d+)\s+of\s+)?Annex\s+(\d+[A-Za-z]?)")
REF_ANNEX_FIRST = re.compile(rf"\bAnnex\s+(\d+[A-Za-z]?),?\s*(?:Part\s+([A-Z]|\d+),?\s*)?paragraphs?\s+({NUM})\.?{LIST}")
REF_OF_REG = re.compile(rf"\bparagraphs?\s+({NUM})\.?{LIST}\s+of\s+(this|UN)\s+Regulation(?:\s+No\.?\s*(\d+[A-Z]?))?")
REF_PLAIN = re.compile(rf"\bparagraphs?\s+({NUM})\.?(?:\s*\([a-z]+\))*{LIST}")
CITE_REG = re.compile(r"\b(?:UN\s+)?Regulations?\s+(?:Nos?\.?\s*)?([1-9]\d*(?:-?[A-Z])?(?:\s*(?:,|and/or|and|or)\s*(?:Nos?\.?\s*)?[1-9]\d*(?:-?[A-Z])?)*)")
COMBINES = re.compile(r"(?:combines?|incorporates?|replaces?|supersedes?)\s+(?:the\s+)?provisions?\s+of\s+(?:the\s+)?(?:individual\s+)?"
                      r"(?:UN\s+)?Regulations?\s+Nos?\.?\s*((?:\d+[A-Z]?(?:\s*(?:,|and|&)\s*)?)+)", re.I)


@dataclass
class Graph:
    reg: str
    version: str
    doc: ParsedDocument
    parent: list[int]  # parent node, -1 for none
    by_key: dict  # (scope, num) -> node index
    refs: list  # (source node, target node or None, other regulation or None)
    cites: list  # (source node, "UN R48")

    @property
    def nodes(self):
        return self.doc.nodes

    def content(self) -> list[int]:
        return [i for i, n in enumerate(self.nodes) if n.kind in ("para", "table")]


def _numbers(first: str, rest: str) -> list[tuple[int, ...]]:
    return [tuple(int(x) for x in s.split(".")) for s in [first, *re.findall(NUM, rest or "")]]


def build_graph(reg: str, role: str = "base") -> Graph:
    entry = corpus.entry_for(reg)
    doc = parse_pdf(corpus.pdf_path(entry, role), grids=False)
    nodes = doc.nodes
    by_key: dict = {}
    for i, n in enumerate(nodes):
        if n.kind == "para":
            by_key.setdefault((n.scope, n.num), i)
    parent = [n.parent for n in nodes]  # the tree is the parser's (Node.parent), no longer derived here
    graph = Graph(reg, corpus.version_label(entry, role), doc, parent, by_key, [], [])
    for i in graph.content():
        body, claimed = nodes[i].body, []
        for pattern, form in ((REF_OF_ANNEX, "annex"), (REF_ANNEX_FIRST, "annex_first"), (REF_OF_REG, "reg"), (REF_PLAIN, "plain")):
            for m in pattern.finditer(body):
                if any(a <= m.start() < b for a, b in claimed):
                    continue
                claimed.append((m.start(), m.end()))
                scope = nodes[i].scope
                if form == "annex":
                    first, rest, part, annex = m.groups()
                    scope = f"Annex {annex}" + (f" Part {part}" if part else "")
                elif form == "annex_first":
                    annex, part, first, rest = m.groups()
                    scope = f"Annex {annex}" + (f" Part {part}" if part else "")
                elif form == "reg":
                    first, rest, which, number = m.groups()
                    if which == "UN" and number:
                        graph.refs += [(i, None, f"UN R{number}") for _ in _numbers(first, rest)]
                        continue
                    scope = ""
                else:
                    first, rest = m.groups()
                for num in _numbers(first, rest):
                    target = by_key.get((scope, num))
                    if target is None and form == "plain":
                        target = by_key.get(("", num))
                    graph.refs.append((i, target, None))
        for m in CITE_REG.finditer(body):
            graph.cites += [(i, "UN R" + x.replace("-", "")) for x in re.findall(r"\d+(?:-?[A-Z])?", m.group(1))]
    return graph


def root_key(node) -> tuple:
    """A subtree root, as in spec/precision.md: a depth-2 body section, or a whole annex/appendix/part scope."""
    return (node.scope, ()) if node.scope else ("", node.num[:2])


def root_label(key: tuple) -> str:
    return key[0] or ".".join(map(str, key[1]))


def roots_of(graph: Graph) -> OrderedDict:
    roots: OrderedDict = OrderedDict()
    for i in graph.content():
        roots.setdefault(root_key(graph.nodes[i]), []).append(i)
    return roots


def top_heading(graph: Graph, i: int) -> str:
    """The depth-1 body section (number and title) or the annex a node sits in."""
    n = graph.nodes[i]
    if n.scope:
        annex = n.scope.split(" Part")[0].split(" Appendix")[0]
        head = next((m.body for m in graph.nodes if m.kind in ROOT_KIND and m.scope == annex), annex)
        return "Annex: " + re.sub(r"\s+", " ", head)[:56]
    top = graph.by_key.get(("", n.num[:1]))
    return f"{n.num[0]}. " + (NUMBER_PREFIX.sub("", graph.nodes[top].body)[:48] if top is not None else "?")


def head_text(graph: Graph, key: tuple, ids: list[int]) -> str:
    """What a table of contents shows for a root: the scope heading plus the first node, or the root paragraph's own first words."""
    if key[0]:
        heads = [n.body for n in graph.nodes if n.kind in ROOT_KIND and n.scope == key[0]]
        return " ".join(heads) + " " + graph.nodes[ids[0]].body[:120]
    own = next((i for i in ids if graph.nodes[i].num == key[1]), ids[0])
    return NUMBER_PREFIX.sub("", graph.nodes[own].body)[:160]


# ------------------------------------------------------------------------------------------------ regulation cards
def make_card(entry: dict) -> dict:
    path = corpus.pdf_path(entry, "base")
    doc = parse_pdf(path, grids=False)
    scope = " ".join(n.body for n in doc.nodes if n.kind == "para" and not n.scope and n.num[:1] == (1,))[:1500]
    toc = [NUMBER_PREFIX.sub("", n.body)[:100] for n in doc.nodes
           if (n.kind == "para" and not n.scope and len(n.num) <= 2) or n.kind in ROOT_KIND]
    with pymupdf.open(path) as pdf:
        front = re.sub(r"\s+", " ", " ".join(pdf[i].get_text() for i in range(min(3, pdf.page_count))))
    m = COMBINES.search(front)  # "This Regulation combines the provisions of individual UN Regulations Nos. 3, 27, 69, 70 and 104"
    return {"title": entry["title"], "scope": scope, "toc": toc,
            "supersedes": ["UN R" + n for n in re.findall(r"\d+[A-Z]?", m.group(1))] if m else []}


CATEGORY = re.compile(r"categor(?:y|ies)\s+((?:[LMNOT]\d?[A-Za-z]?(?:\s*,\s*|\s+and\s+|\s+or\s+|\s*/\s*)?)+)", re.I)


def vehicle_letters(scope: str) -> set[str]:
    return {t[0].upper() for m in CATEGORY.finditer(scope) for t in re.findall(r"[LMNOT]\d?[A-Za-z]?", m.group(1))}


def card_text(card: dict, fields: tuple) -> str:
    return " . ".join(" . ".join(card[f]) if f == "toc" else card[f] for f in fields)


def rank_regulations(cards: dict, query: str, fields: tuple, spec: dict, universe: list[str]) -> dict:
    """Lexical rank of the cards against `query`, then category facet, then SUPERSEDES; each step as an ordered list of
    (regulation, score). The IDF always comes from every card, so the 10-regulation slice restricts the index-wide ranking."""
    regs = list(cards)
    bm = BM25([tokens(card_text(c, fields)) for c in cards.values()])
    score = dict(zip(regs, bm.scores(tokens(query))))
    letter = re.match(r"\s*([LMNOT])", spec["category"]).group(1)
    superseded_by = {old: new for new, c in cards.items() for old in c["supersedes"] if old in cards}
    steps = {}
    ranked = sorted((r for r in universe if r in score), key=score.get, reverse=True)
    steps["lexical"] = [(r, score[r]) for r in ranked]
    faceted = [r for r in ranked if not (letters := vehicle_letters(cards[r]["scope"])) or letter in letters]
    steps["+ category facet"] = [(r, score[r]) for r in faceted]
    merged: dict[str, float] = {}
    for r in faceted:
        target = superseded_by.get(r, r)
        merged[target] = max(merged.get(target, 0.0), score[r])
    steps["+ supersession"] = sorted(((r, s) for r, s in merged.items() if r in universe), key=lambda x: -x[1])
    return steps


# ------------------------------------------------------------------------------------------------------ the gold
def load_gold() -> dict:
    return json.loads((CASE / "expected.json").read_text(encoding="utf-8"))


def anchor_nodes(gold: dict, graphs: dict) -> dict[str, tuple[str, int]]:
    """gold requirement id -> (regulation, node index): the node with the same label whose page range holds the gold page."""
    found = {}
    for q in gold["requirements"]:
        s = q["source"]
        g = graphs[s["regulation"]]
        found[q["id"]] = next(((s["regulation"], i) for i in g.content() if _paragraph_key(g.nodes[i].label) == _paragraph_key(s["paragraph"])
                               and g.nodes[i].page_start <= s["page"] <= g.nodes[i].page_end), None)
    return found


def categorise(graph: Graph, key: tuple, ids: list[int], part_tokens: list[set[str]]) -> str:
    """F: a short section heading that names a part of the product; M: markings; T: an annex scope; G: any other body section."""
    if key[0]:
        return "T"
    head = head_text(graph, key, ids)
    if re.match(r"(approval )?markings?\b|presence of markings", head, re.I):
        return "M"
    if len(head) <= 110 and "shall" not in head and any(p <= set(tokens(head)) for p in part_tokens):
        return "F"
    return "G"


# -------------------------------------------------------------------------------------------------------- selection
def lexical_roots(graph: Graph, items: list, kind: str) -> set[tuple]:
    """Emulates a per-item walk of the table of contents: for every profile item its best roots by BM25."""
    roots = roots_of(graph)
    keys = list(roots)
    docs = [tokens(head_text(graph, k, roots[k]) + (" " + " ".join(graph.nodes[i].body for i in roots[k]) if kind == "full" else ""))
            for k in keys]
    bm, chosen = BM25(docs), set()
    for _, text in items:
        s = bm.scores(tokens(text))
        if (best := max(s)) > 0:
            chosen |= {keys[i] for i in sorted(range(len(keys)), key=s.__getitem__, reverse=True)[:ITEM_TOP] if s[i] >= ITEM_THETA * best}
    return chosen


def evaluate(selection: set[tuple[str, int]], graphs: dict, gold: dict, anchors: dict, gold_nodes: set, gold_roots: set) -> dict:
    sub = {"requirements": [{"source": {"regulation": r, "version": graphs[r].version, "page": graphs[r].nodes[i].page_start,
                                         "paragraph": graphs[r].nodes[i].label}} for r, i in sorted(selection)]}
    plat = platform_score(sub, gold) if sub["requirements"] else {"regulation_level": {"precision": 0, "recall": 0}, "page_level": {"precision": 0, "recall": 0}}
    cited = len(selection & gold_nodes)
    p, r, f = prf(cited, len(selection), len(gold_nodes))
    roots_sel = {(reg, root_key(graphs[reg].nodes[i])) for reg, i in selection}
    return {"nodes": len(selection), "roots": len(roots_sel), "roots_hit": len(roots_sel & gold_roots), "cited": cited,
            "node_p": p, "node_r": r, "node_f2": f,
            "reqs": sum(1 for v in anchors.values() if v in selection),
            "reg_p": plat["regulation_level"]["precision"], "reg_r": plat["regulation_level"]["recall"],
            "page_p": plat["page_level"]["precision"], "page_r": plat["page_level"]["recall"]}


# ---------------------------------------------------------------------------------------------------------- grounding
WORD = re.compile(r"[a-z]+|\d+(?:[.,]\d+)?")


def bag(text: str) -> set[str]:
    return {stem(w) if w.isalpha() else w for w in WORD.findall(text.lower()) if w not in STOP}


def share(want: set[str], text: str) -> float:
    """Fraction of the words in `want` that `text` contains."""
    return len(want & bag(text)) / len(want) if want else 0.0


def grounding(gold: dict, graphs: dict, anchors: dict) -> list[dict]:
    """Per gold requirement: share of its content words found in its anchor node (own text; plus parent and children), in a random
    node of the same regulation (control), and the BM25 rank of the anchor when the gold text is the query."""
    rng, rows = random.Random(1), []
    index = {}
    for reg, g in graphs.items():
        ids = g.content()
        index[reg] = (ids, BM25([tokens(g.nodes[i].body) for i in ids]), {i: bag(g.nodes[i].body) for i in ids})
    for q in gold["requirements"]:
        reg, i = anchors[q["id"]]
        g, (ids, bm, bags) = graphs[reg], index[reg]
        want = bag(q["text"])
        kids = " ".join(g.nodes[j].body for j in ids if g.parent[j] == i)
        up = g.nodes[g.parent[i]].body if g.parent[i] != -1 else ""
        s = bm.scores(tokens(q["text"]))
        order = sorted(range(len(ids)), key=s.__getitem__, reverse=True)
        rows.append({"id": q["id"], "own": share(want, g.nodes[i].body), "context": share(want, g.nodes[i].body + " " + up + " " + kids),
                     "control": len(want & bags[rng.choice([j for j in ids if j != i])]) / len(want) if want else 0.0,
                     "rank": order.index(ids.index(i)) + 1})
    return rows


def sentences(body: str) -> list[str]:
    """The sentence-like units of one node, as an extractor without a language model would cut them."""
    text = NUMBER_PREFIX.sub("", body, count=1)
    return [p.strip() for p in re.split(r"(?<=[.;:])\s+(?=[A-Z(\d])", text) if len(p.split()) >= 5]


def norm(words: set[str], idf: dict) -> float:
    return math.sqrt(sum(idf[t] ** 2 for t in words)) or 1.0


def extractive_floor(selection: set, graphs: dict, gold: dict, anchors: dict, taus: tuple) -> dict:
    """Requirement level without the platform's judge: every sentence of every selected node is a candidate requirement, matched
    one to one with the gold by TF-IDF cosine over content words and numbers (greedy, best pairs first). A crude stand-in:
    rewriting counts as a miss, paraphrase the judge would accept counts as a miss, and one sentence can serve only one requirement."""
    out = {t: {"units": 0, "matched": 0, "in_anchor": 0, "by_reg": Counter(), "missed": []} for t in taus}
    for reg in graphs:
        units = [(i, u) for r, i in sorted(selection) if r == reg for u in sentences(graphs[reg].nodes[i].body)]
        golds = [q for q in gold["requirements"] if q["source"]["regulation"] == reg]
        if not units:
            continue
        bags = [bag(u) for _, u in units] + [bag(q["text"]) for q in golds]
        df = Counter(t for b in bags for t in b)
        idf = {t: math.log(1 + len(bags) / n) for t, n in df.items()}
        posting = defaultdict(list)
        for k, (_, u) in enumerate(units):
            for t in bags[k]:
                posting[t].append(k)
        pairs = []
        for g, q in enumerate(golds):
            gb = bags[len(units) + g]
            shared = defaultdict(float)
            for t in gb:
                for k in posting.get(t, ()):
                    shared[k] += idf[t] ** 2
            pairs += [(s / (norm(gb, idf) * norm(bags[k], idf)), g, k) for k, s in shared.items()]
        pairs.sort(reverse=True)
        for tau in taus:
            used_g, used_k, assigned = set(), set(), []
            for sim, g, k in pairs:
                if sim < tau:
                    break
                if g not in used_g and k not in used_k:
                    used_g.add(g)
                    used_k.add(k)
                    assigned.append((g, k))
            out[tau]["units"] += len(units)
            out[tau]["matched"] += len(assigned)
            out[tau]["in_anchor"] += sum(1 for g, k in assigned if anchors[golds[g]["id"]] == (reg, units[k][0]))
            out[tau]["by_reg"][reg] += len(assigned)
            out[tau]["missed"] += [q["id"] for g, q in enumerate(golds) if g not in used_g]
    return out


# ---------------------------------------------------------------------------------------------------------- the report
@dataclass
class Run:
    """What the report sections share: the gold, the graphs of the ten regulations, and the gold's anchors in them."""
    gold: dict
    gold_regs: list[str]
    random_regs: list[str]
    spec: dict
    items: list  # the profile items, with the derived electronics one
    index: list[dict]
    graphs: dict
    anchors: dict  # gold id -> (regulation, node index)
    all_roots: dict
    gold_nodes: set
    gold_roots: set
    part_tokens: list

    @property
    def ten(self) -> list[str]:
        return self.gold_regs + self.random_regs

    def nodes_of(self, roots) -> set:
        return {(r, i) for r, k in roots for i in self.all_roots[r][k]}

    def n_gold(self, reg: str) -> int:
        return sum(1 for q in self.gold["requirements"] if q["source"]["regulation"] == reg)


def table(rows: list[list], header: list[str]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    print("  " + "  ".join(h.ljust(w) if k == 0 else h.rjust(w) for k, (h, w) in enumerate(zip(header, widths))))
    for row in rows:
        print("  " + "  ".join(str(x).ljust(w) if k == 0 else str(x).rjust(w) for k, (x, w) in enumerate(zip(row, widths))))


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def report_graph(run: Run) -> None:
    print("A. GRAPH (prototype parser, base versions)")
    in_index = {e["regulation"] for e in run.index}
    rows, total = [], Counter()
    for reg, g in run.graphs.items():
        kinds = Counter(n.kind for n in g.nodes)
        local = [d for _, d, other in g.refs if other is None]
        cited = [t for _, t in g.cites if t in in_index and t != reg]
        orphans = sum(1 for i in g.content() if g.nodes[i].num and len(g.nodes[i].num) > 1 and g.parent[i] == -1)
        scopes = len(g.nodes) - kinds["para"] - kinds["table"]
        rows.append([reg, g.version, g.doc.pages, len(g.nodes), kinds["para"], kinds["table"], scopes, orphans, len(g.refs),
                     pct(sum(d is not None for d in local) / max(1, len(local))), len(g.refs) - len(local), len(set(cited)),
                     ",".join(sorted({t[3:] for t in cited if t in run.graphs})) or "-"])
        total.update(nodes=len(g.nodes), parent=sum(p != -1 for p in g.parent), refs=len(g.refs), local=len(local),
                     resolved=sum(d is not None for d in local), cites=len(cited))
    table(rows, ["regulation", "ver", "pages", "nodes", "para", "table", "scope", "orphan", "REFERS_TO", "resolved", "to other reg", "CITES_REG regs", "cites (of the 10)"])
    print(f"  totals: {total['nodes']} nodes, {total['parent']} parent edges, {total['refs']} REFERS_TO ({total['resolved']} of {total['local']} targets inside the regulation "
          f"resolved = {pct(total['resolved'] / total['local'])}), {total['cites']} CITES_REG edges into regulations of the index")
    print("  CITES_REG targets in the index, from the four gold regulations:")
    for reg in run.gold_regs:
        c = Counter(t for _, t in run.graphs[reg].cites if t in in_index and t != reg)
        print(f"    {reg}: " + ", ".join(f"{k[3:]}x{v}" for k, v in c.most_common()))


def report_anchors(run: Run) -> None:
    missing = [k for k, v in run.anchors.items() if v is None]
    print(f"\nB. ANCHORS: {len(run.anchors) - len(missing)}/{len(run.anchors)} gold requirements land on a node with the same label and page range"
          + (f"; missing {missing}" if missing else ""))
    print(f"   {len(run.anchors)} requirements -> {len(run.gold_nodes)} nodes -> {len(run.gold_roots)} roots in {len(run.gold_regs)} regulations")
    for reg in run.gold_regs:
        print(f"   {reg}: {run.n_gold(reg)} requirements, {len({i for r, i in run.gold_nodes if r == reg})} nodes, "
              f"{len({k for r, k in run.gold_roots if r == reg})} roots of {len(run.all_roots[reg])}, {len(run.graphs[reg].content())} content nodes")


def report_regulations(run: Run) -> list[str]:
    """Part C. Returns the regulations the pre-set threshold keeps among the ten, for the end-to-end rows of part D."""
    print("\nC. REGULATION LEVEL (one card per regulation: title, section 1, depth-2 table of contents; BM25 with the IDF of all 56 cards)")
    cards = {e["regulation"]: make_card(e) for e in run.index if corpus.pdf_path(e, "base")}
    size = {r: (len(c["title"]) + len(c["scope"]) + sum(len(t) + 1 for t in c["toc"])) // 4 for r, c in cards.items()}
    print(f"   card size (chars/4): R150 {size['UN R150']}, R148 {size['UN R148']}, R48 {size['UN R48']}, R10 {size['UN R10']}; over {len(size)} regulations: min {min(size.values())}, median "
          f"{statistics.median(size.values()):.0f}, max {max(size.values())}; all cards together about {sum(size.values()) // 1000}K tokens")
    print("   SUPERSEDES read from the introductions: " + "; ".join(f"{r} -> {c['supersedes']}" for r, c in cards.items() if c["supersedes"]))
    gold_set, spec = set(run.gold_regs), run.spec
    plain, derived = (" ".join(text for _, text in profile_items(spec, infer)) for infer in (False, True))
    toc = ("title", "scope", "toc")
    ladder = [("whole spec.md as the query, title+scope cards (as eval/baseline.py)", spec["text"], ("title", "scope"), "lexical"),
              ("profile items, title", plain, ("title",), "lexical"),
              ("profile items, title+scope", plain, ("title", "scope"), "lexical"),
              ("profile items, title+scope+toc", plain, toc, "lexical"),
              ("+ derived electronics item", derived, toc, "lexical"),
              ("+ vehicle-category facet", derived, toc, "+ category facet"),
              ("+ SUPERSEDES from the introductions", derived, toc, "+ supersession")]
    kept_ten: list[str] = []
    for name, universe in (("all 56 regulations", list(cards)), ("the 10 regulations", run.ten)):
        rows = []
        for label, query, fields, step in ladder:
            listing = rank_regulations(cards, query, fields, spec, universe)[step]
            order = [r for r, _ in listing]
            kept = [r for r, s in listing if s >= REG_THETA * listing[0][1]]
            p, rc, f = prf(len(set(kept) & gold_set), len(kept), len(gold_set))
            rows.append([label] + [order.index(r) + 1 if r in order else "-" for r in ("UN R48", "UN R148", "UN R150", "UN R10")]
                        + [len(kept), f"{p:.2f}", f"{rc:.2f}", f"{f:.2f}"])
        print(f"\n   gold regulation ranks among {name}, and the set kept at {REG_THETA} x the best score")
        table(rows, ["card + query", "R48", "R148", "R150", "R10", "kept", "P", "R", "F2"])
        print("   final scores: " + ", ".join(f"{r[3:]}={s:.1f}" for r, s in listing[:9]))
        if universe is not run.ten:
            steps = rank_regulations(cards, derived, toc, spec, universe)
            kept_by_facet = {r for r, _ in steps["+ category facet"]}
            print("   lexical top 12 before the facet: " + ", ".join(f"{r[3:]}={s:.1f}" for r, s in steps["lexical"][:12])
                  + f"\n   the category facet (letter {spec['category'][0]}) drops: {[r[3:] for r, _ in steps['lexical'] if r not in kept_by_facet]}")
        for theta in (0.3, 0.4, 0.5, 0.6):
            kept = [r for r, s in listing if s >= theta * listing[0][1]]
            p, rc, f = prf(len(set(kept) & gold_set), len(kept), len(gold_set))
            print(f"   threshold {theta} x best: {len(kept)} regulations, P={p:.2f} R={rc:.2f} F2={f:.2f}  {[k[3:] for k in kept]}")
        if universe == run.ten:
            kept_ten = [r for r, s in listing if s >= REG_THETA * listing[0][1]]

    print("\n   R10 rank among the 56 under different wordings of the derived item (cards title+scope+toc; before / after facet and SUPERSEDES)")
    rows = []
    for label, extra in (("none", ""), ("'electromagnetic compatibility'", "electromagnetic compatibility"),
                         ("'electrical electronic sub-assembly ESA'", "electrical electronic sub-assembly ESA"),
                         ("naive, from the materials row: 'LED module printed circuit board electronics'", "LED module printed circuit board electronics"),
                         ("both regulation concepts (the item used above)", "electrical electronic sub-assembly ESA electromagnetic compatibility")):
        steps = rank_regulations(cards, plain + " " + extra, toc, spec, list(cards))
        rows.append([label] + [[r for r, _ in steps[s]].index("UN R10") + 1 for s in ("lexical", "+ supersession")])
    table(rows, ["derived item", "lexical", "after facet + SUPERSEDES"])

    # which regulations does CITES_REG reach from the R48 sections?
    r48 = run.graphs["UN R48"]
    in_index = {e["regulation"] for e in run.index}
    reached = lambda roots: Counter(t for i, t in r48.cites if i in {j for _, j in run.nodes_of({("UN R48", k) for k in roots})} and t in in_index and t != "UN R48")
    walked = lexical_roots(r48, run.items, "head")
    function_roots = {k for r, k in run.gold_roots if r == "UN R48" and categorise(r48, k, run.all_roots[r][k], run.part_tokens) == "F"}
    print(f"\n   CITES_REG from R48: the whole regulation reaches {len(reached(run.all_roots['UN R48']))} regulations; the {len(walked)} roots a heading walk picks reach "
          f"{len(reached(walked))}: {dict(reached(walked))}")
    print(f"   from the {len(function_roots)} function-named R48 sections {sorted(root_label(k) for k in function_roots)}: {dict(reached(function_roots))}")
    print("   R10 is cited by: " + ", ".join(f"{r}x{sum(1 for _, t in g.cites if t == 'UN R10')}" for r, g in run.graphs.items() if r != "UN R10" and any(t == "UN R10" for _, t in g.cites))
          + "; nodes that mention electromagnetic compatibility in the three lighting regulations: "
          + ", ".join(f"{r} {[g.nodes[i].label for i in g.content() if re.search('electromagnetic compatibility', g.nodes[i].body, re.I)]}"
                      for r, g in run.graphs.items() if r in ("UN R150", "UN R148", "UN R48")))
    return kept_ten


def report_sections(run: Run, kept_ten: list[str], selection_path: str | None) -> tuple[OrderedDict, dict]:
    """Part D. Returns the selectors (name -> set of (regulation, node)) and the category of every gold-touched root."""
    g, anchors, gold_nodes, gold_roots = run.graphs, run.anchors, run.gold_nodes, run.gold_roots
    print("\nD. SECTION / NODE / PAGE LEVEL (regulation set: the four gold regulations, i.e. assuming the regulation step was right)")
    cat_of = {(r, k): categorise(g[r], k, ids, run.part_tokens) for r in run.gold_regs for k, ids in run.all_roots[r].items()}
    by_cat = defaultdict(set)
    for key in gold_roots:
        by_cat[cat_of[key]].add(key)
    reqs_by_cat = Counter(cat_of[(r, root_key(g[r].nodes[i]))] for r, i in anchors.values())
    print("   gold-touched roots by category (F function-named, M markings, G other body sections, T annex scopes):")
    for c in "FMGT":
        inside = run.nodes_of(by_cat[c])
        print(f"     {c}: {len(by_cat[c]):>2} roots, {reqs_by_cat[c]:>3} requirements ({pct(reqs_by_cat[c] / len(anchors))}); "
              f"{len(inside & gold_nodes)} of {len(inside)} nodes cited, match rate {pct(len(inside & gold_nodes) / len(inside))}   "
              + ", ".join(sorted(f"{r[3:]} {root_label(k)}" for r, k in by_cat[c])))
    by_top = defaultdict(lambda: [set(), 0])
    for r, i in anchors.values():
        row = by_top[(r, top_heading(g[r], i))]
        row[0].add(i)
        row[1] += 1
    print("   gold requirements by top-level section or annex (nodes, requirements):")
    for (r, head), (nodes, reqs) in sorted(by_top.items(), key=lambda kv: (run.gold_regs.index(kv[0][0]), -kv[1][1])):
        print(f"     {r:<8}{head:<66}{len(nodes):>3} {reqs:>3}")
    lex = {kind: {(r, k) for r in run.gold_regs for k in lexical_roots(g[r], run.items, kind)} for kind in ("head", "full")}
    for kind, picked in lex.items():
        per_reg = [f"{r[3:]} {len({k for rr, k in picked if rr == r} & {k for rr, k in gold_roots if rr == r})}/{len({k for rr, k in gold_roots if rr == r})}" for r in run.gold_regs]
        print(f"   lexical walk ({kind}): gold roots found per regulation " + ", ".join(per_reg)
              + f"; function-named {len(picked & by_cat['F'])}/{len(by_cat['F'])}, markings {len(picked & by_cat['M'])}/{len(by_cat['M'])}, "
              f"other body {len(picked & by_cat['G'])}/{len(by_cat['G'])}, annex {len(picked & by_cat['T'])}/{len(by_cat['T'])}")
    print("   R48 roots the heading walk picks: " + ", ".join(f"{root_label(k)}{'*' if ('UN R48', k) in gold_roots else ''}"
                                                              for r, k in sorted(lex["head"], key=str) if r == "UN R48") + "   (* = holds a gold node)")
    selectors = OrderedDict([
        ("every node of the 4 regulations", {(r, i) for r in run.gold_regs for i in g[r].content()}),
        ("lexical walk, headings only", run.nodes_of(lex["head"])),
        ("lexical walk, headings + text", run.nodes_of(lex["full"])),
        ("oracle F only", run.nodes_of(by_cat["F"])),
        ("oracle F + M", run.nodes_of(by_cat["F"] | by_cat["M"])),
        ("oracle F + M + G (no annexes)", run.nodes_of(by_cat["F"] | by_cat["M"] | by_cat["G"])),
        ("oracle: every gold-touched root", run.nodes_of(gold_roots)),
    ])
    if selection_path:
        wanted = {(p["regulation"], p["root"]) for p in json.loads(Path(selection_path).read_text(encoding="utf-8"))}
        selectors["--selection " + Path(selection_path).name] = run.nodes_of({(r, k) for r in run.gold_regs for k in run.all_roots[r] if (r, root_label(k)) in wanted})
    # the regulation step of part C in front of the same selectors (regulations kept among the ten, right or wrong)
    selectors["end-to-end: regulation step + lexical walk (headings + text)"] = {(r, i) for r in kept_ten for k in lexical_roots(g[r], run.items, "full") for i in run.all_roots[r][k]}
    selectors["end-to-end: regulation step + oracle roots"] = {x for x in run.nodes_of(gold_roots) if x[0] in kept_ten}
    results = {name: evaluate(sel, g, run.gold, anchors, gold_nodes, gold_roots) for name, sel in selectors.items()}
    table([[name, e["roots"], f"{e['roots_hit']}/{len(gold_roots)}", e["nodes"], f"{e['cited']}/{len(gold_nodes)}", pct(e["node_p"]), pct(e["node_r"]), f"{e['node_f2']:.2f}",
            f"{e['reqs']}/{len(anchors)}", f"{pct(e['reg_p'])}/{pct(e['reg_r'])}", f"{pct(e['page_p'])}/{pct(e['page_r'])}"] for name, e in results.items()],
          ["selector", "roots", "gold roots", "nodes", "cited nodes", "node P", "node R", "F2", "reqs reachable", "reg P/R", "page P/R"])
    print(f"   (reg and page P/R: tools/score_local.py, one entry per selected node; the end-to-end rows keep {[r[3:] for r in kept_ten]} from the regulation step)")

    print("\n   search as a safety net (BM25 on each node's own text, per profile item top-N, union):")
    node_ids = [(r, i) for r in run.gold_regs for i in g[r].content()]
    bm = BM25([tokens(g[r].nodes[i].body) for r, i in node_ids])
    per_item = [bm.scores(tokens(text)) for _, text in run.items]
    rows = []
    for n in (5, 10, 20, 40):
        hits = {node_ids[j] for s in per_item for j in sorted(range(len(s)), key=s.__getitem__, reverse=True)[:n]}
        rows.append([f"top {n} per item", len(hits), f"{len(hits & gold_nodes)}/{len(gold_nodes)}",
                     f"{len({(r, root_key(g[r].nodes[i])) for r, i in hits} & gold_roots)}/{len(gold_roots)}"])
    table(rows, ["search", "nodes", "gold nodes", "gold roots touched"])
    return selectors, cat_of


def report_costs(run: Run, selectors: OrderedDict) -> None:
    """What a regulation-level error costs, on top of the oracle roots."""
    base = selectors["oracle: every gold-touched root"]
    print("\n   cost of a regulation-level error (oracle roots as the base; for a wrong regulation the lexical walk 'headings + text' decides what it drags in).")
    print("   dF2 uses node recall; dF2(req) uses the share of gold requirements reachable, which weighs R10's 32 requirements on 15 nodes properly:")

    def cost(sel: set) -> tuple:
        p, rc, f = prf(len(sel & run.gold_nodes), len(sel), len(run.gold_nodes))
        return p, rc, f, f2(p, sum(1 for v in run.anchors.values() if v in sel) / len(run.anchors))

    b = cost(base)
    rows = [["base: oracle roots of the 4", len(base), pct(b[0]), pct(b[1]), f"{b[2]:.3f}", "-", "-"]]
    for victim in run.gold_regs:
        sel = {x for x in base if x[0] != victim}
        c = cost(sel)
        rows.append([f"drop {victim}", len(sel), pct(c[0]), pct(c[1]), f"{c[2]:.3f}", f"{c[2] - b[2]:+.3f}", f"{c[3] - b[3]:+.3f}"])
    for wrong in run.random_regs:
        gw = run.graphs[wrong]
        walk = {(wrong, i) for k in lexical_roots(gw, run.items, "full") for i in run.all_roots[wrong][k]}
        for label, add in ((f"add {wrong}, walk picks {len(walk)} nodes", walk), (f"add {wrong}, all {len(gw.content())} nodes", {(wrong, i) for i in gw.content()})):
            c = cost(base | add)
            rows.append([label, len(base | add), pct(c[0]), pct(c[1]), f"{c[2]:.3f}", f"{c[2] - b[2]:+.3f}", f"{c[3] - b[3]:+.3f}"])
    table(rows, ["scenario", "nodes", "node P", "node R", "node F2", "dF2", "dF2(req)"])


def report_requirements(run: Run, selectors: OrderedDict) -> list[dict]:
    """Part E. Returns the grounding row of every gold requirement."""
    print("\nE. REQUIREMENT LEVEL CEILING (lexical: content words of the gold text found in its anchor node)")
    ground = grounding(run.gold, run.graphs, run.anchors)
    for label, key in (("own text of the anchor", "own"), ("anchor + parent + children", "context"), ("control: a random node of the same regulation", "control")):
        v = [x[key] for x in ground]
        print(f"   {label:<46} median {statistics.median(v):.2f}   >=0.8: {sum(x >= 0.8 for x in v):>3}   0.5-0.8: {sum(0.5 <= x < 0.8 for x in v):>3}   <0.5: {sum(x < 0.5 for x in v):>3}")
    ranks = [x["rank"] for x in ground]
    print(f"   BM25 with the gold text as the query ranks its anchor first {sum(r == 1 for r in ranks)}/{len(ranks)}, within 3: {sum(r <= 3 for r in ranks)}, within 10: {sum(r <= 10 for r in ranks)}")
    print(f"   anchor's own text holds < 80% of the gold words: {[(x['id'], round(x['own'], 2)) for x in ground if x['own'] < 0.8]}")
    print("\n   extractive floor: every sentence of the selected nodes is a candidate requirement, matched 1:1 with the gold by lexical cosine (a crude stand-in for the judge)")
    rows = []
    for name in ("anchor nodes only (121)", "oracle: every gold-touched root", "lexical walk, headings + text", "every node of the 4 regulations"):
        selection = run.gold_nodes if name.startswith("anchor") else selectors[name]
        for tau, x in extractive_floor(selection, run.graphs, run.gold, run.anchors, (0.5, 0.6, 0.7)).items():
            p, rc, f = prf(x["matched"], x["units"], len(run.anchors))
            rows.append([name, tau, x["units"], x["matched"], x["in_anchor"], pct(p), pct(rc), f"{f:.2f}"])
    table(rows, ["selection", "cosine >=", "candidate sentences", "matched", "of them from the anchor node", "P", "R", "F2"])
    floor = extractive_floor(run.gold_nodes, run.graphs, run.gold, run.anchors, (0.6,))[0.6]
    print("   anchor nodes only, cosine >= 0.6, matched by regulation: " + ", ".join(f"{r[3:]} {floor['by_reg'][r]}/{run.n_gold(r)}" for r in run.gold_regs)
          + f"; missed: {floor['missed']}")
    per_node = Counter(run.anchors.values())
    print("   requirements per cited node: " + ", ".join(
        f"{r[3:]} {run.n_gold(r) / len([x for x in per_node if x[0] == r]):.2f}" for r in run.gold_regs))
    return ground


def write_csv(path: str, run: Run, ground: list[dict], selectors: OrderedDict, cat_of: dict) -> None:
    by_id = {x["id"]: x for x in ground}
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["id", "regulation", "paragraph", "page", "node_label", "category", "own_containment", "context_containment", "control_containment", "bm25_rank"]
                   + ["in:" + name for name in selectors])
        for q in run.gold["requirements"]:
            reg, i = run.anchors[q["id"]]
            x, key = by_id[q["id"]], (reg, root_key(run.graphs[reg].nodes[i]))
            w.writerow([q["id"], reg, q["source"]["paragraph"], q["source"]["page"], run.graphs[reg].nodes[i].label, cat_of[key],
                        f"{x['own']:.2f}", f"{x['context']:.2f}", f"{x['control']:.2f}", x["rank"]] + [int((reg, i) in sel) for sel in selectors.values()])
    print(f"\nwrote {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Simulate mapping the rear-lamp spec onto a graph of regulations and score it against the gold.")
    ap.add_argument("--seed", type=int, default=SEED, help="seed for the 6 random regulations")
    ap.add_argument("--csv", help="write one row per gold requirement to this file")
    ap.add_argument("--selection", help="JSON list of {regulation, root} to score as one more selector")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    gold = load_gold()
    counts = Counter(q["source"]["regulation"] for q in gold["requirements"])
    gold_regs = [r for r, _ in counts.most_common()]
    index = corpus.load_index()
    pool = [e["regulation"] for e in index if e["regulation"] not in gold_regs and corpus.pdf_path(e, "base")]
    random_regs = random.Random(args.seed).sample(pool, 6)
    spec = read_spec(CASE / "spec.md")
    print(f"gold: {len(gold['requirements'])} requirements from {gold_regs}\nrandom 6 (seed {args.seed}): {random_regs}\n")

    graphs = {r: build_graph(r) for r in gold_regs + random_regs}
    anchors = anchor_nodes(gold, graphs)
    gold_nodes = set(anchors.values())
    all_roots = {r: roots_of(g) for r, g in graphs.items()}
    run = Run(gold, gold_regs, random_regs, spec, profile_items(spec, True), index, graphs, anchors, all_roots, gold_nodes,
              {(r, root_key(graphs[r].nodes[i])) for r, i in gold_nodes}, [set(tokens(p)) for p in spec["parts"]])
    report_graph(run)
    report_anchors(run)
    kept_ten = report_regulations(run)
    selectors, cat_of = report_sections(run, kept_ten, args.selection)
    report_costs(run, selectors)
    ground = report_requirements(run, selectors)
    if args.csv:
        write_csv(args.csv, run, ground, selectors, cat_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
