"""The regulations of regulations/index.json as cards, for choosing which of them apply to a product (spec/proposal.md A4.2).

A card holds what a reader needs to decide whether a regulation is about the product: its title, the vehicle categories its first section
names, the scope text, a table of contents (the sections two levels down: for an installation regulation this is where "Rear position lamp"
shows up), and what it supersedes. Supersession is read from the regulation's own introduction ("combines the provisions of individual UN
Regulations Nos. ..."), not typed in. Cards are parsed once per version of the parser and cached as JSON.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf

from regcomp import corpus

from .config import ROOT
from .store import _parser, parser_module, parser_name

SCOPE_CHARS = 900
TOC_CHARS = 2600
SCOPE_KINDS = ("annex", "annex-appendix", "appendix", "part")
COMBINES = re.compile(r"(?:combines?|incorporates?|replaces?|supersedes?)\s+(?:the\s+)?provisions?\s+of\s+(?:the\s+)?(?:individual\s+)?"
                      r"(?:UN\s+)?Regulations?\s+Nos?\.?\s*((?:\d+[A-Z]?(?:\s*(?:,|and|&)\s*)?)+)", re.I)
CATEGORY = re.compile(r"(?i:categor(?:y|ies))\s+((?:[LMNOT]\d?[A-Za-z]?(?:\s*,\s*|\s+and\s+|\s+or\s+|\s*/\s*)?)+)")


def vehicle_letters(text: str) -> list[str]:
    """The vehicle category letters a scope text names ('categories M1, N1 and O' -> M, N, O). Upper case only, so 'category of' adds nothing."""
    return sorted({t[0] for m in CATEGORY.finditer(text) for t in re.findall(r"[LMNOT]\d?[A-Za-z]?", m.group(1))})


def parser_hash() -> str:
    """Hash of the selected parser's files (marker parser: parse_marker + marker_induce + marker_outline + parse), so cards are per parser."""
    files = [Path(parser_module().__file__)]
    if parser_name() != "rules":
        files = [files[0].with_name(n) for n in ("parse_marker.py", "marker_induce.py", "marker_outline.py", "parse.py")]
    return hashlib.sha1(b"".join(f.read_bytes() for f in files)).hexdigest()[:8]


def build_card(reg: str) -> dict:
    entry = corpus.entry_for(reg)
    path = corpus.pdf_path(entry, "base")
    doc = _parser()(path, grids=False)
    nodes = doc.nodes
    scope = re.sub(r"\s+", " ", " ".join(n.body for n in nodes if n.kind == "para" and not n.scope and n.num[:1] == (1,))).strip()
    with pymupdf.open(path) as pdf:
        front = re.sub(r"\s+", " ", " ".join(pdf[i].get_text() for i in range(min(3, pdf.page_count))))
    if not scope:  # a layout without a numbered first section (GTRs): the first words of the document
        scope = front[:SCOPE_CHARS * 2]
    heads = [re.sub(r"\s+", " ", n.title(60)).strip() for n in nodes
             if (n.kind == "para" and not n.scope and len(n.num) <= 2 and getattr(n, "children", [])) or n.kind in SCOPE_KINDS]
    toc = " · ".join(h for h in heads if h)
    combined = COMBINES.search(front)
    return {"regulation": reg, "title": entry["title"], "version": corpus.version_label(entry, "base"), "pages": doc.pages,
            "categories": vehicle_letters(scope), "scope": scope[:SCOPE_CHARS],
            "toc": toc if len(toc) <= TOC_CHARS else toc[:TOC_CHARS].rsplit(" · ", 1)[0] + " · …",
            "supersedes": ["UN R" + n for n in re.findall(r"\d+[A-Z]?", combined.group(1))] if combined else []}


class Catalog:
    def __init__(self, cache_dir: Path | None = ROOT / "runs" / "_cards"):
        self.index = corpus.load_index()
        self.names = [e["regulation"] for e in self.index if corpus.pdf_path(e, "base") is not None]
        self.cache_dir = cache_dir
        self.cards: dict[str, dict] = {}

    def load(self, log=lambda message: None) -> "Catalog":
        file = self.cache_dir / f"cards-{parser_hash()}.json" if self.cache_dir else None
        if file is not None and file.is_file():
            self.cards = json.loads(file.read_text(encoding="utf-8"))
        missing = [r for r in self.names if r not in self.cards]
        for k, reg in enumerate(missing, 1):
            log(f"[catalog] card {k}/{len(missing)}: {reg}")
            self.cards[reg] = build_card(reg)
        if missing and file is not None:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(self.cards, ensure_ascii=False, indent=1), encoding="utf-8")
        return self

    def superseded_by(self, reg: str) -> str | None:
        """The regulation whose introduction says it combines the provisions of `reg` (R7 -> R148), if that one is in the index."""
        return next((new for new, card in self.cards.items() if reg in card["supersedes"] and new != reg), None)

    def successor(self, reg: str) -> str:
        """`reg` itself, or the regulation that replaced it (followed to the end of the chain)."""
        seen = {reg}
        while (new := self.superseded_by(reg)) and new not in seen:
            seen.add(new)
            reg = new
        return reg

    def card_text(self, reg: str) -> str:
        card = self.cards[reg]
        meta = []
        if card["categories"]:
            meta.append("vehicle categories its scope names: " + ", ".join(card["categories"]))
        if card["supersedes"]:
            meta.append("combines the provisions of " + ", ".join(card["supersedes"]))
        if (new := self.superseded_by(reg)):
            meta.append(f"SUPERSEDED: its provisions are now in {new}")
        lines = [f"### {reg}: {card['title']} (base {card['version']}, {card['pages']} pages)"]
        if meta:
            lines.append("; ".join(meta))
        lines += [f"Scope: {card['scope']}", f"Contents: {card['toc']}"]
        return "\n".join(lines)

    def all_cards_text(self) -> str:
        return "\n\n".join(self.card_text(reg) for reg in self.names)
