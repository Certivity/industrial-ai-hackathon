"""Stage 1: the product spec becomes a profile: what the product is, does, is made of and is not, in the words a regulation uses as well as
the spec's own (spec/proposal.md A4.1). The input is the text of the spec, the facts that vision.py read from a drawing, or both. With text only the
prompt, the schema and the profile are exactly what they were before drawings were read (so cached runs still replay); with a drawing the schema
adds `source` to parts and attributes ("image" for what only the drawing says) and profile.md gets a block with the drawing's callouts, verbatim.
"""

from __future__ import annotations

import copy

from .llm import LLM
from .vision import callouts_text, facts_for_prompt

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


IMAGE_RULES = """

A drawing was read as well (its facts are given below the specification, or alone). Rules for it:
- Parts, functions and attributes that only the drawing shows are marked source "image"; those the specification states (also when the drawing repeats them) are "spec"; "both" is for a part that both name. The specification wins where the two disagree.
- The callouts of the drawing state intended performance, tests or conditions of a part (a range, an angle, a test). Keep each one as an attribute named after the part and the quantity, value as printed, source "image". They are requirements the product is meant to meet: the regulatory concepts should cover every one of them.
- The callouts add to the regulatory concepts, they do not replace them: every part, material and technology still gets its own concepts, including the horizontal ones (electronics, materials, marking, installation), exactly as if there were no drawing.
- A callout with low link confidence is still reported, but do not build a part on it alone.
- Without a written specification, build the whole profile from the drawing and from what follows directly from it; what you add from general knowledge of such products is marked "inferred" (attributes) and keep `not_present` to what the drawing makes clear."""


def _image_schema() -> dict:
    schema = copy.deepcopy(SCHEMA)
    source = {"type": "string", "enum": ["spec", "image", "both"]}
    schema["properties"]["parts"]["items"] = _obj({**schema["properties"]["parts"]["items"]["properties"], "source": source})
    schema["properties"]["attributes"]["items"] = _obj({"name": _STR, "value": _STR, "source": {"type": "string", "enum": ["stated", "inferred", "image"]}})
    schema["properties"]["regulatory_concepts"] = {"type": "array", "items": _STR, "description": "5 to 25 phrases: the topics under which regulations address this product, its parts and its drawn callouts."}
    return schema


IMAGE_SCHEMA = _image_schema()


def build_profile(llm: LLM, spec_text: str | None, facts: dict | None = None) -> dict:
    if facts is None:
        if spec_text is None:
            raise ValueError("build_profile needs the text of a spec, the facts of a drawing, or both")
        user = f"Specification (markdown):\n\n<spec>\n{spec_text.strip()}\n</spec>\n\nWrite the profile."
        return llm.complete_json(stage="profile", label="profile", system=SYSTEM, user=user, schema=SCHEMA, max_tokens=12_000)
    spec = (f"Specification (markdown):\n\n<spec>\n{spec_text.strip()}\n</spec>\n\n" if spec_text
            else "There is no written specification: the drawing is the only input.\n\n")
    user = f"{spec}Drawing facts (read from the image):\n\n<drawing>\n{facts_for_prompt(facts)}\n</drawing>\n\nWrite the profile."
    return llm.complete_json(stage="profile", label="profile", system=SYSTEM + IMAGE_RULES, user=user, schema=IMAGE_SCHEMA, max_tokens=14_000)


def profile_text(profile: dict, facts: dict | None = None) -> str:
    """The profile as the later prompts show it: compact markdown, the same bytes on every call (so that it can be cached)."""
    lines = [f"Product: {profile['product']}", f"Summary: {profile['summary']}",
             "Vehicle categories: " + ", ".join(profile["vehicle_categories"])]
    lines.append("Functions: " + "; ".join(f"{f['key']} {f['name']}" + (f" ({f['detail']})" if f["detail"] else "") for f in profile["functions"]))
    lines.append("Parts: " + "; ".join(f"{p['key']} {p['name']}" + (f" - {p['role']}" if p["role"] else "")
                                       + (f" [{', '.join(p['materials'])}]" if p["materials"] else "")
                                       + (" (drawing)" if p.get("source") == "image" else "") for p in profile["parts"]))
    lines.append("Technologies: " + "; ".join(f"{t['key']} {t['name']} -> {', '.join(t['regulatory_concepts'])}" for t in profile["technologies"]))
    lines.append("Attributes: " + "; ".join(f"{a['name']} = {a['value']} ({a['source']})" for a in profile["attributes"]))
    if facts is not None and callouts_text(facts):
        lines.append("Annotated requirements from the drawing (callout texts, verbatim): " + callouts_text(facts))
    lines.append("Regulatory concepts: " + "; ".join(profile["regulatory_concepts"]))
    lines.append("Not present: " + "; ".join(profile["not_present"]))
    return "\n".join(lines)
