"""Stage 1: the product spec becomes a profile: what the product is, does, is made of and is not, in the words a regulation uses as well as
the spec's own (spec/proposal.md A4.1). Only the text of spec.md is read; the exploded view is the next step.
"""

from __future__ import annotations

from .llm import LLM

SYSTEM = """You are a vehicle-regulation engineer. You read a product specification and write the profile that the later steps use to find \
the UN Regulations (UNECE, 1958 Agreement) and the provisions the product has to meet.

Write the profile in two vocabularies: the specification's own words, and the words a UN Regulation would use for the same thing. \
A regulation can apply because of what the product does, but also because of what it is made of, what it contains, where it is mounted \
or which vehicle it is for. For every part, material and technology ask: under which regulatory category or concept would a regulation \
treat this? Name those concepts (device and sub-assembly categories, material and test domains, vehicle-level topics). Illustration from \
another domain: a safety-belt buckle is also a "restraint system component" and falls under "anchorages and strength" topics; a tyre is \
also a "pneumatic tyre" with "rolling resistance" and "wet grip" topics.

Rules:
- Use only what the specification says or what follows from it directly. An attribute that you infer (for example the colour of emitted light \
from the colour of a lens) is marked "inferred"; one the specification states is marked "stated".
- `not_present` lists functions, devices or features that similar products often have and that this one does not (the specification does not \
mention them and they would be a different product variant). It is used to discard provisions written for those variants.
- Keys are F1, F2 ... for functions, P1, P2 ... for parts, T1, T2 ... for technologies.
- Be concise: names and short phrases, no prose beyond `summary`."""

_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


SCHEMA = _obj({
    "product": _STR,
    "summary": {"type": "string", "description": "One to three plain sentences: what the product is and where it sits on the vehicle."},
    "vehicle_categories": {"type": "array", "items": _STR, "description": "UN vehicle categories (M1, N1, L3 ...). ['unspecified'] if unknown."},
    "functions": {"type": "array", "items": _obj({"key": _STR, "name": _STR, "detail": _STR})},
    "parts": {"type": "array", "items": _obj({"key": _STR, "name": _STR, "role": _STR, "materials": _STRS})},
    "technologies": {"type": "array", "items": _obj({"key": _STR, "name": _STR, "regulatory_concepts": _STRS})},
    "attributes": {"type": "array", "items": _obj({"name": _STR, "value": _STR, "source": {"type": "string", "enum": ["stated", "inferred"]}})},
    "regulatory_concepts": {"type": "array", "items": _STR, "description": "5 to 15 phrases: the topics under which regulations address this product."},
    "not_present": _STRS,
})


def build_profile(llm: LLM, spec_text: str) -> dict:
    user = f"Specification (markdown):\n\n<spec>\n{spec_text.strip()}\n</spec>\n\nWrite the profile."
    return llm.complete_json(stage="profile", label="profile", system=SYSTEM, user=user, schema=SCHEMA, max_tokens=12_000)


def profile_text(profile: dict) -> str:
    """The profile as the later prompts show it: compact markdown, the same bytes on every call (so that it can be cached)."""
    lines = [f"Product: {profile['product']}", f"Summary: {profile['summary']}",
             "Vehicle categories: " + ", ".join(profile["vehicle_categories"])]
    lines.append("Functions: " + "; ".join(f"{f['key']} {f['name']}" + (f" ({f['detail']})" if f["detail"] else "") for f in profile["functions"]))
    lines.append("Parts: " + "; ".join(f"{p['key']} {p['name']}" + (f" - {p['role']}" if p["role"] else "")
                                       + (f" [{', '.join(p['materials'])}]" if p["materials"] else "") for p in profile["parts"]))
    lines.append("Technologies: " + "; ".join(f"{t['key']} {t['name']} -> {', '.join(t['regulatory_concepts'])}" for t in profile["technologies"]))
    lines.append("Attributes: " + "; ".join(f"{a['name']} = {a['value']} ({a['source']})" for a in profile["attributes"]))
    lines.append("Regulatory concepts: " + "; ".join(profile["regulatory_concepts"]))
    lines.append("Not present: " + "; ".join(profile["not_present"]))
    return "\n".join(lines)
