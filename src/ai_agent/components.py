"""component_map.json: for every component of the product (the parts of the spec and the components of the drawing) the regulations, the sections and
the requirements of the submission that constrain it, and for every callout of the drawing the requirements that constrain the same quantity.

It is written after the run from what the run produced (profile.json, vision.json, trace.json, submission.json). It does not touch the extraction:
three kinds of small Sonnet calls (effort "components", medium) over the finished requirements.

  1. group: parts of the spec and components of the drawing that are the same physical thing become one component
  2. assign: every requirement of the submission to the components it is about (none: it constrains the product as a whole)
  3. callouts: every callout value of the drawing to the requirements that state a limit or a test on the same quantity

    python src/ai_agent/components.py runs/dev-rear-lamp/<run id>      # builds the file for an existing run
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

if __package__:
    from .llm import LLM
else:  # run as a script
    sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
    from ai_agent.llm import LLM

BATCH = 130  # requirements per assign call
TEXT_CHARS = 230

_STR = {"type": "string"}


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


GROUP_SCHEMA = _obj({"components": {"type": "array", "items": _obj({
    "id": {"type": "string", "description": "K1, K2 ..."}, "name": _STR,
    "keys": {"type": "array", "items": _STR, "description": "the P*/C* keys that are this component"}})}})
ASSIGN_SCHEMA = _obj({"assignments": {"type": "array", "items": _obj({
    "requirement": _STR, "components": {"type": "array", "items": _STR, "description": "component ids K*; empty when it is about the whole product"}})}})
CALLOUT_SCHEMA = _obj({"callouts": {"type": "array", "items": _obj({
    "callout": {"type": "string", "description": "the callout id Q*"},
    "matches": {"type": "array", "items": _obj({
        "requirement": _STR,
        "relation": {"type": "string", "enum": ["same_quantity", "related_test", "same_topic"]},
        "why": {"type": "string", "description": "one short phrase"}})}})}})

GROUP_SYSTEM = """You merge two lists of the components of one product: the parts named in its written specification (keys P*) and the components read from \
its drawing (keys C*). A part and a component that name the same physical thing become one entry (for example "Outer lens" in both; \
"Reflector" and "Reflector surface"). Do not merge a light function (a rear position lamp, a stop lamp) with the part that realises it, and do not merge \
different physical parts. Every key appears in exactly one entry; give each entry a short name."""

ASSIGN_SYSTEM = """You link requirements of UN Regulations to the components of a product. For each requirement given, list the components (ids K*) that the \
requirement is about: it constrains the component itself, its material, the function it realises or the performance it has to show. A requirement that \
is about the product or the lamp as a whole, a marking, or a general test belongs to no component: return an empty list. Be selective: choose the \
components a reader would look at to check the requirement."""

CALLOUT_SYSTEM = """A drawing of a product carries callouts: a component and a performance value or test written next to it. You get the callouts (ids Q*) and the \
requirements of the product's type approval (ids, regulation, section, text). For each callout, list the requirements that state a limit, a value or a test \
on the same quantity (same_quantity: for example the luminous-intensity range of a lamp function; the visibility angle of a function), then those that \
state the test that checks it (related_test), then those that treat the same topic (same_topic, at most three). Quote nothing; give ids. A callout may \
have no match: return an empty list rather than a stretch."""


def _req_line(req: dict) -> str:
    s = req["source"]
    return f"{req['id']} | {s['regulation']} | {s['paragraph']} | {' '.join(req['text'].split())[:TEXT_CHARS]}"


def component_inputs(profile: dict, facts: dict | None) -> tuple[list[str], dict]:
    """(lines for the group call, {callout id: callout}); parts P* from the profile, components C* from the drawing."""
    lines = [f"{p['key']} (spec) {p['name']}" + (f" - {p['role']}" if p.get("role") else "") for p in profile["parts"] if p.get("source") != "image"]
    callouts: dict[str, dict] = {}
    for c in (facts or {}).get("components", []):
        lines.append(f"{c['key']} (drawing) {c['name']}" + (f" - callout: {c['callout_text']}" if c["callout_text"] else ""))
        if c["callout_text"].strip():
            callouts[f"Q{len(callouts) + 1}"] = c
    return lines, callouts


def build_component_map(llm: LLM, run_dir: Path, case_id: str = "", log=print) -> dict:
    run_dir = Path(run_dir)
    read = lambda name: json.loads((run_dir / name).read_text(encoding="utf-8"))
    profile, submission, trace = read("profile.json"), read("submission.json"), read("trace.json")
    facts = read("vision.json") if (run_dir / "vision.json").is_file() else None
    requirements = submission["requirements"]
    node_of = {t["id"]: t for t in trace}

    lines, callouts = component_inputs(profile, facts)
    grouped = llm.complete_json(stage="components", label="group", system=GROUP_SYSTEM, user="Components:\n" + "\n".join(lines), schema=GROUP_SCHEMA,
                                max_tokens=8_000)["components"]
    comps = {g["id"]: {"id": g["id"], "name": g["name"], "keys": g["keys"], "sources": sorted({"image" if k.startswith("C") else "spec" for k in g["keys"]}),
                       "callouts": [], "requirement_ids": [], "via_callout": []} for g in grouped}
    key_to_comp = {k: g["id"] for g in grouped for k in g["keys"]}
    component_list = "\n".join(f"{g['id']} {g['name']}" for g in grouped)

    assigned: dict[str, list[str]] = {}
    for start in range(0, len(requirements), BATCH):
        batch = requirements[start:start + BATCH]
        user = f"Components:\n{component_list}\n\nRequirements (id | regulation | section | text):\n" + "\n".join(_req_line(r) for r in batch)
        answer = llm.complete_json(stage="components", label=f"assign {start // BATCH + 1}", system=ASSIGN_SYSTEM, user=user, schema=ASSIGN_SCHEMA,
                                   max_tokens=16_000)
        for item in answer["assignments"]:
            assigned[item["requirement"]] = [k for k in item["components"] if k in comps]
    for rid, ks in assigned.items():
        for k in ks:
            comps[k]["requirement_ids"].append(rid)

    callout_rows = []
    if callouts:
        listing = "\n".join(f"{q} | {c['name']} | {c['callout_text']}" for q, c in callouts.items())
        user = f"Callouts (id | component | text):\n{listing}\n\nRequirements (id | regulation | section | text):\n" + "\n".join(_req_line(r) for r in requirements)
        answer = llm.complete_json(stage="components", label="callouts", system=CALLOUT_SYSTEM, user=user, schema=CALLOUT_SCHEMA, max_tokens=16_000)
        by_id = {r["id"]: r for r in requirements}
        for item in answer["callouts"]:
            c = callouts.get(item["callout"])
            if c is None:
                continue
            comp = key_to_comp.get(c["key"])
            matches = [{"id": m["requirement"], "regulation": by_id[m["requirement"]]["source"]["regulation"],
                        "paragraph": by_id[m["requirement"]]["source"]["paragraph"], "page": by_id[m["requirement"]]["source"]["page"],
                        "relation": m["relation"], "why": m["why"]} for m in item["matches"] if m["requirement"] in by_id]
            row = {"component": comp, "component_name": c["name"], "callout_text": c["callout_text"], "values": c["values"],
                   "function_hint": c["function_hint"], "link_confidence": c["confidence"], "matches": matches}
            callout_rows.append(row)
            if comp in comps:
                comps[comp]["callouts"].append({"text": c["callout_text"], "values": c["values"]})
                for m in matches:
                    if m["relation"] != "same_topic" and m["id"] not in comps[comp]["requirement_ids"]:
                        comps[comp]["requirement_ids"].append(m["id"])
                        comps[comp]["via_callout"].append(m["id"])

    rows = []
    for comp in comps.values():
        regs: dict[str, dict] = defaultdict(lambda: {"requirements": 0, "sections": set()})
        for rid in comp["requirement_ids"]:
            t = node_of.get(rid)
            if t:
                regs[t["regulation"]]["requirements"] += 1
                regs[t["regulation"]]["sections"].add(t["paragraph"])
        rows.append({**comp, "requirement_count": len(comp["requirement_ids"]),
                     "regulations": {reg: {"requirements": v["requirements"], "sections": sorted(v["sections"])}
                                     for reg, v in sorted(regs.items(), key=lambda kv: -kv[1]["requirements"])}})
    whole = sorted(r["id"] for r in requirements if not assigned.get(r["id"]))
    result = {"case": case_id or submission.get("case_id", ""), "run": run_dir.name, "components": rows, "callouts": callout_rows,
              "whole_product_requirement_ids": whole, "requirements": len(requirements)}
    (run_dir / "component_map.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[components] {len(rows)} components, {len(callout_rows)} callouts, {len(whole)} requirements about the whole product")
    return result


def main(argv: list[str] | None = None) -> int:
    from ai_agent.config import Settings
    from ai_agent.llm import stderr_log

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    run_dir = Path(args[0])
    settings = Settings.from_env(max_cost_usd=float(args[1]) if len(args) > 1 else 2.0)
    llm = LLM(settings, log=stderr_log, call_log=run_dir / "calls.jsonl")
    build_component_map(llm, run_dir, log=stderr_log)
    print(f"spent ${llm.ledger.summary()['spent_usd']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
