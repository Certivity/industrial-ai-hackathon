"""The drift agent (README.md section 3, spec/proposal.md B1 and B3): the requirements derived from an old version of a regulation, and the
new version, in; which requirements are modified, removed or have to be added, and why, out.

Two parts:

  * `align` pairs the content nodes (paragraphs and tables) of the two versions without a model: the same label with the same text hash
    is SAME, the same hash under another label is RENUMBERED, similar text is MODIFIED, the rest is REMOVED or ADDED. A page shift, a
    renumbering and a re-flowed layout never change a hash (regcomp.parse.Node.text_hash), so they cost nothing and are never flagged.
  * `run_drift` sends only the changed nodes to the model: one call per MODIFIED node judges each requirement on it (modified, unchanged,
    removed) and rewrites the modified ones; one call per group of ADDED nodes lists the new obligations. The `reason` strings are built in
    code, in the format of the example (subgoal/dev): "Paragraph 5.1.4 of UN R175 was amended in version 1.0.0: 'a' became 'b'; 'c' was added."
"""

from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.sparse import csr_matrix

from regcomp.parse import NUMBER_PREFIX, ParsedDocument, join_lines

from .config import DEFAULT_EFFORT, Settings
from .llm import LLM
from .store import BM25, _parser, label_key, words

CONTENT = ("para", "table")
SAME, RENUMBERED, MODIFIED, REMOVED, ADDED = "SAME", "RENUMBERED", "MODIFIED", "REMOVED", "ADDED"
PAIR_SIMILARITY = 0.6  # token similarity at which two paragraphs with different labels are one paragraph, edited
SAME_LABEL_SIMILARITY = 0.3  # ... and with the same label (a strong sign on its own)
LABEL_BONUS = 0.15  # added to the score of a pair with the same label when the pairs compete for the same node
PARENT_BONUS = 0.02  # ... and with the same parent label: breaks ties between identical paragraphs ("Deleted", "Reserved")


# ----------------------------------------------------------------------------------------------------------------------- a version
class Version:
    """One parsed version of a regulation: the content nodes with a unique id (the label, a repeat gets a suffix), text and parent."""

    def __init__(self, doc: ParsedDocument, regulation: str = "", label: str = ""):
        self.doc, self.regulation, self.label = doc, regulation, label
        self.nodes = doc.nodes
        seen: dict[str, int] = defaultdict(int)
        self.ids: list[str] = []
        for n in self.nodes:
            base = n.label or f"node p{n.page_start}"
            seen[base] += 1
            self.ids.append(base if seen[base] == 1 else f"{base} [{seen[base]}]")
        self.content = [i for i, n in enumerate(self.nodes) if n.kind in CONTENT and (n.body or "").strip()]
        self.by_key: dict[str, int] = {}
        for i in self.content:
            self.by_key.setdefault(label_key(self.ids[i]), i)
        self.hashes = {i: self.nodes[i].text_hash for i in self.content}
        self.texts = {i: self.nodes[i].model_text or self.nodes[i].body for i in self.content}
        self._bm25: BM25 | None = None

    @classmethod
    def from_pdf(cls, path: str | Path, regulation: str = "", label: str = "") -> "Version":
        return cls(_parser()(path, grids=True), regulation, label)

    def key(self, i: int) -> str:
        return label_key(self.ids[i])

    def parent_key(self, i: int) -> str:
        p = getattr(self.nodes[i], "parent", -1)
        return label_key(self.ids[p]) if 0 <= p < len(self.nodes) else ""

    def top_section(self, i: int) -> str:
        """The first number of the label ('5' for 5.1.4), or the scope ('Annex 4') of a paragraph in an annex."""
        n = self.nodes[i]
        if n.scope:
            return label_key(n.scope)
        m = re.match(r"\d+", n.label or "")
        return m.group(0) if m else ""

    def plain(self, i: int) -> str:
        """The words of node i without its own number, on one line: what the diff compares."""
        return words_line(self.nodes[i])

    def search(self, query: str, top_k: int = 5, among: list[int] | None = None) -> list[tuple[int, float]]:
        if self._bm25 is None:
            self._bm25 = BM25([words(getattr(self.nodes[i], "path", "") + " " + self.texts[i]) for i in self.content])
        scores = self._bm25.scores(words(query))
        pool = None if among is None else set(among)
        ranked = sorted(((self.content[k], s) for k, s in scores.items() if pool is None or self.content[k] in pool), key=lambda t: -t[1])
        return ranked[:top_k]


def words_line(node) -> str:
    """The text of a node as one line, its own number cut off (the first line only: 'NUMBER_PREFIX' is how text_hash does it)."""
    lines = list(node.text)
    if lines:
        lines[0] = NUMBER_PREFIX.sub("", lines[0])
    return " ".join(join_lines(lines).split())


# ----------------------------------------------------------------------------------------------------------------------- alignment
@dataclass
class Match:
    kind: str  # SAME | RENUMBERED | MODIFIED | REMOVED | ADDED
    old: int | None  # index of the node in the old version
    new: int | None
    sim: float = 0.0
    renumbered: bool = False  # the label changed (always true for RENUMBERED, and for a MODIFIED node that moved)

    def as_dict(self, old: Version, new: Version) -> dict:
        return {"kind": self.kind, "old": old.ids[self.old] if self.old is not None else None,
                "new": new.ids[self.new] if self.new is not None else None, "sim": round(self.sim, 3), "renumbered": self.renumbered}


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _jaccard(old_toks: list[list[str]], new_toks: list[list[str]]) -> np.ndarray:
    vocab: dict[str, int] = {}
    for toks in old_toks + new_toks:
        for t in set(toks):
            vocab.setdefault(t, len(vocab))

    def matrix(rows: list[list[str]]) -> csr_matrix:
        r, c = [], []
        for k, toks in enumerate(rows):
            for t in set(toks):
                r.append(k)
                c.append(vocab[t])
        return csr_matrix((np.ones(len(r), dtype=np.float32), (r, c)), shape=(len(rows), max(1, len(vocab))))

    a, b = matrix(old_toks), matrix(new_toks)
    inter = (a @ b.T).toarray()
    size_a = np.asarray(a.sum(axis=1)).reshape(-1, 1)
    size_b = np.asarray(b.sum(axis=1)).reshape(1, -1)
    return inter / np.maximum(1.0, size_a + size_b - inter)


def align(old: Version, new: Version) -> list[Match]:
    """Pair the content nodes of two versions. SAME (label and hash) first; then every other old node competes with every other new node:
    the pair score is the token similarity plus a bonus for the same label and for the same parent, a pair is allowed when the similarity
    reaches PAIR_SIMILARITY (SAME_LABEL_SIMILARITY with the same label, any similarity for equal hashes), and scipy's linear_sum_assignment
    (Hungarian) picks the best allowed one-to-one pairing. What is left is REMOVED (old) and ADDED (new)."""
    out: list[Match] = []
    new_by_key = {new.key(j): j for j in reversed(new.content)}  # the first node of a label wins
    taken_new: set[int] = set()
    left_old: list[int] = []
    for i in old.content:
        j = new_by_key.get(old.key(i))
        if j is not None and j not in taken_new and new.hashes[j] == old.hashes[i] and old.key(i) == new.key(j):
            out.append(Match(SAME, i, j, 1.0))
            taken_new.add(j)
        else:
            left_old.append(i)
    left_new = [j for j in new.content if j not in taken_new]
    if left_old and left_new:
        o_tok = [tokens(old.plain(i)) for i in left_old]
        n_tok = [tokens(new.plain(j)) for j in left_new]
        jac = _jaccard(o_tok, n_tok)
        score = np.full(jac.shape, -1.0)
        sims = np.zeros(jac.shape)
        for a, i in enumerate(left_old):
            for b, j in enumerate(left_new):
                same_hash = old.hashes[i] == new.hashes[j]
                same_label = old.key(i) == new.key(j)
                if not same_hash and jac[a, b] < 0.2:
                    continue
                s = 1.0 if same_hash else similarity(o_tok[a], n_tok[b])
                sims[a, b] = s
                if same_hash or s >= PAIR_SIMILARITY or (same_label and s >= SAME_LABEL_SIMILARITY):
                    bonus = (LABEL_BONUS if same_label else 0.0) + (PARENT_BONUS if old.parent_key(i) == new.parent_key(j) else 0.0)
                    score[a, b] = s + bonus
        rows, cols = linear_sum_assignment(-score)
        used_old: set[int] = set()
        for a, b in zip(rows, cols):
            if score[a, b] < 0:
                continue
            i, j = left_old[a], left_new[b]
            used_old.add(a)
            taken_new.add(j)
            moved = old.key(i) != new.key(j)
            same_hash = old.hashes[i] == new.hashes[j]
            kind = RENUMBERED if same_hash else MODIFIED
            out.append(Match(kind, i, j, float(sims[a, b]), renumbered=moved))
        left_old = [i for a, i in enumerate(left_old) if a not in used_old]
        left_new = [j for j in left_new if j not in taken_new]
    out += [Match(REMOVED, i, None) for i in left_old]
    out += [Match(ADDED, None, j) for j in left_new]
    # a same-hash pair under the same label can only be SAME, but a duplicate label made it through the pool: report it as SAME
    for m in out:
        if m.kind == RENUMBERED and not m.renumbered:
            m.kind = SAME
    return sorted(out, key=lambda m: (m.old if m.old is not None else 10**9, m.new if m.new is not None else 10**9))


def counts(matches: list[Match]) -> dict[str, int]:
    c = {k: 0 for k in (SAME, RENUMBERED, MODIFIED, REMOVED, ADDED)}
    for m in matches:
        c[m.kind] += 1
    return c


# ----------------------------------------------------------------------------------------------------------------------- the word diff
@dataclass
class Edit:
    op: str  # replace | insert | delete
    old: str
    new: str

    def phrase(self) -> str:
        return self.old or self.new


def word_edits(old_text: str, new_text: str, merge_gap: int = 2) -> list[Edit]:
    """The edits that turn old_text into new_text, on words. Edits separated by at most `merge_gap` unchanged words are one edit, so
    'standstill.' becoming 'standstill and, as relevant, while creeping.' is one phrase and not a scatter of words."""
    a, b = old_text.split(), new_text.split()
    runs: list[tuple] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            runs.append(("equal", i1, i2, j1, j2))
        elif len(runs) >= 2 and runs[-1][0] == "equal" and runs[-1][2] - runs[-1][1] <= merge_gap and runs[-2][0] == "change":
            runs[-2:] = [("change", runs[-2][1], i2, runs[-2][3], j2)]  # a change, a short unchanged run and the next change
        else:
            runs.append(("change", i1, i2, j1, j2))
    edits = []
    for tag, i1, i2, j1, j2 in runs:
        if tag == "change":
            x, y = " ".join(a[i1:i2]), " ".join(b[j1:j2])
            edits.append(Edit("replace" if x and y else "insert" if y else "delete", x, y))
    return edits


APPENDED_MODES = ("added", "modified", "both")


def _bare(word: str) -> str:
    return word.strip(".,;:()[]\"'")


def appended_sentences(old_text: str, new_text: str) -> list[str]:
    """The whole sentences a new paragraph adds to an old one that is otherwise kept (words equal, edge punctuation aside), or [] when
    the paragraph changed in any other way. Deterministic, from the word diff: every non-equal run must be an insertion that starts a
    sentence (the paragraph start, or after a word ending in '.') with a capital letter and ends with '.'."""
    a, b = old_text.split(), new_text.split()
    if not a or len(b) <= len(a):
        return []
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [_bare(w) for w in a], [_bare(w) for w in b], autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag != "insert":
            return []
        chunk = b[j1:j2]
        if (j1 > 0 and not b[j1 - 1].endswith(".")) or not chunk[0][:1].isupper() or not chunk[-1].endswith("."):
            return []
        out.append(" ".join(chunk))
    return out


QUOTE_LIMIT = 170


def _clip(text: str, limit: int = QUOTE_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def edit_clause(e: Edit) -> str:
    if e.op == "replace":
        return f"'{_clip(e.old)}' became '{_clip(e.new)}'"
    if e.op == "insert":
        return f"'{_clip(e.new)}' was added"
    return f"'{_clip(e.old)}' was removed"


def modified_reason(regulation: str, version: str, label: str, former: str | None, old_text: str, new_text: str, max_edits: int = 8) -> str:
    """The `reason` of a modified requirement, in the example's format."""
    edits = word_edits(old_text, new_text)
    head = f"Paragraph {label}" + (f" (formerly {former})" if former else "") + f" of {regulation} was amended in version {version}"
    if not edits:
        return head + "."
    clauses = [edit_clause(e) for e in edits[:max_edits]]
    if len(edits) > max_edits:
        clauses.append(f"{len(edits) - max_edits} further changes")
    return head + ": " + "; ".join(clauses) + "."


def removed_reason(regulation: str, version: str, label: str, text: str) -> str:
    return (f"Paragraph {label} of {regulation} was amended in version {version}; the provision '{_clip(' '.join(text.split()), 80)}' "
            f"no longer appears.")


def added_reason(regulation: str, version: str, label: str, text: str) -> str:
    return f"Paragraph {label} of {regulation} is new in version {version}: '{_clip(' '.join(text.split()), 100)}'."


def diff_summary(old_text: str, new_text: str) -> str:
    """The edits as numbered lines for a prompt."""
    edits = word_edits(old_text, new_text)
    return "\n".join(f"{k}. {edit_clause(e)}" for k, e in enumerate(edits, 1)) or "(no word differs)"


# ===================================================================================================================== the agent
# From here on: requirements -> old nodes, the model calls, the changes file. Nothing below reads a gold file.
MOVE_CHECK_BELOW = 0.95  # a MODIFIED node less similar than this is also shown the added paragraphs that resemble it
MAP_CONTAINMENT = 0.25  # share of a requirement's words found in the node its label names, below which the label is doubted


def containment(text: str, node_text: str) -> float:
    a = set(words(text))
    return len(a & set(words(node_text))) / len(a) if a else 0.0


def map_requirements(old: Version, requirements: list[dict]) -> dict[str, dict]:
    """The old node of every requirement: the node its source paragraph names, or (when no node has that label, or its words hardly
    contain the requirement's) the node whose text matches the requirement best (BM25 over the whole old version)."""
    out: dict[str, dict] = {}
    for r in requirements:
        src = r.get("source") or {}
        i = old.by_key.get(label_key(src.get("paragraph")))
        how = "label"
        if i is None or containment(r["text"], old.texts[i]) < MAP_CONTAINMENT:
            hits = old.search(r["text"], 3)
            if hits and (i is None or containment(r["text"], old.texts[hits[0][0]]) >= 0.5):
                i, how = hits[0][0], "text" if i is None else "text (label doubted)"
        out[r["id"]] = {"node": i, "by": how if i is not None else "unmapped"}
    return out


CHANGE_RULES = """A requirement is MODIFIED when its content changed: a different condition, number, limit, scope or exception, a sentence or clause that belongs to it added or removed, a changed obligation. It is REMOVED when its content is gone from the new version. It is UNCHANGED, and you give it verdict "unchanged", when:
- only the paragraph number or the order of paragraphs changed, or a cross-reference number follows a renumbering;
- only spelling, hyphenation, capitalisation, punctuation, an abbreviation ("s" for "seconds"), a unit written another way ("per cent" for "%") or a typographical variant changed;
- a footnote was renumbered or re-worded without changing what the requirement demands;
- the change concerns another requirement of the same paragraph, or text the requirement does not carry (a heading, an added sub-title, a definition);
- the wording differs but the meaning is the same.
A false "modified" is costly: when the new text still demands exactly what the requirement demands, say "unchanged". When it is modified, `new_text` is the OLD requirement rewritten for the new version: the same style and scope (a standalone "X shall ..." sentence), keeping every part that did not change, with the change applied; `new_paragraph` is the label of the NEW paragraph where it now sits."""

JUDGE_SYSTEM = f"""You keep the engineering requirements derived from a UN Regulation up to date. The requirements were written from an OLD version; you get one OLD paragraph, the requirements derived from it, and what the NEW version has in its place: the matching new paragraph with a word-level diff, or, when the old paragraph has no counterpart (it was deleted, split or rewritten), candidate new paragraphs. Judge every requirement of the old paragraph.

{CHANGE_RULES}

For each requirement give: id, verdict (modified | unchanged | removed), new_text (empty unless modified), new_paragraph (empty unless modified), note (one short sentence on what changed or why it did not).
`new_obligations`: obligations that the NEW paragraph states and that no requirement of the old paragraph covers (a new sentence, a new list item, a new condition that is a requirement of its own), each a standalone "X shall ..." sentence with the label of the new paragraph it comes from; an empty list when there is none. Do not list what a modified requirement already carries."""

JUDGE_SCHEMA = {"type": "object", "properties": {
    "requirements": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "verdict": {"type": "string", "enum": ["modified", "unchanged", "removed"]},
        "new_text": {"type": "string"}, "new_paragraph": {"type": "string"}, "note": {"type": "string"}},
        "required": ["id", "verdict", "new_text", "new_paragraph", "note"], "additionalProperties": False}},
    "new_obligations": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string"}, "new_paragraph": {"type": "string"}}, "required": ["text", "new_paragraph"], "additionalProperties": False}}},
    "required": ["requirements", "new_obligations"], "additionalProperties": False}

ADDED_SYSTEM = """You keep the engineering requirements derived from a UN Regulation up to date. A newer version added paragraphs; you get them as <node id=... page=...> blocks, and the titles above them. List the engineering requirements the added paragraphs state, the way the experts wrote the existing ones (examples below, from the same regulation).

- One requirement is one subject and one constraint, with its condition: a standalone sentence "The <system> shall ...". Each independent constraint of a paragraph is a requirement of its own (one per sentence, one per list item that is a separate constraint; the lead-in's condition goes into each); an exception that follows a constraint belongs to it. Keep the paragraph's words, numbers, units and cross-references; add nothing.
- Product requirements only: design, performance, marking, installation, test procedure and pass criteria, conformity of production. Not requirements: definitions, scope statements, headings, transitional provisions, the approval application and administrative procedure, forms, duties of the authority. A permission that sets a condition on the product ("tests may be conducted ..., whilst ...") is written as the obligation it implies.
- Give an entry for EVERY node, in order: its requirements, or an empty list. A requirement carries a `quote`: the shortest verbatim span of the node that holds it.

Examples of the existing requirements of this regulation:
{examples}"""

ADDED_SCHEMA = {"type": "object", "properties": {"nodes": {"type": "array", "items": {"type": "object", "properties": {
    "node": {"type": "string"}, "requirements": {"type": "array", "items": {"type": "object", "properties": {
        "quote": {"type": "string"}, "text": {"type": "string"}}, "required": ["quote", "text"], "additionalProperties": False}}},
    "required": ["node", "requirements"], "additionalProperties": False}}}, "required": ["nodes"], "additionalProperties": False}


def render_node(v: Version, i: int, role: str, extra: str = "") -> str:
    n = v.nodes[i]
    page = n.page_start if n.page_start == n.page_end else f"{n.page_start}-{n.page_end}"
    return f'<{role} id="{v.ids[i]}" page="{page}"{extra}>\n{v.texts[i]}\n</{role}>'


def candidates_for(new: Version, matches: list[Match], old: Version, i: int, reqs: list[dict], top_k: int = 6) -> list[int]:
    """New paragraphs where the content of old node i may have gone: the best BM25 hits among the added and the modified new nodes."""
    pool = [m.new for m in matches if m.kind in (ADDED, MODIFIED)]
    query = old.texts[i][:1500] + " " + " ".join(r["text"] for r in reqs)
    return [j for j, s in new.search(query, top_k, among=pool) if s > 0]


def judge_node(llm, reg: str, old: Version, new: Version, m: Match, reqs: list[dict], cands: list[int]) -> dict:
    i = m.old
    parts = [f"Regulation {reg}: old version {old.label}, new version {new.label}.", "", render_node(old, i, "old_paragraph"), "",
             "Requirements derived from the old paragraph:", *[f'{r["id"]}: {r["text"]}' for r in reqs], ""]
    if m.kind == MODIFIED:
        parts += [render_node(new, m.new, "new_paragraph", ' renumbered="true"' if m.renumbered else ""), "", "Word diff, old -> new:",
                  diff_summary(old.plain(i), new.plain(m.new))[:4000], ""]
    if cands:
        parts += [("Part of the old paragraph may have moved out of it, into these new paragraphs (a requirement whose content stands in one of them, or in the new paragraph above, is not removed):" if m.kind == MODIFIED
                   else "The old paragraph has no counterpart in the new version; its content may have moved into one of these new paragraphs:")]
        parts += [render_node(new, j, "candidate_paragraph") for j in cands]
    elif m.kind == REMOVED:
        parts += ["The old paragraph has no counterpart in the new version and no new paragraph resembles it."]
    parts += ["", "Judge each requirement."]
    return llm.complete_json(stage="drift_judge", label=old.ids[i], system=JUDGE_SYSTEM, user="\n".join(parts), schema=JUDGE_SCHEMA,
                             effort=DEFAULT_EFFORT["judge"], max_tokens=16_000)


def grounded(quote: str, text: str) -> bool:
    q, t = tokens(quote), tokens(text)
    if len(q) < 3:
        return False
    n = len(q)
    if any(t[k:k + n] == q for k in range(len(t) - n + 1)):
        return True
    sm = difflib.SequenceMatcher(None, t, q, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks() if b.size >= 2) / n >= 0.85


def extract_added(llm, reg: str, new: Version, nodes: list[int], examples: list[str], chunk_chars: int = 20_000) -> tuple[list[dict], list[str]]:
    """Requirements of the added nodes: one entry per node from the model, each checked by its quote against the node's own text."""
    chunks, current, size = [], [], 0
    for j in nodes:
        n = len(new.texts[j]) + 120
        if current and size + n > chunk_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(j)
        size += n
    if current:
        chunks.append(current)
    system = ADDED_SYSTEM.replace("{examples}", "\n".join(f"- {e}" for e in examples) or "(none)")

    def one(item):
        k, chunk = item
        ctx = list(dict.fromkeys(getattr(new.nodes[j], "path", "") for j in chunk))
        body = (f"Regulation {reg}, version {new.label}. Titles above the added paragraphs:\n" + "\n".join(f"- {c}" for c in ctx if c) + "\n\n"
                + "\n".join(render_node(new, j, "node") for j in chunk) + f"\n\nGive an entry for each of the {len(chunk)} nodes, in order.")
        return llm.complete_json(stage="drift_added", label=f"chunk {k}", system=system, user=body, schema=ADDED_SCHEMA,
                                 effort=DEFAULT_EFFORT["obligations"], max_tokens=32_000)

    with ThreadPoolExecutor(max_workers=max(1, llm.s.workers)) as pool:
        answers = list(pool.map(one, enumerate(chunks, 1)))
    out, log = [], []
    for chunk, answer in zip(chunks, answers):
        for entry in answer["nodes"]:
            j = new.by_key.get(label_key(entry["node"]))
            if j is None or j not in chunk:
                log.append(f"entry for unknown node {entry['node']!r} ignored")
                continue
            for item in entry["requirements"]:
                text = " ".join(item["text"].split())
                if not text:
                    continue
                if not grounded(item["quote"], new.texts[j]):
                    log.append(f"{new.ids[j]}: dropped, the quote is not in the node: {item['quote'][:60]!r}")
                    continue
                out.append({"node": j, "text": text})
    return out, log


@dataclass
class DriftResult:
    changes: dict
    trace: dict
    cost: dict


def regulation_of(requirements: list[dict], given: str | None) -> str:
    if given:
        return given
    names = [r["source"].get("regulation") for r in requirements if r.get("source", {}).get("regulation")]
    return max(set(names), key=names.count) if names else "the regulation"


def run_drift(old: Version, new: Version, requirements: list[dict], settings: Settings, case_id: str, regulation: str | None = None,
              llm: LLM | None = None, log=lambda m: None, new_in_modified: bool = True, appended: str = "added") -> DriftResult:
    if appended not in APPENDED_MODES:
        raise ValueError(f"appended must be one of {APPENDED_MODES}")
    reg = regulation_of(requirements, regulation)
    llm = llm or LLM(settings, log=log)
    matches = align(old, new)
    log(f"[align] {reg}: {len(old.content)} old nodes, {len(new.content)} new, {counts(matches)}")
    mapping = map_requirements(old, requirements)
    by_node: dict[int, list[dict]] = defaultdict(list)
    for r in requirements:
        node = mapping[r["id"]]["node"]
        if node is not None:
            by_node[node].append(r)
    match_of_old = {m.old: m for m in matches if m.old is not None}
    changes: list[dict] = []
    trace: dict = {"regulation": reg, "old_version": old.label, "new_version": new.label, "alignment": counts(matches),
                   "unmapped_requirements": [r["id"] for r in requirements if mapping[r["id"]]["node"] is None],
                   "mapped_by_text": [r["id"] for r in requirements if mapping[r["id"]]["by"].startswith("text")],
                   "nodes_judged": [], "gated_unchanged": [], "added_log": [], "appended_mode": appended, "appended_nodes": []}
    homes: set[int] = set()  # new nodes that now carry an old requirement: they are not "added" as well
    new_obligations: list[dict] = []

    # 1. the old nodes that need a judge: changed nodes that carry requirements
    jobs = []
    for i, reqs in by_node.items():
        m = match_of_old.get(i)
        if m is None or m.kind in (SAME, RENUMBERED):
            continue
        if m.kind == MODIFIED and tokens(old.plain(i)) == tokens(new.plain(m.new)):
            trace["gated_unchanged"].append({"old": old.ids[i], "why": "only punctuation or case differs"})
            continue
        cands = [j for j in candidates_for(new, matches, old, i, reqs) if j != m.new]  # where a sentence that left the paragraph may have gone
        if m.kind == MODIFIED:
            cands = cands[:3] if m.sim < MOVE_CHECK_BELOW else []  # a near-identical paragraph has not lost a requirement elsewhere
        jobs.append((i, m, reqs, cands))
    jobs.sort(key=lambda t: t[0])

    def run(job):
        i, m, reqs, cands = job
        if m.kind == REMOVED and not cands:  # nothing in the new version resembles it: no model call
            return {"requirements": [{"id": r["id"], "verdict": "removed", "new_text": "", "new_paragraph": "",
                                      "note": "no counterpart and no similar paragraph"} for r in reqs], "new_obligations": []}
        return judge_node(llm, reg, old, new, m, reqs, cands)

    with ThreadPoolExecutor(max_workers=max(1, settings.workers)) as pool:
        answers = list(pool.map(run, jobs))

    # 2. verdicts become changes, with the reasons built from the diff
    for (i, m, reqs, cands), answer in zip(jobs, answers):
        verdicts = {a["id"]: a for a in answer["requirements"]}
        record = {"old": old.ids[i], "kind": m.kind, "sim": round(m.sim, 3), "candidates": [new.ids[j] for j in cands], "verdicts": {}}
        tail = appended_sentences(old.plain(i), new.plain(m.new)) if (m.kind == MODIFIED and appended != "added") else []
        if tail:
            trace["appended_nodes"].append({"old": old.ids[i], "new": new.ids[m.new], "sentences": tail})
        tail_text = " ".join(tail)
        for r in reqs:
            a = verdicts.get(r["id"])
            verdict = a["verdict"] if a else "unchanged"
            record["verdicts"][r["id"]] = {"verdict": verdict, "note": (a or {}).get("note", "")}
            if tail and verdict == "unchanged" and appended in ("modified", "both"):
                # a sentence appended to the paragraph: the requirement is modified (paragraph-level convention)
                a = {"new_text": r["text"], "new_paragraph": new.ids[m.new], "note": ""}
                verdict = "modified"
                record["verdicts"][r["id"]]["verdict"] = "modified (appended sentence)"
            if verdict == "removed":
                changes.append({"requirement_id": r["id"], "change": "removed", "reason": removed_reason(reg, new.label, old.ids[i], r["text"])})
            elif verdict == "modified":
                text = " ".join(a["new_text"].split())
                if tail and appended in ("modified", "both") and containment(tail_text, text) < 0.8:
                    text = f"{text} {tail_text}"  # the new sentence is part of the modified requirement
                j = new.by_key.get(label_key(a["new_paragraph"])) if a["new_paragraph"] else None
                if j is None and m.kind == MODIFIED:
                    j = m.new
                if not text or text == r["text"] or j is None:
                    record["verdicts"][r["id"]]["dropped"] = "no new wording or unknown new paragraph"
                    continue
                former = old.ids[i] if old.key(i) != new.key(j) else None
                homes.add(j)
                changes.append({"requirement_id": r["id"], "change": "modified", "new_text": text[:2000],
                                "reason": modified_reason(reg, new.label, new.ids[j], former, old.plain(i), new.plain(j)),
                                "source": {"page": new.nodes[j].page_start, "paragraph": new.ids[j]}})
        if tail and appended == "modified":
            answer = {**answer, "new_obligations": []}  # the sentence is in the modified requirements, not an item of its own
        if new_in_modified:
            for o in answer["new_obligations"]:
                j = new.by_key.get(label_key(o["new_paragraph"]))
                if j is None and m.kind == MODIFIED:
                    j = m.new
                text = " ".join(o["text"].split())
                if j is not None and text:
                    new_obligations.append({"node": j, "text": text, "appended": bool(tail)})
        if tail and appended == "both" and not any(o["appended"] and o["node"] == m.new for o in new_obligations):
            new_obligations.append({"node": m.new, "text": tail_text, "appended": True})  # the sentence itself, once
        trace["nodes_judged"].append(record)

    # 3. added: new nodes that carry no old requirement, inside the sections the old requirements cover
    covered = {old.top_section(i) for i in by_node}
    todo = [m.new for m in matches if m.kind == ADDED and m.new not in homes and new.top_section(m.new) in covered]
    trace["added_nodes"] = [new.ids[j] for j in todo]
    trace["added_nodes_outside_coverage"] = [new.ids[m.new] for m in matches if m.kind == ADDED and new.top_section(m.new) not in covered]
    examples = [f'paragraph {r["source"].get("paragraph")}: {r["text"][:300]}' for r in requirements[:: max(1, len(requirements) // 6)][:6]]
    found: list[dict] = []
    if todo:
        found, trace["added_log"] = extract_added(llm, reg, new, todo, examples)
    seen_text = [tokens(c["new_text"]) for c in changes if c["change"] == "modified"]
    n_modified = len(seen_text)
    for o in found + new_obligations:
        t = tokens(o["text"])
        if any(similarity(t, s) > 0.8 for s in seen_text[:n_modified] if not (o.get("appended") and appended == "both")) or                 any(similarity(t, s) > 0.8 for s in seen_text[n_modified:]):
            continue
        seen_text.append(t)
        j = o["node"]
        changes.append({"requirement_id": None, "change": "added", "new_text": o["text"][:2000],
                        "reason": added_reason(reg, new.label, new.ids[j], new.plain(j)),
                        "source": {"page": new.nodes[j].page_start, "paragraph": new.ids[j]}})
    order = {"modified": 0, "removed": 1, "added": 2}
    changes.sort(key=lambda c: (order[c["change"]], c.get("requirement_id") or "", c.get("source", {}).get("page", 0)))
    trace["counts"] = {k: sum(1 for c in changes if c["change"] == k) for k in order}
    return DriftResult({"team_id": settings.team_id, "case_id": case_id, "changes": changes}, trace, llm.ledger.summary())
