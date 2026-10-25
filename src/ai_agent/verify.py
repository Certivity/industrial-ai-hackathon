"""Stage 2b (AI_AGENT_SELECT=v3): shortlist, then verify against the scope text (spec/finding/selection-tuning.md section 8).

The recall-oriented selection (regulations.SELECT_SYSTEM_V2) is the shortlist. One call per shortlisted regulation then reads the product
profile against the verbatim Scope section of that regulation (paragraph 1 and its sub-paragraphs from the regcomp parse of the version the
agent uses), the definitions when they are short, and the supersession note. A yes counts only when the clause it quotes is word for word in
the scope text (checked here, not by the model). The rules are the expert conventions of the other prompts; nothing is specific to a case,
a product, a regulation or a label.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .catalog import Catalog
from .llm import LLM

VERIFY_SYSTEM = """You check whether one UN Regulation applies to a product. You get the product profile and, for one regulation, its card, the \
verbatim text of its Scope section (paragraph 1 and its sub-paragraphs), the definitions when they are short, and a supersession note. Decide \
from these texts and the profile only.

The regulation applies when the product, or a part, sub-assembly or function of it that the profile lists as present, falls inside the scope \
as the scope text prints it, including the vehicle categories it names. It does not apply when the scope excludes the product's vehicle \
category or kind of product, when the scope covers a different kind of device, or when the part it is about is not in the product.

Conventions of a type-approval engineer:
- Use the current regulation. If the note says it is SUPERSEDED, answer no; its successor is judged separately.
- A horizontal regulation (electromagnetic compatibility, cyber security, software update, and similar) applies only when the product itself \
contains the electrical/electronic or software sub-assembly it addresses, not merely because the vehicle it goes on does. When such a regulation's scope speaks of vehicles, the product still falls inside it through that sub-assembly (an ECU, software, a communication interface) even though the approval itself is granted to the vehicle; judge whether the product contains the sub-assembly, not whether it is a vehicle.
- A vehicle-level installation regulation applies only when the product is a device or part that its installation provisions address (the lamps, \
the mirrors, the tyres, the coupling ...); a product that is just fitted to a vehicle of the right category is not enough.

Answer with `applies` (yes or no); `scope_clause`: a short quote copied word for word from the scope text that decides it (for a no, the clause \
that excludes the product, or empty); `product_part`: the part or function of the product it concerns, or "none"; `reason`: one or two sentences."""

VERIFY_SCHEMA = {"type": "object", "properties": {
    "applies": {"type": "string", "enum": ["yes", "no"]}, "scope_clause": {"type": "string"},
    "product_part": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["applies", "scope_clause", "product_part", "reason"], "additionalProperties": False}

DEFS_CHARS = 2500


def scope_text(nodes: list) -> tuple[str, str]:
    """(scope, definitions) of a parsed regulation: the text of paragraph 1 with its sub-paragraphs, and paragraph 2 (definitions) only when it
    is at most DEFS_CHARS long, else ''. `nodes` are the regcomp parse nodes (kind, num, scope, body)."""
    def block(first: int) -> str:
        return "\n".join(re.sub(r"\s+", " ", n.body).strip() for n in nodes if n.kind == "para" and not n.scope and n.num[:1] == (first,)).strip()
    defs = block(2)
    return block(1), defs if len(defs) <= DEFS_CHARS else ""


def norm(text: str) -> list[str]:
    """Tokens of letters and digits, case-folded; a thousands separator is dropped ("1,500" = "1500")."""
    return re.findall(r"[^\W_]+", re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text).casefold())


def quote_is_verbatim(quote: str, text: str, min_tokens: int = 3) -> bool:
    """The quote is a contiguous run of the text, up to case, punctuation and spacing. A quote of fewer than `min_tokens` tokens proves
    nothing and does not count. A quote may join clauses with an ellipsis; each piece is checked on its own."""
    hay = norm(text)
    pieces = [norm(p) for p in re.split(r"\.{3}|…", quote or "")]
    pieces = [p for p in pieces if p]
    if not pieces or sum(len(p) for p in pieces) < min_tokens:
        return False
    return all(any(hay[i:i + len(p)] == p for i in range(len(hay) - len(p) + 1) if hay[i] == p[0]) for p in pieces)


def verify_regulation(llm: LLM, catalog: Catalog, profile_md: str, reg: str, scope: str, defs: str = "") -> dict:
    """One verification. {'regulation', 'applies', 'scope_clause', 'quote_verbatim', 'product_part', 'reason', 'retried', 'accepted'}.
    A yes whose quote is not verbatim in the scope text is asked once more; if it still is not, it is unverified and not accepted."""
    successor = catalog.superseded_by(reg)
    note = f"SUPERSEDED: its provisions are now in {successor}" if successor else "not superseded"
    scope = scope or "(no numbered paragraph 1 in this document; the card above carries the first words of the document)"
    user = (f"Product profile:\n{profile_md}\n\n=== {reg} ===\n{catalog.card_text(reg)}\n\nScope section (verbatim):\n{scope}\n\n"
            + (f"Definitions (verbatim):\n{defs}\n\n" if defs else "") + f"Supersession note: {note}\n\nDoes {reg} apply to this product?")
    answer = llm.complete_json(stage="verify", label=f"verify {reg}", system=VERIFY_SYSTEM, user=user, schema=VERIFY_SCHEMA, max_tokens=4_000)
    ok = quote_is_verbatim(answer["scope_clause"], scope)
    retried = answer["applies"] == "yes" and not ok
    if retried:
        again = llm.complete_json(
            stage="verify", label=f"verify {reg} (quote)", system=VERIFY_SYSTEM, schema=VERIFY_SCHEMA, max_tokens=4_000,
            user=user + f"\n\nYour earlier answer quoted \"{answer['scope_clause']}\", which is not word for word in the scope text. Answer again: "
            "quote the deciding clause exactly as printed, or answer no if no clause of the scope text covers the product.")
        answer, ok = again, quote_is_verbatim(again["scope_clause"], scope)
    return {"regulation": reg, "applies": answer["applies"] == "yes", "scope_clause": answer["scope_clause"], "quote_verbatim": ok,
            "product_part": answer["product_part"], "reason": answer["reason"], "retried": retried,
            "accepted": answer["applies"] == "yes" and ok}


def verify_all(llm: LLM, catalog: Catalog, profile_md: str, scopes: dict[str, tuple[str, str]], workers: int = 5) -> dict[str, dict]:
    """Verify every regulation of `scopes` ({reg: (scope, definitions)}); {reg: decision} in the order of `scopes`."""
    if not scopes:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {reg: pool.submit(verify_regulation, llm, catalog, profile_md, reg, *scopes[reg]) for reg in scopes}
        return {reg: f.result() for reg, f in futures.items()}


def shortlist_union(selected: list[dict], vetted_add: list[dict], cap: int) -> list[dict]:
    """The selection first (its order kept), then the vetted citations, each regulation once, at most `cap`. A citation counts as a
    medium-confidence vehicle-level pick marked `source: citation`."""
    out, seen = [], set()
    for item in selected:
        if item["regulation"] not in seen:
            seen.add(item["regulation"])
            out.append({**item, "source": item.get("source", "selection")})
    for item in vetted_add:
        if item["regulation"] not in seen:
            seen.add(item["regulation"])
            out.append({"regulation": item["regulation"], "level": "vehicle", "confidence": "medium", "covers": [],
                        "reason": item.get("reason", ""), "source": "citation"})
    return out[:cap]


def accepted_items(shortlist: list[dict], decisions: dict[str, dict]) -> list[dict]:
    """The shortlist items whose verification accepted them, in shortlist order, each with its verification attached."""
    return [{**item, "verification": decisions[item["regulation"]]} for item in shortlist
            if decisions.get(item["regulation"], {}).get("accepted")]
