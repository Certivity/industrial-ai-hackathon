"""Stage 3: the section walk (spec/proposal.md A4.3, with the tool surface of A5). One agent per regulation reads the outline, looks inside
with get_toc / read_node / search / follow_refs, and ends with select_sections. Selection is inclusive at section level: a section that is
left out is lost for good, one that is not needed only costs reading time, because the next stage reads every provision and drops what
does not apply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Settings
from .llm import LLM
from .store import RegGraph
from .tools import WalkerTools, expand

SYSTEM = """You are a regulatory engineer. A product (profile below) is to be approved. For ONE UN Regulation you decide which parts of it hold \
provisions the product has to meet. A later step reads every provision of the parts you select, one by one, and keeps only what applies. So \
your choice is about coverage: a part you leave out is lost for good, a part you did not need only costs reading time. Be inclusive at the \
level of sections, but do not select the whole regulation.

You see the regulation as an outline: every section with its page range and size. Look inside with get_toc, read_node, search and follow_refs, \
and finish with ONE call to select_sections. You refer to nodes only by the labels the tools show. You never write page numbers or paragraph \
numbers: the system takes them from the nodes you select.

Look for three kinds of part:
1. Parts named after something the product is or does: a section for each function, part and feature of the profile, and the sections on how \
the product is installed or must perform if this regulation governs that.
2. Parts that bind every device of this class whatever its function: general requirements and specifications, marking requirements, electrical \
and electronic requirements if the product contains electronics, requirements on materials, conformity-of-production requirements. Do not judge \
a part by its title: a section headed as administrative provisions or approval can carry marking or design requirements for the product. Read \
before you leave one out.
3. Test methods and annexes that fix a condition or a pass criterion for the product's functions, materials and technologies. Select the part, \
appendix or paragraph that applies, not a whole annex when only a part of it does.

Leave out: definitions and scope (read them for context, they hold no requirements); approval procedure and paperwork (application, \
communication forms, granting, extension, modification of a type, penalties, transitional provisions, discontinued production, names of technical \
services); and parts written only for other kinds of device, vehicle or category than the profile's. Where one section mixes applicable and \
foreign subsections, select it and `exclude` the foreign subsections.

Work efficiently: the outline shows the structure, so read a section only when its title does not settle the question. Run one search with the \
product's materials and technologies, and one for what the profile lists as regulatory concepts, before you submit. A walk is usually 8 to 20 \
tool calls."""


@dataclass
class WalkResult:
    reg: str
    selections: list[dict] = field(default_factory=list)
    nodes: list[int] = field(default_factory=list)  # every node the selections cover, document order
    notes: str = ""
    finished: bool = False
    reason: str = ""
    turns: int = 0
    tool_calls: list = field(default_factory=list)
    messages: list = field(default_factory=list)

    def summary(self, graph: RegGraph) -> dict:
        content = [i for i in self.nodes if graph.is_content(i)]
        return {"regulation": self.reg, "finished": self.finished, "reason": self.reason, "turns": self.turns,
                "selections": [{k: v for k, v in s.items() if k not in ("idx", "exclude_idx")} for s in self.selections],
                "notes": self.notes, "nodes": len(self.nodes), "provisions": len(content),
                "tokens": graph.tokens_of(sum(len(graph.text[i]) for i in self.nodes)),
                "tool_calls": [name for name, _ in self.tool_calls]}


def first_message(graph: RegGraph, profile_md: str) -> str:
    provisions = sum(1 for n in graph.nodes if n.kind in ("para", "table"))
    return (f"Regulation: {graph.reg} - {graph.title} (version {graph.version}, {graph.doc.pages} pages, {provisions} provisions)\n\n"
            f"Product profile:\n{profile_md}\n\n"
            f"Outline of the regulation (label | start of the text | pages | size). Leaves are not listed; read them with read_node:\n"
            f"{graph.outline()}\n\n"
            "Select the parts of this regulation the product has to meet, then call select_sections.")


def walk(llm: LLM, graph: RegGraph, profile_md: str, settings: Settings) -> WalkResult:
    tools = WalkerTools(graph)
    loop = llm.run_tools(stage="sections", label=graph.reg, system=SYSTEM, first_user=first_message(graph, profile_md), tools=tools.schemas,
                         handle=tools.handle, done=lambda: tools.done, max_turns=settings.walk_turns,
                         nudge="You have not submitted yet. Call select_sections now with the parts you found.")
    result = WalkResult(graph.reg, finished=loop.finished, reason=loop.reason, turns=loop.turns, tool_calls=tools.calls, messages=loop.messages)
    if tools.selections is not None:
        result.selections = tools.selections
        result.nodes = expand(graph, tools.selections)
        result.notes = tools.notes
    return result


def transcript(messages: list[dict]) -> list[dict]:
    """The walk as a readable log: thinking blocks (empty text, long signature) dropped, tool results shortened."""
    out = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": message["role"], "text": content[:3000]})
            continue
        blocks = []
        for block in content:
            kind = block.get("type")
            if kind == "text":
                blocks.append({"text": block["text"][:3000]})
            elif kind == "tool_use":
                blocks.append({"tool_use": block["name"], "input": block["input"]})
            elif kind == "tool_result":
                blocks.append({"tool_result": str(block.get("content"))[:600], "is_error": block.get("is_error", False)})
        out.append({"role": message["role"], "blocks": blocks})
    return out
