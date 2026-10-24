"""Stage 4: the selected parts become atomic obligations, each judged against the profile (spec/proposal.md A3 and A4.5 in one pass).

The provisions of a regulation are cut into chunks (a subtree each, split at child boundaries when it is long). The model answers with one entry
for EVERY node of the chunk, in order, listing the obligations of the node (none, one or several); each obligation has a verbatim quote, a standalone
rewrite and four labels: modality, addressee, kind and how well it applies to the product (certain / likely / possible / unlikely). Two checks in code:

  * grounding: the quote is looked for in the node it names and in the other nodes of the chunk; a quote that is nowhere is rejected, one that sits in
    another node moves there. The page and the paragraph label come from the node, not from the model.
  * coverage: a node the answer leaves out, and a node with an empty list that says "shall", is handed back to the model once, alone; a model that
    stops early or skips a plain "shall" sentence (it did, at medium effort, with 1 obligation for 110 nodes) is caught instead of silently lost.

Nothing is dropped here: emit.py applies the policy, so every candidate and the reason it was kept or dropped stays on disk.
"""

from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .llm import LLM
from .store import RegGraph

MODALITY = ["obligation", "permission", "exemption", "definition", "scope"]
ADDRESSEE = ["product", "product_via_test", "test_setup", "manufacturer_process", "authority"]
KIND = ["design", "performance", "marking", "installation", "test-procedure", "conformity-of-production", "admin"]
APPLIES = ["certain", "likely", "possible", "unlikely"]
SHALL = re.compile(r"\b(?:shall|must|is required|are required)\b", re.I)

# The paragraphs of UN R175 whose expert requirements are shown below. eval/bench_extract.py leaves them out of its score, so that the independent
# benchmark does not grade the model on its own examples.
EXAMPLE_PARAGRAPHS = ("4.2", "5.1.1", "5.2.1", "5.2.3.1", "5.3.2", "6.1.7")

EXAMPLES = """\
Examples, from another regulation (UN R175, on a system called ACPE); the requirements are the experts' own. Note how they split, what they keep and \
how they word it.

Node 4.2: "An approval number shall be assigned to each vehicle type approved; its first two digits (00 for the Regulation in its initial form) shall \
indicate the series of amendments incorporating the most recent major technical amendments made to the Regulation at the time of issue of the approval. \
The same Contracting Party shall not assign the same number to the same vehicle type equipped with another type of ACPE, or to another vehicle type."
 1. The Contracting Party shall assign an approval number to each vehicle type approved.
 2. The first two digits of the approval number assigned to each vehicle type approved (00 for the Regulation in its initial form) shall indicate the \
series of amendments incorporating the most recent major technical amendments made to the Regulation at the time of issue of the approval.
 3. The same Contracting Party shall not assign the same approval number to the same vehicle type equipped with another type of ACPE, or to another \
vehicle type.

Node 5.1.1: "The ACPE shall be able to limit unintended acceleration of the vehicle when an accelerator control misapplication by the driver has been \
detected at least: (a) When an obstacle exists in front of the vehicle when the driving direction is selected to be forward, and (b) When an obstacle \
exists behind the vehicle when the driving direction is selected to be rearwards."
 1. When an accelerator control misapplication by the driver has been detected at least when an obstacle exists in front of the vehicle when the driving \
direction is selected to be forward, the ACPE shall be able to limit unintended acceleration of the vehicle.
 2. When an accelerator control misapplication by the driver has been detected at least when an obstacle exists behind the vehicle when the driving \
direction is selected to be rearwards, the ACPE shall be able to limit unintended acceleration of the vehicle.

Node 5.2.1: "Short term deactivation When a vehicle is equipped with a means to manually deactivate the ACPE, the ACPE shall be automatically reinstated \
at the initiation of any new engine start (or run cycle, as relevant). This requirement does not apply when a new engine start (or run cycle, as relevant) \
is performed automatically, e.g., the operation of a stop/start system. A deactivation warning shall be given at least at the time of deactivation."
 1. When a vehicle is equipped with a means to manually deactivate the ACPE, the ACPE shall be automatically reinstated at the initiation of any new \
engine start (or run cycle, as relevant), except that this requirement does not apply when a new engine start (or run cycle, as relevant) is performed \
automatically, e.g., the operation of a stop/start system.
 2. When a vehicle is equipped with a means to manually deactivate the ACPE, the ACPE shall give a deactivation warning at least at the time of deactivation.

Node 5.2.3.1: "When the vehicle is equipped with a means to automatically deactivate the ACPE, for instance in situations such as carrying a bicycle rack \
or towing a trailer, the following conditions shall apply as appropriate:" (its items are the child nodes 5.2.3.1.1, ...)
 1. Where the vehicle is equipped with a means to automatically deactivate the ACPE, for instance in situations such as carrying a bicycle rack or towing \
a trailer, the vehicle shall apply the following conditions as appropriate.

Node 5.3.2: "There shall not be an appreciable time interval between each ACPE self-check, and subsequently there shall not be a delay in illuminating the \
warning signal, in the case of an electrically detectable failure. However, if the vehicle speed is greater than 10 km/h at the time a failure is detected, \
the warning signal may be suppressed until the next time the vehicle speed is below 10 km/h."
 1. The ACPE shall not have an appreciable time interval between each self-check.
 2. If an electrically detectable failure occurs, then the ACPE shall not delay in illuminating the warning signal, however, if the vehicle speed is greater \
than 10 km/h at the time a failure is detected, the warning signal may be suppressed until the next time the vehicle speed is below 10 km/h.

Node 6.1.7: "At the request of the manufacturer and with the agreement of the Technical Service tests may be conducted under deviating test conditions \
(suboptimal conditions, e.g. on a not dry surface; below the specified minimum ambient temperature), whilst the performance requirements are still to be met."
 1. When tests are conducted under deviating test conditions (suboptimal conditions, e.g. on a not dry surface; below the specified minimum ambient \
temperature) at the request of the manufacturer and with the agreement of the Technical Service, the system shall still meet the performance requirements."""

SYSTEM = f"""You turn the provisions of a UN Regulation into the engineering requirements that a specific product has to meet, the way a regulatory expert \
writes them. You get the product profile, then the provisions as <node id=... page=... parent=...> blocks in document order (the children of a node follow \
it). You return an entry for EVERY node, in the order given: the obligations the node states (none, one or several).

How an expert writes requirements:
- One requirement is one subject and one constraint, with its condition. Each independent constraint of a paragraph is a requirement of its own: usually \
one per sentence, one per list item that is a separate constraint (the lead-in's condition goes into each), one per row of a table (the row's keys, such as \
class, category, colour or voltage system, written into the sentence). An exception that follows a constraint ("This requirement does not apply when ...", \
"However, ...") is part of the requirement it limits, not a requirement of its own. One constraint that takes several clauses stays one requirement.
- Be faithful to the paragraph. Keep its words, and keep EVERY condition, exception, tolerance, number, unit and cross-reference ("paragraph 5.8.1.") exactly \
as written, including those that concern cases the product does not have: the profile decides which requirements APPLY (the `applies` grade), never how one \
is worded. Add no fact that is not in the provision, and none from another sentence or another node.
- Make the subject explicit ("The <device> shall ...", "The manufacturer shall ..."). Bring a governing condition from a lead-in sentence, an earlier sentence \
or a heading into the requirement that depends on it. A provision stated as a plain value ("Number: Two") becomes a sentence ("The lamps shall be two in number.").
- A node that introduces a list ("... shall meet the following:", "the following conditions shall apply") states an obligation of its own: list it, keeping \
its pointer to the items, and list the items in their own nodes.
- A provision that hands a requirement to other paragraphs, annexes or tables ("shall meet the requirements of paragraph 5.1.4", "in accordance with Annex 4") \
is an obligation; keep the pointer.
- A permission that sets a condition on the product ("tests may be conducted under ..., whilst the performance requirements are still to be met") is written as \
the obligation it implies. A bare permission or exemption, a definition and a scope statement are listed with the modality that says so (they may be dropped \
later); they are not obligations.
- Never leave an obligation out because you think it does not apply to this product, or because a condition ("in case ... is used", "where ...") may not hold: \
list it and grade it. Omit only what is no obligation.

For each obligation:
- `quote`: the shortest verbatim span of that node that carries it (for a table row, the row as printed in the grid).
- `text`: the requirement, as above.
- `modality`: obligation (shall / must / is required, or a requirement stated as a plain value); permission (may, need not); exemption (does not apply, deemed \
to comply); definition; scope.
- `addressee`, decided by what is constrained, not by who is named: product (the device or vehicle, its properties, performance, markings or installation, or \
what its samples have to meet: "the two samples supplied shall meet Table 4" constrains the product); product_via_test (a test condition or pass criterion the \
product is judged by: a frequency range, an exposure, a limit after a test); test_setup (how a laboratory arranges instruments, fixtures and measurements); \
manufacturer_process (what the applicant or manufacturer does in the approval process: applications, documents, samples to submit, production control, \
inspections); authority (what the approval authority or technical service does).
- `kind`: design, performance, marking, installation, test-procedure, conformity-of-production or admin.
- `applies`, against the profile: certain (the profile has the function, part or feature the provision is about); likely (applies unless a detail the profile \
does not state contradicts it); possible (applies only if something the profile does not state turns out a certain way, for example a condition "in case ... is \
used"); unlikely (it is about a variant the profile does not have: another function, device type, vehicle category, class, colour or technology, or something \
under "Not present" or contradicted by an attribute). Use the attributes to choose table rows (the row for the product's own category, class or colour) and \
grade the other rows unlikely.
- `why`: at most 15 words.

Every node of the input appears once in your answer; a node with no obligation (a heading, a definition, an introduction, a pure pointer) has an empty list.

{EXAMPLES}"""


def _schema() -> dict:
    item = {"type": "object", "properties": {
        "quote": {"type": "string"}, "text": {"type": "string"}, "modality": {"type": "string", "enum": MODALITY},
        "addressee": {"type": "string", "enum": ADDRESSEE}, "kind": {"type": "string", "enum": KIND}, "applies": {"type": "string", "enum": APPLIES},
        "why": {"type": "string"}},
        "required": ["quote", "text", "modality", "addressee", "kind", "applies", "why"], "additionalProperties": False}
    entry = {"type": "object", "properties": {"node": {"type": "string"}, "obligations": {"type": "array", "items": item}},
             "required": ["node", "obligations"], "additionalProperties": False}
    return {"type": "object", "properties": {"nodes": {"type": "array", "items": entry}}, "required": ["nodes"], "additionalProperties": False}


SCHEMA = _schema()


@dataclass
class Chunk:
    reg: str
    index: int
    nodes: list[int]
    context: list[str]
    chars: int


def _size(graph: RegGraph, ids: list[int]) -> int:
    return sum(len(graph.text[j]) + 70 for j in ids)


def plan_chunks(graph: RegGraph, node_ids: list[int], max_chars: int) -> list[Chunk]:
    """Cut the selected nodes into chunks of at most `max_chars`, along the tree: a subtree that is too long is split into its node and its
    children's subtrees, and neighbouring parts are packed together again up to the limit. A single node over the limit is a chunk of its own."""
    chosen = set(node_ids)

    def split(i: int) -> list[list[int]]:
        ids = [j for j in graph.subtree(i) if j in chosen]
        if _size(graph, ids) <= max_chars:
            return [ids]
        parts = [[i]] if i in chosen else []
        for child in graph.children[i]:
            if child in chosen:
                parts += split(child)
        return parts

    parts: list[list[int]] = []
    for top in (i for i in node_ids if graph.parent[i] not in chosen):
        parts += split(top)
    packed: list[list[int]] = []
    current: list[int] = []
    for part in parts:
        if current and _size(graph, current) + _size(graph, part) > max_chars:
            packed.append(current)
            current = []
        current = current + part
    if current:
        packed.append(current)
    chunks = []
    for k, ids in enumerate(packed, 1):
        inside = set(ids)
        context = list(dict.fromkeys(graph.nodes[graph.parent[j]].path for j in ids if graph.parent[j] >= 0 and graph.parent[j] not in inside))
        chunks.append(Chunk(graph.reg, k, ids, context, _size(graph, ids)))
    return chunks


def chunk_content(graph: RegGraph, chunk: Chunk, profile_md: str, nodes: list[int] | None = None, note: str = "") -> list[dict]:
    """The user message of one extraction call: the profile first (the same bytes on every call, so it is cached), then the nodes."""
    context = "\n".join(f"- {c}" for c in chunk.context) or "- (top level)"
    body = (f"Regulation: {graph.reg} - {graph.title} (version {graph.version})\n"
            f"Context: the titles above the first node of each group below:\n{context}\n\n"
            f"Provisions:\n{graph.render(chunk.nodes if nodes is None else nodes)}\n\n"
            + (note or f"Give an entry for each of the {len(chunk.nodes)} nodes, in order."))
    return [{"type": "text", "text": f"Product profile:\n{profile_md}", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": body}]


def ground(graph: RegGraph, chunk: Chunk, item: dict) -> dict:
    """The candidate for one model item: the node that really holds the quote, its page and paragraph label, or a rejection. Only the nodes
    of the chunk count: the model read those, so a quote that is only in some other node of the regulation was not taken from what it was given."""
    named = graph.resolve(item.get("node"))
    named = named if named in set(chunk.nodes) else None
    found = graph.locate(item.get("quote", ""), named, chunk.nodes)
    base = {"regulation": graph.reg, "version": graph.version, "chunk": chunk.index, "text": " ".join(str(item.get("text", "")).split()),
            "quote": item.get("quote", ""), "modality": item.get("modality"), "addressee": item.get("addressee"), "kind": item.get("kind"),
            "applies": item.get("applies"), "why": item.get("why", ""), "named_node": item.get("node")}
    if found is None or not base["text"]:
        return {**base, "node": None, "paragraph": None, "page": None, "status": "rejected:quote" if base["text"] else "rejected:empty"}
    idx, share = found
    return {**base, "node": graph.ids[idx], "node_idx": idx, "paragraph": graph.nodes[idx].label, "page": graph.page_of(idx, base["quote"]),
            "quote_match": round(share, 3), "reassigned": idx != named, "status": ""}


REPAIR_NOTE = ("These nodes were left out of your answer, or you listed nothing for them although they say 'shall' / 'must'. Read each again. Give an entry "
               "for each, with its obligations, or an empty list if it states none.")


def extract_chunk(llm: LLM, graph: RegGraph, chunk: Chunk, profile_md: str) -> tuple[list[dict], dict]:
    """(candidates, stats) of one chunk: the answer, grounded, plus one repair pass for the nodes it skipped."""
    answer = llm.complete_json(stage="obligations", label=f"{graph.reg} chunk {chunk.index}", system=SYSTEM,
                               user=chunk_content(graph, chunk, profile_md), schema=SCHEMA, max_tokens=48_000)
    inside = set(chunk.nodes)
    listed: dict[int, int] = defaultdict(int)  # node -> obligations listed for it
    entries: list[tuple[str, dict]] = []
    for entry in answer["nodes"]:
        idx = graph.resolve(entry["node"])
        if idx in inside:
            listed[idx] += len(entry["obligations"])
        entries += [(entry["node"], item) for item in entry["obligations"]]
    missing = [i for i in chunk.nodes if i not in listed]
    silent = [i for i in chunk.nodes if i in listed and not listed[i] and SHALL.search(graph.nodes[i].body)]
    stats = {"index": chunk.index, "nodes": len(chunk.nodes), "chars": chunk.chars, "entries": len(answer["nodes"]), "missing": len(missing),
             "silent_shall": len(silent), "repaired_nodes": 0, "repaired_obligations": 0}
    repair = (missing + silent)[:80]
    repaired: list[tuple[str, dict]] = []
    if repair:
        stats["repaired_nodes"] = len(repair)
        again = llm.complete_json(stage="obligations", label=f"{graph.reg} chunk {chunk.index} repair", system=SYSTEM,
                                  user=chunk_content(graph, chunk, profile_md, repair, REPAIR_NOTE), schema=SCHEMA, max_tokens=32_000)
        for entry in again["nodes"]:
            idx = graph.resolve(entry["node"])
            if idx in repair:
                repaired += [(entry["node"], item) for item in entry["obligations"]]
        stats["repaired_obligations"] = len(repaired)
    out = []
    for source, batch in (("answer", entries), ("repair", repaired)):
        for named, item in batch:
            candidate = ground(graph, chunk, {**item, "node": named})
            candidate["source"] = source
            out.append(candidate)
    return out, stats


def extract_all(llm: LLM, graphs: dict[str, RegGraph], nodes: dict[str, list[int]], profile_md: str, workers: int, chunk_chars: int,
                log=lambda message: None) -> tuple[list[dict], dict[str, list[Chunk]], list[dict], list[dict]]:
    """Every candidate obligation of the selected nodes, the chunk plan, the chunks that failed (reported, not fatal) and per-chunk statistics."""
    plan = {reg: plan_chunks(graphs[reg], ids, chunk_chars) for reg, ids in nodes.items()}
    jobs = [(reg, chunk) for reg, chunks in plan.items() for chunk in chunks]
    log(f"[obligations] {len(jobs)} chunks over {len(plan)} regulations ({sum(c.chars for _, c in jobs) // 1000}K characters)")
    found: dict[tuple[str, int], list[dict]] = {}
    stats: list[dict] = []
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(extract_chunk, llm, graphs[reg], chunk, profile_md): (reg, chunk) for reg, chunk in jobs}
        for future in as_completed(futures):
            reg, chunk = futures[future]
            try:
                found[(reg, chunk.index)], chunk_stats = future.result()
                stats.append({"regulation": reg, **chunk_stats})
            except Exception as error:  # a chunk that fails is reported; a spent budget stops the run
                if type(error).__name__ == "BudgetExceeded":
                    raise
                failures.append({"regulation": reg, "chunk": chunk.index, "error": f"{type(error).__name__}: {error}"})
                log(f"[obligations] {reg} chunk {chunk.index} failed: {error}")
    ordered = [c for reg, chunk in jobs for c in found.get((reg, chunk.index), [])]
    by_node: dict[tuple[str, int], int] = defaultdict(int)
    for c in ordered:  # the order of the obligations of one node is the order the model listed them
        if c.get("node_idx") is not None:
            c["ordinal"] = by_node[(c["regulation"], c["node_idx"])]
            by_node[(c["regulation"], c["node_idx"])] += 1
    return ordered, plan, failures, sorted(stats, key=lambda s: (s["regulation"], s["index"]))
