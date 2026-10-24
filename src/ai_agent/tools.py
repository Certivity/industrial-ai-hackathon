"""The tools of the section walk (spec/proposal.md A5): the agent reads a regulation through them and ends by calling select_sections.

Every tool is bound to one RegGraph. The agent names nodes by label; a label that does not exist is answered with the closest labels that
do, and select_sections refuses it. Nothing the agent writes becomes a page or a paragraph of the output: those come from the nodes it picked.
"""

from __future__ import annotations

from .llm import ToolOutcome
from .store import RegGraph

CATEGORIES = ("function", "general", "marking", "conformity", "test", "other")
MAX_READ_CHARS = 14_000


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}


def walker_tools() -> list[dict]:
    node = {"type": "string", "description": "A node label exactly as shown in the outline or in a tool result, e.g. 6.10.4.2 or Annex 4 Part 1."}
    return [
        _tool("get_toc", "List the sub-sections of a node, `depth` levels down, with page range and size. Call it to look inside a section "
                         "whose title is all you have seen, or without `node` for the top level (all sections and annexes).",
              {"node": {**node, "description": node["description"] + " Omit for the top level."},
               "depth": {"type": "integer", "description": "1 to 3 levels, default 1."}}),
        _tool("read_node", "Read the text of a node. With subtree=true you get the node and everything under it (cut at 14,000 characters; "
                           "when it is cut, read the children one by one). Call it whenever a title does not tell you whether a section applies, "
                           "and before you exclude part of a section.",
              {"node": node, "subtree": {"type": "boolean", "description": "Include everything below the node. Default false."}}, ["node"]),
        _tool("search", "Keyword search over the provisions of this regulation (each matched together with the titles above it). Call it for "
                        "something the product has but no section title names (a material, a technology, a test, a marking), and once more "
                        "before you submit to check that you did not miss a section.",
              {"query": {"type": "string"}, "top_k": {"type": "integer", "description": "1 to 15, default 8."},
               "within": {**node, "description": "Only search below this node. Optional."}}, ["query"]),
        _tool("follow_refs", "Show what a node points to (paragraphs and annexes), what points to it, and the other regulations it cites. "
                             "Call it when a provision hands its requirement to another paragraph or annex ('as specified in', 'in accordance with').",
              {"node": node}, ["node"]),
        _tool("select_sections", "Submit the parts of this regulation whose provisions the product has to meet. Call it once, when you have "
                                 "decided. Each selection is a node and everything below it, minus the nodes in `exclude`.",
              {"selections": {"type": "array", "items": {"type": "object", "properties": {
                  "node": node,
                  "category": {"type": "string", "enum": list(CATEGORIES), "description":
                               "function: named after a part or function of the product; general: applies to every device of the class "
                               "(general and electrical specifications); marking; conformity: conformity of production; test: test method or "
                               "annex that fixes a condition or pass criterion; other."},
                  "reason": {"type": "string", "description": "One sentence: which part, function, material or technology of the profile this covers."},
                  "exclude": {"type": "array", "items": {"type": "string"}, "description": "Nodes inside this selection to leave out. Optional."}},
                  "required": ["node", "category", "reason"], "additionalProperties": False}},
               "notes": {"type": "string", "description": "Anything the next reader should know: what you left out and why. Optional."}},
              ["selections"]),
    ]


def expand(graph: RegGraph, selections: list[dict]) -> list[int]:
    """The nodes a selection covers: every node below each selected one, minus the excluded subtrees, in document order."""
    chosen: set[int] = set()
    for item in selections:
        nodes = set(graph.subtree(item["idx"]))
        for i in item.get("exclude_idx", []):
            nodes -= set(graph.subtree(i))
        chosen |= nodes
    return sorted(chosen)


class WalkerTools:
    def __init__(self, graph: RegGraph):
        self.g = graph
        self.selections: list[dict] | None = None
        self.notes = ""
        self.schemas = walker_tools()
        self.calls: list[tuple[str, dict]] = []

    @property
    def done(self) -> bool:
        return self.selections is not None

    def _need(self, label) -> tuple[int | None, str]:
        i = self.g.resolve(label if isinstance(label, str) else None)
        if i is not None:
            return i, ""
        near = self.g.suggest(str(label)) if label else []
        return None, f"No node '{label}' in {self.g.reg}." + (f" Closest labels: {', '.join(near)}." if near else "")

    def handle(self, name: str, args: dict) -> ToolOutcome:
        self.calls.append((name, args))
        method = getattr(self, f"_{name}", None)
        if method is None:
            return ToolOutcome(f"Unknown tool '{name}'. Tools: get_toc, read_node, search, follow_refs, select_sections.", True)
        return method(args)

    # ------------------------------------------------------------------------------------------------------------------ tools
    def _get_toc(self, args: dict) -> ToolOutcome:
        depth = max(1, min(3, int(args.get("depth") or 1)))
        if args.get("node"):
            i, error = self._need(args["node"])
            if i is None:
                return ToolOutcome(error, True)
            return ToolOutcome(f"{self.g.line(i)}\n" + self.g.toc(i, depth))
        return ToolOutcome(self.g.toc(None, depth))

    def _read_node(self, args: dict) -> ToolOutcome:
        i, error = self._need(args.get("node"))
        if i is None:
            return ToolOutcome(error, True)
        if not args.get("subtree"):
            return ToolOutcome(f"Path: {self.g.nodes[i].path}\n" + self.g.render([i]))
        shown, used = [], 0
        ids = self.g.subtree(i)
        for j in ids:
            cost = len(self.g.text[j]) + 60
            if used + cost > MAX_READ_CHARS and shown:
                break
            shown.append(j)
            used += cost
        cut = len(ids) - len(shown)
        tail = f"\n[cut: {cut} more nodes below; read them with get_toc and read_node]" if cut else ""
        return ToolOutcome(f"Path: {self.g.nodes[i].path}\n" + self.g.render(shown) + tail)

    def _search(self, args: dict) -> ToolOutcome:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolOutcome("Give a query.", True)
        within = None
        if args.get("within"):
            within, error = self._need(args["within"])
            if within is None:
                return ToolOutcome(error, True)
        top_k = max(1, min(15, int(args.get("top_k") or 8)))
        rows = []
        direct = self.g.resolve(query)
        if direct is not None:
            rows.append(f"{self.g.ids[direct]} (exact label) | {self.g.nodes[direct].path[:110]}")
        for j, score in self.g.search(query, top_k, within):
            if j == direct:
                continue
            snippet = " ".join(self.g.text[j].split())[:170]
            rows.append(f"{self.g.ids[j]} | {self.g.nodes[j].path[:110]} | {self.g.nodes[j].page_start} | {snippet}")
        return ToolOutcome("\n".join(rows) if rows else "No provision matches; try other words.")

    def _follow_refs(self, args: dict) -> ToolOutcome:
        i, error = self._need(args.get("node"))
        if i is None:
            return ToolOutcome(error, True)
        refs = self.g.references(i)
        lines = []
        if refs["refers_to"]:
            lines.append("Refers to: " + "; ".join(f"{self.g.ids[j]} ({self.g.heading(j, 50)})" for j in refs["refers_to"][:12]))
        if refs["referred_by"]:
            lines.append("Referred to by: " + ", ".join(self.g.ids[j] for j in refs["referred_by"][:12]))
        if refs["cites"]:
            lines.append("Cites other regulations: " + ", ".join(refs["cites"]))
        return ToolOutcome("\n".join(lines) or "No references found in or to this node.")

    def _select_sections(self, args: dict) -> ToolOutcome:
        items = args.get("selections")
        if not isinstance(items, list) or not items:
            return ToolOutcome("`selections` must be a non-empty list.", True)
        checked, problems = [], []
        for k, item in enumerate(items):
            if not isinstance(item, dict):
                problems.append(f"selection {k}: not an object")
                continue
            i, error = self._need(item.get("node"))
            if i is None:
                problems.append(f"selection {k}: {error}")
                continue
            category = item.get("category")
            if category not in CATEGORIES:
                problems.append(f"selection {k} ({item.get('node')}): category must be one of {', '.join(CATEGORIES)}")
                continue
            excluded = []
            for label in item.get("exclude") or []:
                j, error = self._need(label)
                if j is None:
                    problems.append(f"selection {k} ({item.get('node')}) exclude: {error}")
                elif not self.g.contained(i, j) or j == i:
                    problems.append(f"selection {k} ({item.get('node')}) exclude: {label} is not below {item.get('node')}")
                else:
                    excluded.append(j)
            checked.append({"node": self.g.ids[i], "idx": i, "category": category, "reason": str(item.get("reason") or "").strip(),
                            "exclude": [self.g.ids[j] for j in excluded], "exclude_idx": excluded})
        if problems:
            return ToolOutcome("Nothing was submitted. Fix and call select_sections again:\n- " + "\n- ".join(problems), True)
        covered = expand(self.g, checked)
        content = sum(1 for j in covered if self.g.is_content(j))
        chars = sum(len(self.g.text[j]) for j in covered)
        self.selections = checked
        self.notes = str(args.get("notes") or "").strip()
        return ToolOutcome(f"Accepted: {len(checked)} selections covering {content} provisions (~{self.g.tokens_of(chars) / 1000:.1f}k tokens) "
                           f"of {sum(1 for n in self.g.nodes if n.kind in ('para', 'table'))}.")
