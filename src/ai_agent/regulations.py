"""Stage 2: which of the 56 regulations apply (spec/proposal.md A4.2), and the citation hop that follows the section walk.

One call reads every card at once (about 43K tokens) against the profile. It is asked to be strict: on the oracle section list a wrong
regulation costs far more than a missing marginal one (spec/finding/mapping-simulation.md 3.4). Supersession is applied in code afterwards:
a superseded regulation is replaced by the one that combined its provisions.
"""

from __future__ import annotations

from .catalog import Catalog
from .llm import LLM

SELECT_SYSTEM = """You decide which UN Regulations a product has to be approved against or comply with. You get the product profile and one \
card per available regulation (title, vehicle categories its scope names, scope, contents, supersession).

Think at three levels and look for regulations at each of them:
- device level: regulations that approve the product itself as a device or component;
- vehicle level: regulations on how the product is installed on a vehicle or what it must do there;
- horizontal level: regulations that apply because of a technology, material or feature the product contains, whatever the product does.

Be strict. Select a regulation only if you can name a part, function, material, technology or regulatory concept of the profile that falls \
inside its scope as the card prints it. A regulation that does not apply costs much more than a marginal one you leave out, so do not select \
"to be safe". Do not select regulations written for other vehicle categories than the product's, or for other kinds of product.

A card marked SUPERSEDED has been replaced: its provisions are now in the regulation it names. Never select a superseded regulation; select \
its successor if the profile calls for it.

Fill `covers` with the profile keys (F1, P2, T1, ...) the regulation is about. `close_calls` lists up to ten regulations you looked at hard \
and left out, each with the reason."""


# v2: the threshold moves from "strict" to "plausible". The bench scores recall twice as heavily as precision (F2), a regulation left out loses
# every requirement of it for good, and a marginal one is still weighed by the later stages. Same schema and the same cards; only the rules differ.
SELECT_SYSTEM_V2 = """You decide which UN Regulations a product has to be approved against or comply with. You get the product profile and one card per available regulation (title, vehicle categories its scope names, scope, contents, supersession).

Think like the engineer who writes the type-approval test plan for this product and the vehicle it goes on. Look for regulations at three levels:
- device level: regulations that approve the product itself as a device or component;
- vehicle level: regulations on how the product is installed on a vehicle or what it must do there, and regulations on the vehicle system the product belongs to;
- horizontal level: regulations that apply because of a technology, material or feature the product contains or relies on, whatever the product does.

Selecting is a recall task: a regulation you leave out loses all of its requirements for good, while one that turns out marginal is weighed again by the later steps. So select a regulation when a part, function, material, technology, interface or regulatory concept of the profile plausibly falls inside its scope as the card prints it, and say in `reason` which one. Use `confidence` for how direct the link is: high when the regulation is written for this kind of product, medium when it applies through a feature or a system the product belongs to, low when the link is indirect or depends on a detail the profile does not settle. Do not select a regulation whose scope excludes the product's vehicle category or kind of product, or whose subject the profile lists under not present.

A card marked SUPERSEDED has been replaced: its provisions are now in the regulation it names. Never select a superseded regulation; select its successor if the profile calls for it.

Fill `covers` with the profile keys (F1, P2, T1, ...) the regulation is about. `close_calls` lists up to ten regulations you looked at hard and left out, each with the reason."""


def _schema(names: list[str]) -> dict:
    reg = {"type": "string", "enum": names}
    return {"type": "object", "properties": {
        "selected": {"type": "array", "items": {"type": "object", "properties": {
            "regulation": reg, "level": {"type": "string", "enum": ["device", "vehicle", "horizontal"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "covers": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}},
            "required": ["regulation", "level", "confidence", "covers", "reason"], "additionalProperties": False}},
        "close_calls": {"type": "array", "items": {"type": "object", "properties": {"regulation": reg, "reason": {"type": "string"}},
                                                    "required": ["regulation", "reason"], "additionalProperties": False}}},
        "required": ["selected", "close_calls"], "additionalProperties": False}


def select_regulations(llm: LLM, catalog: Catalog, profile_md: str, max_regulations: int, version: str = "v1") -> dict:
    """{'selected': [...], 'rejected': [...], 'redirects': {...}, 'dropped': [...]} with the supersession applied to the model's picks."""
    user = (f"Product profile:\n{profile_md}\n\nAvailable regulations ({len(catalog.names)}):\n\n{catalog.all_cards_text()}\n\n"
            "Select the regulations that apply.")
    answer = llm.complete_json(stage="regulations", label="select", system=SELECT_SYSTEM_V2 if version in ("v2", "v3") else SELECT_SYSTEM, user=user, schema=_schema(catalog.names),
                               max_tokens=16_000)
    order = {"high": 0, "medium": 1, "low": 2}
    selected, redirects, seen = [], {}, set()
    for item in answer["selected"]:
        reg = catalog.successor(item["regulation"])
        if reg != item["regulation"]:
            redirects[item["regulation"]] = reg
        if reg in seen:
            continue
        seen.add(reg)
        selected.append({**item, "regulation": reg, **({"redirected_from": item["regulation"]} if reg != item["regulation"] else {})})
    selected.sort(key=lambda item: order[item["confidence"]])  # stable: ties keep the model's order
    dropped = [item["regulation"] for item in selected[max_regulations:]]
    return {"selected": selected[:max_regulations], "rejected": answer["close_calls"], "redirects": redirects, "dropped": dropped}


VET_SYSTEM = """A product has been matched to some UN Regulations, and the provisions selected from them cite other regulations. You decide \
which cited regulations ALSO hold requirements this product itself has to meet. You get the product profile, and for each cited regulation its \
card and the sentence that cites it.

Add a regulation only when the citation hands the product a requirement (for example "type-approved according to Regulation No. X": the \
product has to be approved to X) and the product falls inside X's scope. Do not add a regulation that is cited for another kind of device, \
for a vehicle-level test, for a definition, or as a historical reference. A card marked SUPERSEDED is replaced by the regulation it names; \
you are shown the successor instead."""


# v2: the sentence that cites a regulation is evidence the text itself gives; a part or component of the product that falls under the cited
# regulation is enough, the product need not be that regulation's main subject.
VET_SYSTEM_V2 = """A product has been matched to some UN Regulations, and the provisions selected from them cite other regulations. You decide which cited regulations ALSO hold requirements this product, or one of its parts, components or functions, has to meet. You get the product profile, and for each cited regulation its card and the sentence that cites it.

Add a regulation when the citation hands the product, or a part, component or function of it, a requirement (for example "type-approved according to Regulation No. X", or a test or condition that Regulation X defines and this product has to satisfy) and that part or function plausibly falls inside X's scope. The product does not have to be X's main subject. Do not add a regulation that is cited only for another kind of device, a definition, or a historical reference. A card marked SUPERSEDED is replaced by the regulation it names; you are shown the successor instead."""


def vet_cited(llm: LLM, catalog: Catalog, profile_md: str, cited: dict[str, dict], version: str = "v1") -> dict:
    """`cited` is {regulation: {'count', 'nodes', 'snippet', 'by': [regulations that cite it]}}. Returns {'add': [...], 'skip': [...]}."""
    if not cited:
        return {"add": [], "skip": []}
    names = sorted(cited)
    blocks = [f"{catalog.card_text(reg)}\nCited {cited[reg]['count']}x by {', '.join(cited[reg]['by'])} (nodes {', '.join(cited[reg]['nodes'][:4])}): "
              f"\"{cited[reg]['snippet']}\"" for reg in names]
    reg = {"type": "string", "enum": names}
    schema = {"type": "object", "properties": {
        "add": {"type": "array", "items": {"type": "object", "properties": {"regulation": reg, "reason": {"type": "string"}},
                                           "required": ["regulation", "reason"], "additionalProperties": False}},
        "skip": {"type": "array", "items": {"type": "object", "properties": {"regulation": reg, "reason": {"type": "string"}},
                                            "required": ["regulation", "reason"], "additionalProperties": False}}},
        "required": ["add", "skip"], "additionalProperties": False}
    user = f"Product profile:\n{profile_md}\n\nCited regulations:\n\n" + "\n\n".join(blocks) + "\n\nWhich of them to add?"
    return llm.complete_json(stage="regulations", label="vet-cited", system=VET_SYSTEM_V2 if version == "v2" else VET_SYSTEM, user=user, schema=schema, max_tokens=8_000)
