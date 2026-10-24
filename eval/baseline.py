#!/usr/bin/env python3
"""Lexical baseline for the main goal: spec.md -> requirements, with no model calls. A floor to measure the funnel against.

    python eval/baseline.py cases/dev-rear-lamp/spec.md --out out.json
    python eval/baseline.py spec/testing/cases/<case>/spec.md --strategy nodes --size 25 --regulations "UN R43"

It stands in for the real pipeline (proposal A4, steps 2-4) with BM25 where the real one uses a model:
  1. regulations: BM25 of one card per regulation (title + its scope section) against the whole spec; keep those that score at
     least half of the best, three at most
  2. nodes: BM25 of every node of a chosen regulation against each facet of the spec (product type, each function, each main
     part); a node's score is its best facet score relative to that facet's best. With the graph, a node is matched together
     with the titles of its ancestors and of its annex or part (the breadcrumb); with --flat, on its own text only
  3. emit: strategy "nodes" gives the N best nodes, strategy "sections" every node of the K best sections (a depth-2 body
     section, or an annex/part scope, scored by its best node)
Defaults, fixed before any case was run: relative 0.5, at most 3 regulations, N = 25, K = 3. Heading-only nodes are never
emitted (spec/precision.md 4.1). The `text` of a requirement is the node's own text, not an atomic obligation, so the baseline
can only be judged on what it cites. Parses are cached in regulations/data/_cache (ignored by git).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from regcomp import corpus  # noqa: E402
from regcomp.parse import NUMBER_PREFIX, Node, ParsedDocument, parse_pdf  # noqa: E402

RELATIVE, MAX_REGULATIONS, NODES, SECTIONS = 0.5, 3, 25, 3
SCOPE_KINDS = ("annex", "annex-appendix", "appendix", "part")
STOP = frozenset(
    "a an and are as at be been by for from has have in into is it its of on or such than that the their these this those to under "
    "was were which with within shall may should must not no any all each other when where while also can will one two per".split())
DEFINITION_TITLE = re.compile(r"^(definitions?|scope|purpose)\b", re.I)
VERB = re.compile(r"\b(shall|must|may|should|is|are|be|been|has|have|can|will|not|means|apply|applies|include|includes|contain|"
                  r"contains|comply|complies)\b", re.I)
_PARSER_SOURCE = Path(sys.modules[parse_pdf.__module__].__file__).read_bytes()


# ---------------------------------------------------------------------------------------------------------- text and BM25
def stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("sses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> list[str]:
    return [stem(t) for t in re.findall(r"[a-z][a-z0-9]*", text.lower()) if len(t) >= 3 and t not in STOP]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.length = [len(d) for d in docs]
        self.avg = (sum(self.length) / len(docs)) if docs else 1.0
        df = Counter(t for tf in self.tf for t in tf)
        self.idf = {t: math.log(1 + (len(docs) - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = [0.0] * len(self.tf)
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(term)
                if f:
                    out[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.length[i] / self.avg))
        return out


# ---------------------------------------------------------------------------------------------------------- the spec
@dataclass
class Spec:
    text: str  # the whole file: the query for choosing regulations
    facets: list[str]  # the product type, each function, each main part: the queries for choosing nodes
    product: str = ""  # the product type line
    functions: list[str] = field(default_factory=list)


def read_spec(path: str | Path) -> Spec:
    text = Path(path).read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line.strip())
    product = " ".join(line for line in sections.get("product type", []) if line)
    functions = [line[2:].strip() for line in sections.get("function", []) if line.startswith("- ")]
    parts = [line[2:].strip() for line in sections.get("main parts", []) if line.startswith("- ")]
    return Spec(text, [f for f in [product, *functions, *parts] if f], product, functions)


# ---------------------------------------------------------------------------------------------------------- parsed regulations
def parsed(regulation: str, role: str = "base") -> ParsedDocument:
    """The parse of a regulation, cached under regulations/data/_cache and keyed by the parser's own source."""
    pdf = corpus.pdf_path(corpus.entry_for(regulation), role)
    if pdf is None:
        raise SystemExit(f"error: the {role} PDF of {regulation} is not in regulations/data; run tools/fetch_regulations.py")
    cache = corpus.DATA / "_cache" / f"{corpus.slug(regulation)}_{role}_{hashlib.sha1(_PARSER_SOURCE).hexdigest()[:8]}.pkl"
    if cache.is_file():
        return pickle.loads(cache.read_bytes())
    doc = parse_pdf(pdf, grids=False)
    cache.parent.mkdir(exist_ok=True)
    cache.write_bytes(pickle.dumps(doc))
    return doc


def heading_only(node: Node) -> bool:
    """spec/precision.md 4.1: under 60 characters, no verb, no digit. It is structure, never a candidate."""
    body = NUMBER_PREFIX.sub("", node.body)
    return len(body) < 60 and not re.search(r"\d", body) and not VERB.search(body)


def section_of(node: Node) -> str:
    """A depth-2 body section ('6.4') or an annex/part scope ('Annex 4 Part 1'), as in spec/precision.md."""
    return node.scope or ".".join(map(str, node.num[:2]))


def short_title(node: Node, width: int = 80) -> str:
    return node.title(width)


# ---------------------------------------------------------------------------------------------------------- stage 1: regulations
_CARDS: tuple[list[str], BM25] | None = None


def card_text(entry: dict, doc: ParsedDocument) -> str:
    scope = [n for n in doc.nodes if n.kind == "para" and not n.scope and n.num[:1] == (1,)]
    body = " ".join(n.body for n in scope) or " ".join(n.body for n in doc.nodes if n.kind == "para")
    return entry["title"] + ". " + body[:1500]


def rank_regulations(spec: Spec) -> list[tuple[str, float]]:
    """Every regulation with the BM25 score of its card against the whole spec, best first."""
    global _CARDS
    if _CARDS is None:
        entries = [e for e in corpus.load_index() if corpus.pdf_path(e, "base") is not None]
        _CARDS = ([e["regulation"] for e in entries], BM25([tokens(card_text(e, parsed(e["regulation"]))) for e in entries]))
    names, index = _CARDS
    return sorted(zip(names, index.scores(tokens(spec.text))), key=lambda item: -item[1])


def choose_regulations(ranking: list[tuple[str, float]], relative: float = RELATIVE, most: int = MAX_REGULATIONS) -> list[str]:
    top = ranking[0][1]
    return [name for name, score in ranking[:most] if score >= relative * top]


# ---------------------------------------------------------------------------------------------------------- stages 2 and 3: nodes
class RegulationIndex:
    def __init__(self, regulation: str, graph: bool = True, drop_definitions: bool = False) -> None:
        doc = parsed(regulation)
        self.regulation = regulation
        self.version = corpus.version_label(corpus.entry_for(regulation), "base")
        titles = {(n.scope, n.num): short_title(n) for n in doc.nodes if n.kind == "para"}

        def defines(node: Node) -> bool:
            return any(DEFINITION_TITLE.match(titles.get((node.scope, node.num[:k]), "")) for k in range(1, len(node.num) + 1))

        self.nodes = [n for n in doc.nodes if n.kind in ("para", "table") and not heading_only(n) and not (drop_definitions and defines(n))]
        docs = []
        for n in self.nodes:
            crumbs: list[str] = []
            if graph:  # the titles of the node's ancestors, scope headings first: the tree is the parser's (Node.parent)
                up = n.parent
                if n.kind == "table" and up >= 0 and doc.nodes[up].kind == "para":
                    up = doc.nodes[up].parent  # a table is matched with the crumbs of the paragraph that names it, not with its text
                while up >= 0:
                    ancestor = doc.nodes[up]
                    crumbs.insert(0, ancestor.title(90) if ancestor.kind in SCOPE_KINDS else short_title(ancestor))
                    up = ancestor.parent
            docs.append(tokens(" ".join(crumbs + [n.body])))
        self.bm25 = BM25(docs)

    def score(self, facets: list[str]) -> list[float]:
        best = [0.0] * len(self.nodes)
        for facet in facets:
            scores = self.bm25.scores(tokens(facet))
            top = max(scores, default=0.0) or 1.0
            best = [max(b, s / top) for b, s in zip(best, scores)]
        return best

    def top_nodes(self, scores: list[float], n: int) -> list[Node]:
        order = sorted(range(len(self.nodes)), key=lambda i: (-scores[i], i))[:n]
        return [self.nodes[i] for i in sorted(order, key=lambda i: (-scores[i], i))]

    def ranked_sections(self, scores: list[float]) -> list[str]:
        best: dict[str, float] = {}
        for node, score in zip(self.nodes, scores):
            best[section_of(node)] = max(best.get(section_of(node), 0.0), score)
        return sorted(best, key=lambda s: -best[s])

    def sections(self, scores: list[float], k: int) -> list[Node]:
        chosen = set(self.ranked_sections(scores)[:k])
        return [n for n in self.nodes if section_of(n) in chosen]


_INDEXES: dict[tuple[str, bool, bool], RegulationIndex] = {}


def index_of(regulation: str, graph: bool = True, drop_definitions: bool = False) -> RegulationIndex:
    key = (regulation, graph, drop_definitions)
    if key not in _INDEXES:
        _INDEXES[key] = RegulationIndex(regulation, graph, drop_definitions)
    return _INDEXES[key]


def emit(regulations: list[str], spec: Spec, strategy: str, size: int, graph: bool = True,
         drop_definitions: bool = False) -> list[tuple[str, Node]]:
    """(regulation, node) pairs: the `size` best nodes, or every node of the `size` best sections, per chosen regulation."""
    picks: list[tuple[str, Node]] = []
    for regulation in regulations:
        index = index_of(regulation, graph, drop_definitions)
        scores = index.score(spec.facets)
        nodes = index.top_nodes(scores, size) if strategy == "nodes" else index.sections(scores, size)
        picks += [(regulation, n) for n in nodes]
    return picks


def to_submission(case_id: str, picks: list[tuple[str, Node]]) -> dict:
    requirements = []
    for number, (regulation, node) in enumerate(picks, start=1):
        text = NUMBER_PREFIX.sub("", node.body)[:400].strip() or node.label
        version = corpus.version_label(corpus.entry_for(regulation), "base")
        requirements.append({"id": f"B-{number:04d}", "text": text,
                             "source": {"regulation": regulation, "version": version, "page": node.page_start, "paragraph": node.label}})
    return {"team_id": "baseline", "case_id": case_id, "requirements": requirements}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lexical baseline: spec.md -> requirements (no model calls).")
    parser.add_argument("spec", help="path of the spec.md")
    parser.add_argument("--out", help="write the submission JSON here (default: print a summary)")
    parser.add_argument("--strategy", choices=["nodes", "sections"], default="nodes")
    parser.add_argument("--size", type=int, help=f"nodes per regulation, or sections per regulation (default {NODES} / {SECTIONS})")
    parser.add_argument("--regulations", nargs="+", help="use these regulations instead of choosing them")
    parser.add_argument("--flat", action="store_true", help="match a node on its own text only, without the breadcrumb")
    args = parser.parse_args(argv)

    spec = read_spec(args.spec)
    ranking = rank_regulations(spec)
    regulations = args.regulations or choose_regulations(ranking)
    print("regulations ranked:", ", ".join(f"{n} {s:.1f}" for n, s in ranking[:6]), "| chosen:", regulations)
    size = args.size or (NODES if args.strategy == "nodes" else SECTIONS)
    picks = emit(regulations, spec, args.strategy, size, graph=not args.flat)
    submission = to_submission(Path(args.spec).parent.name, picks)
    if args.out:
        Path(args.out).write_text(json.dumps(submission, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(picks)} requirements" + (f" written to {args.out}" if args.out else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
