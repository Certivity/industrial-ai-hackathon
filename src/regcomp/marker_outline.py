"""Model fallback of the marker parser: a model supplies only the OUTLINE of a document, code checks it and cuts the text.

    from regcomp.marker_outline import parse_with_outline
    doc2 = parse_with_outline(path, doc, grids)      # None on failure; `doc` is the marker parser's own parse

The text layer of the PDF (doc.raws, margins already removed) is cut into windows of about 3 pages (under 9 KB, 1 page of overlap).
For each window a model is asked for the headings only: {"headings": [{"label", "page", "words", "level", "kind"}]}. Code then
  * finds `words` (whitespace-, case-, hyphen- and ligature-tolerant) at a line start on the stated page, at or after the previous
    accepted heading (a monotone cursor); a heading it cannot find is dropped and counted, one repeated in the overlap is merged;
  * cuts the text of every node out of doc.raws between two verified headings: nothing the model writes becomes node text;
  * gets the parent from `level` (a stack), the scope from the label's leading "<word> <id>" (Annex 4, Part B ...), the number from
    the label's trailing dotted number.
The prompt carries the stack of open headings from one window to the next. Replies are cached in runs/_generic_llm/ under
sha256(PDF bytes) and the hash of the prompt, so a second run makes no call. Only public regulation text may be sent: a path with a
`cases` directory is refused (None). No UNECE vocabulary is built in.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Callable

from regcomp.parse import Node, ParsedDocument, _attach_grids, _Line, _Raw

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "runs" / "_generic_llm"
WINDOW_PAGES = 3
WINDOW_BYTES = 9000
LINE_CLIP = 200  # characters of a line shown to the model
MIN_WORDS_CHARS = 3  # a heading whose words squash to fewer characters than this cannot be verified

SYSTEM = (
    "You read pages of a long technical or legal document and report its heading outline. Reply with ONLY a JSON object:\n"
    '{"headings":[{"label":"","page":0,"words":"","level":1,"kind":"para"}]}\n'
    "- label: the heading's number or identifier as printed (for example \"4.2.1\", \"Annex 3\", \"Article 5\", \"(a)\"); \"\" if none.\n"
    "- page: the page number from the '=== page N ===' line above the heading.\n"
    "- words: the first 8 words of the heading line exactly as printed, label included. Copy them; never paraphrase.\n"
    "- level: 1 for the top level, 2 for a heading directly inside a level-1 heading, and so on. Numbering depth and printed "
    "style give the level; use the open headings listed in the request to continue the hierarchy across windows.\n"
    "- kind: \"scope\" for a container that opens a new numbering range or major division (annex, article, part, chapter, "
    "appendix and the like), otherwise \"para\" (a numbered paragraph or section heading).\n"
    "Report every numbered paragraph or section start and every container heading, in reading order. Skip the table of contents, "
    "running headers and footers, page numbers, table rows, figure captions and ordinary sentences. A line that begins with "
    "[b] is set in bold; the marker is not part of the text. If a page holds no heading return {\"headings\":[]}. "
    "Do not report anything you cannot see in the pages."
)

KEYWORD = re.compile(r"^([A-Za-z]+)\s+([0-9]+[A-Za-z]?|[IVXLC]+|[A-Z])(?![A-Za-z0-9])")
TRAILING_NUMBER = re.compile(r"(?:^|\s)(\d+(?:\.\d+)*)\.?\s*$")


# ------------------------------------------------------------------------------------------------------------------ text matching
def squash(text: str) -> str:
    """Letters and digits only, case folded, ligatures expanded: what two spellings of one heading have in common (hyphen wraps,
    spacing, 'ﬁ' against 'fi')."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text).casefold() if ch.isalnum())


def find_heading(raws: list[_Raw], after: int, page: int, words: str, span: int = 3) -> int | None:
    """Index of the first line after `after` on `page` that starts with `words` (the heading may wrap over up to `span` lines)."""
    want = squash(words)
    if len(want) < MIN_WORDS_CHARS:
        return None
    for i in range(after + 1, len(raws)):
        if raws[i].page < page:
            continue
        if raws[i].page > page:
            break
        have = ""
        for j in range(i, min(i + span, len(raws))):
            if raws[j].page != page:
                break
            have += squash(raws[j].text)
            if have.startswith(want):
                return i
            if not want.startswith(have):
                break
    return None


# ------------------------------------------------------------------------------------------------------------------ windows
def make_windows(raws: list[_Raw], pages: int, max_pages: int = WINDOW_PAGES, max_bytes: int = WINDOW_BYTES) -> list[tuple[int, int, str]]:
    """(first page, last page, text) of each window: up to `max_pages` pages and `max_bytes` bytes, the last page of a window being
    the first of the next."""
    by_page: dict[int, list[_Raw]] = {}
    for raw in raws:
        by_page.setdefault(raw.page, []).append(raw)
    numbers = sorted(by_page)

    def block(p: int) -> str:
        lines = [f"=== page {p} ==="]
        for raw in by_page[p]:
            lines.append(("[b] " if raw.bold else "") + raw.text[:LINE_CLIP])
        return "\n".join(lines)

    blocks = {p: block(p) for p in numbers}
    out, k = [], 0
    while k < len(numbers):
        end, size = k, len(blocks[numbers[k]].encode("utf-8"))
        while end + 1 < len(numbers) and end - k + 1 < max_pages and size + len(blocks[numbers[end + 1]].encode("utf-8")) + 1 <= max_bytes:
            end += 1
            size += len(blocks[numbers[end]].encode("utf-8")) + 1
        text = "\n".join(blocks[p] for p in numbers[k:end + 1])
        out.append((numbers[k], numbers[end], text[:max_bytes] if end == k else text))
        if end + 1 >= len(numbers):
            break
        k = end if end > k else k + 1
    return out


def stack_text(stack: list[dict]) -> str:
    if not stack:
        return "(none yet)"
    return "\n".join(f"level {h['level']}: {h['label'] or '-'} | {h['words']}" for h in stack)


def window_prompt(first: int, last: int, total: int, stack: list[dict], text: str) -> str:
    return (f"Open headings carried over from the previous window (outermost first):\n{stack_text(stack)}\n\n"
            f"Pages {first}-{last} of {total}. Report the headings that start in these pages.\n\n{text}")


# ------------------------------------------------------------------------------------------------------------------ cache and model
def read_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


def default_ask() -> Callable[[str, str], str]:
    """DeepSeek (LLM_* of .env) through eval/xprovider.py's request and reply helpers, thinking off, over eval/drift_cases.py's paced
    connection. The returned function has a .usage dict of its calls."""
    eval_dir = str(ROOT / "eval")
    if eval_dir not in sys.path:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), eval_dir]
    import drift_cases  # noqa: PLC0415  (heavy; only a live call needs it)

    provider = drift_cases.Provider(timeout=900.0)

    def ask(system: str, user: str) -> str:
        url, headers, body = provider.xp.request_for("llm", provider.model, system, user, None, thinking=False)
        answer = provider.post(url, headers, body)
        usage = answer.get("usage") or {}
        ask.usage["calls"] += 1
        ask.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        ask.usage["completion_tokens"] += usage.get("completion_tokens", 0)
        return provider.xp.reply_text("llm", answer)

    ask.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    return ask


def _cached_ask(ask, system: str, user: str, pdf_hash: str, cache_dir: Path) -> tuple[str | None, bool]:
    """(reply, from_cache). A reply is cached only once it parses as JSON."""
    key = hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()[:24]
    file = cache_dir / f"{pdf_hash[:24]}-{key}.json"
    if file.is_file():
        try:
            return json.loads(file.read_text(encoding="utf-8"))["reply"], True
        except (OSError, ValueError, KeyError):
            pass
    reply = ask(system, user)
    try:
        read_json(reply)
    except ValueError:
        return reply, False
    cache_dir.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"reply": reply}, ensure_ascii=False), encoding="utf-8")
    return reply, False


# ------------------------------------------------------------------------------------------------------------------ outline
def _clean(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    try:
        page = int(item.get("page"))
        level = max(1, int(item.get("level", 1)))
    except (TypeError, ValueError):
        return None
    words = " ".join(str(item.get("words", "")).split())
    if not words:
        return None
    kind = "scope" if str(item.get("kind", "para")).strip().lower() == "scope" else "para"
    return {"label": " ".join(str(item.get("label", "") or "").split()), "page": page, "words": words, "level": level, "kind": kind}


def _scope_piece(label: str) -> tuple[str, str] | None:
    """('Annex', 'Annex 4') from a label that opens '<word> <id>', else None."""
    m = KEYWORD.match(label)
    return (m.group(1).lower(), f"{m.group(1)} {m.group(2)}") if m else None


def collect_outline(raws: list[_Raw], windows: list[tuple[int, int, str]], total: int, reply_of: Callable[[str], str | None],
                    stats: dict) -> list[dict]:
    """Ask for each window and verify the answers. Returns the accepted headings in document order, each with its line index
    ("line"), its effective level and its parent (index in the returned list, -1 for none)."""
    accepted: list[dict] = []
    stack: list[int] = []  # indexes in `accepted` of the open headings, outermost first
    seen: set[tuple[int, str]] = set()
    cursor = -1
    for first, last, text in windows:
        shown = [{"level": accepted[i]["level"], "label": accepted[i]["label"], "words": accepted[i]["words"][:60]} for i in stack]
        reply = reply_of(window_prompt(first, last, total, shown, text))
        try:
            items = read_json(reply)["headings"] if reply else []
        except (ValueError, KeyError, TypeError):
            stats["bad_replies"] += 1
            continue
        if not isinstance(items, list):
            stats["bad_replies"] += 1
            continue
        for item in (_clean(x) for x in items):
            stats["headings_returned"] += 1
            if item is None:
                stats["dropped"] += 1
                continue
            key = (item["page"], squash(item["words"])[:40])
            if key in seen:
                stats["duplicates"] += 1
                continue
            at = find_heading(raws, cursor, item["page"], item["words"])
            if at is None:
                stats["dropped"] += 1
                continue
            seen.add(key)
            while stack and accepted[stack[-1]]["level"] >= item["level"]:
                stack.pop()
            item.update(line=at, level=len(stack) + 1, parent=stack[-1] if stack else -1)
            accepted.append(item)
            stack.append(len(accepted) - 1)
            cursor = at
            stats["verified"] += 1
    return accepted


def build_document(path: Path, doc: ParsedDocument, outline: list[dict], grids: bool) -> ParsedDocument:
    """Cut doc.raws between the verified headings into nodes and link the tree."""
    raws = doc.raws
    out = ParsedDocument(path=Path(path), pages=doc.pages)
    for name in ("footers", "footer_mismatches", "image_pages", "body_size"):
        setattr(out, name, getattr(doc, name))
    out.raws = raws
    starts = {h["line"]: k for k, h in enumerate(outline)}
    scope_of: list[str] = []  # the scope string in force at each outline entry's children
    for k, h in enumerate(outline):
        inherited = scope_of[h["parent"]] if h["parent"] >= 0 else ""
        piece = _scope_piece(h["label"]) if h["kind"] == "scope" else None
        if piece:
            h["scope"], h["node_kind"], h["label_out"] = (inherited + " " + piece[1]).strip(), piece[0], piece[1]
        else:
            h["scope"], h["node_kind"], h["label_out"] = inherited, "scope" if h["kind"] == "scope" else "para", h["label"]
        scope_of.append(h["scope"])
    out.front_chars = sum(len(r.text) for r in raws[:outline[0]["line"]]) if outline else sum(len(r.text) for r in raws)
    lines: list[_Line] = []
    owners, slots = [-1] * len(raws), [-1] * len(raws)
    holder = -1
    for i, raw in enumerate(raws):
        k = starts.get(i)
        if k is not None:
            h = outline[k]
            m = TRAILING_NUMBER.search(h["label"]) if h["kind"] == "para" else None
            num = tuple(int(x) for x in m.group(1).split(".")) if m else ()
            if h["kind"] == "para":
                label = (h["scope"] + " " if h["scope"] else "") + ".".join(map(str, num)) if num else h["label_out"] or h["words"]
                node = Node("para", label, h["scope"], num, raw.page, raw.page, [raw.text], [raw.page], note=[0])
            else:
                node = Node(h["node_kind"], h["label_out"] or h["words"], h["scope"], (), raw.page, raw.page, [raw.text], [raw.page], note=[0])
            out.nodes.append(node)
            holder = len(out.nodes) - 1
            if holder != k:  # indexes agree: one node per outline entry, in order
                raise RuntimeError("outline and nodes out of step")
        elif holder >= 0:
            node = out.nodes[holder]
            node.text.append(raw.text)
            node.pages.append(raw.page)
            node.note.append(0)
            node.page_end = raw.page
        owners[i] = holder
        slots[i] = len(out.nodes[holder].text) - 1 if holder >= 0 else -1
        lines.append(_Line(i, raw.page, raw.text, raw.bold, raw.size, 0, None, raw.bbox))
    for k, h in enumerate(outline):
        out.nodes[k].parent = h["parent"]
        if h["parent"] >= 0:
            out.nodes[h["parent"]].children.append(k)
    for n in out.nodes:
        chain, up = [], n.parent
        while up >= 0:
            chain.append(out.nodes[up].title(60))
            up = out.nodes[up].parent
        n.path = " › ".join([*reversed(chain), n.title(60)])
    if grids:
        import pymupdf
        _attach_grids(pymupdf.open(path), lines, owners, slots, out)
    return out


def parse_with_outline(path, doc: ParsedDocument, grids: bool = True, ask: Callable[[str, str], str] | None = None,
                       cache_dir: Path | None = None) -> ParsedDocument | None:
    """The marker parse `doc` redone from a model's outline. None when the path is under cases/, the model is unreachable, or no
    heading survives verification. `ask(system, user) -> reply text` is injectable (default DeepSeek); `cache_dir` defaults to
    runs/_generic_llm/."""
    path = Path(path)
    if "cases" in (part.lower() for part in path.resolve().parts):
        print(f"marker_outline: refusing {path}: only public regulation text may be sent to a model", file=sys.stderr)
        return None
    raws = getattr(doc, "raws", None)
    if not raws:
        return None
    pdf_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
    stats = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0, "headings_returned": 0, "verified": 0,
             "dropped": 0, "duplicates": 0, "bad_replies": 0, "windows": 0}
    live = ask
    model_ask = None

    def reply_of(user: str) -> str | None:
        nonlocal live, model_ask
        stats["windows"] += 1
        key = hashlib.sha256((SYSTEM + "\x00" + user).encode("utf-8")).hexdigest()[:24]
        if not (cache_dir / f"{pdf_hash[:24]}-{key}.json").is_file() and live is None:
            live = model_ask = default_ask()
        try:
            reply, cached = _cached_ask(live or (lambda s, u: "{}"), SYSTEM, user, pdf_hash, cache_dir)
        except (SystemExit, Exception) as error:  # an unreachable or failing model must not cost the parse
            print(f"marker_outline: model call failed: {error!r}"[:300], file=sys.stderr)
            return None
        stats["cache_hits" if cached else "calls"] += 1
        return reply

    windows = make_windows(raws, doc.pages)
    outline = collect_outline(raws, windows, doc.pages, reply_of, stats)
    usage = getattr(model_ask or live, "usage", None)
    if usage:
        stats["prompt_tokens"], stats["completion_tokens"] = usage["prompt_tokens"], usage["completion_tokens"]
    if not outline:
        return None
    out = build_document(path, doc, outline, grids)
    out.induction = dict(getattr(doc, "induction", None) or {}, fallback=True, outline=stats)
    return out
