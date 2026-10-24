#!/usr/bin/env python3
"""Put the pipeline's questions to a model from another provider and score what comes back against ground truth.

Every gold set so far was written, and every pipeline step designed, with Claude. A second provider is the only way to tell how
much of a result is the task and how much is one model's habits. Commands (`python eval/xprovider.py <command> --help`):

  select CASE        the provider reads the case's spec.md and a catalogue of the regulations with their sections (what steps A4.2
                     and A4.3 of the proposal give a Claude model) and picks regulations and sections. CASE/expected.json is read
                     only after the answer is saved, to score it, and is never sent: the blind run of mapping-simulation.md section 7
  author --id ID --brief TEXT
                     the provider invents a product from a one-line brief, names the regulations that apply, then reads their
                     page text and writes requirements with page, paragraph and a verbatim quote: a new case in
                     spec/testing/cases/ID/. Its quotes are checked with `ground`
  agree CASE         the provider writes its own gold for an existing case (the regulations given) and the two golds are compared
                     at regulation, page and paragraph level: how far two writers of the same gold agree
  ground FILE        offline: check a provider's requirements against the raw page text of the PDFs and against our parse
  regrade [CASE ...] offline: ground the saved provider.json of cases again with the parser as it is now, and show how the verdicts
                     moved against the ground.json kept at the time (--write keeps them and rebuilds expected.json)
  score CASE FILE    offline: score a picks file ([{"regulation": "UN R48", "root": "6.10"}, ...]) against CASE/expected.json
  catalogue          offline: the size of what `select` sends

A command that would call a model prints what it would send and where, and stops unless --send is given. Keys are read from
OPENAI_API_KEY or GEMINI_API_KEY (GOOGLE_API_KEY) in the environment, or from a .env file in the repository root (git ignores it);
a dry run says whether one was found, and never prints it. --provider replay --reply FILE answers from a file instead, to try
the rest.

--provider llm is any OpenAI-compatible chat endpoint (DeepSeek, a local server), set by four lines of the .env file or the
environment: LLM_API_KEY, LLM_BASE_URL (e.g. https://api.deepseek.com), LLM_MODEL (what --model defaults to) and LLM_TIMEOUT_S
(seconds the connection may stay silent; --timeout overrides it; the other providers wait up to 1200). The call goes with
`thinking: disabled`; --thinking leaves the model's own default (DeepSeek: on).

What is sent: the case's spec.md (and exploded_view.png with --image), the catalogue (titles, the first lines of section 1 and the
section headings of the regulations in regulations/index.json), and for `author` and `agree` the page text of the chosen regulation
PDFs. The prompts are built from those and from nothing else; no expected.json is read before the answer is saved, and the only
thing `agree` takes from one is the names of the regulations. The exact prompt of every call is kept next to its reply. cases/ and
subgoal/ are for the hackathon only (LICENSE-DATA.md): --send puts a spec.md in the hands of a third party, so use it with a case
you may send.

The provider's gold is a second writer's opinion, not the experts'. Use it for regulation and section choice and for the agreement
figure; the expert dev gold and the platform's uploads calibrate the requirement level.
Needs PyMuPDF and the base PDFs in regulations/data. Prompts and replies go to regulations/data/_xprovider/ (ignored by git).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

import pymupdf  # noqa: E402
import build_expected  # noqa: E402
from baseline import SCOPE_KINDS, heading_only, parsed, read_spec, section_of  # noqa: E402
from regcomp import corpus  # noqa: E402
from regcomp.parse import NUMBER_PREFIX, Node  # noqa: E402
from run_cases import Case, prf  # noqa: E402
from score_local import _paragraph_key  # noqa: E402

WORK = corpus.DATA / "_xprovider"
CASES = ROOT / "spec" / "testing" / "cases"
SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
PLAIN = str.maketrans(SUPERSCRIPTS, "0123456789-+")
CONTEXT_TOKENS = 250_000  # refuse a prompt above this (estimated at 4 characters a token) unless --context says otherwise
LLM_MAX_TOKENS = 64_000  # output cap of --provider llm; a reasoning model spends part of it thinking, and a cut-off reply is an error
DEFAULT_TIMEOUT_S = 1200
SCOPE_ID = re.compile(r"^(?:(?:Annex|Appendix|Part)\s+(?:\d+[A-Za-z]?|[A-Z]|[IVX]+)\b\s*[-–:.]?\s*)+")

SPEC_TEMPLATE = """# spec: <name>

## Product Type

<one or two sentences: what the product is and does>

## Vehicle Category

<the UNECE category, e.g. M1, N1, L3, and one clause on the vehicle it is fitted to>

## Function

- <what the product does, one line each>

## Main Parts

- <the main parts, one line each>

## Materials

Representative values — confirm against actual bill of materials.


| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| <part>            | <material>                                  |
"""

PICK_RULES = {
    "strategy": """- Choose regulations strictly. A wrong regulation brings in hundreds of paragraphs that do not apply. When the catalogue says a regulation replaces others, choose the one that replaces them.
- Inside a chosen regulation be inclusive. List every section that may hold a requirement for this product: the sections named after its parts and functions, the general specifications and markings every such product must meet, and the annexes with the test methods that fit its materials and technology. Leave out sections about other devices or vehicle categories, the approval application and administrative procedure, definitions, and transitional provisions.
- Reason from what the product is and does, including what its parts imply, not only from the words of the specification.""",
    "plain": """- Choose the regulations that apply to this product and the sections of them that hold requirements for it.""",
}

GOLD_RULES = """Write the engineering requirements this product must fulfil under these regulations, as a regulatory expert would for an engineer who has to design and test the product.
- One engineering obligation per requirement, written as a standalone sentence ("The <device> shall ... [when / where ...]"); split a paragraph that holds several obligations, and one table row that applies to this product is one requirement.
- Keep product obligations, the test criteria they are judged by, markings, and the conditions of the table row that fits this product (its colour, category, size, technology). Leave out the application and approval procedure, duties of the authority, definitions, permissions, transitional provisions, and clauses for other devices, variants or vehicle categories.
- Cite each requirement with the regulation, the physical page number from the `=== page N of M ===` marker, the paragraph label, and a verbatim quote of the paragraph (8 to 25 consecutive words, copied exactly from the page text).
- Write the paragraph label as printed, with the annex, appendix or part it sits in in front when it is not in the body of the regulation: `2.4.1`, `Annex 2 Part 1 3.2`, `Annex 5 4.` For a requirement from a table, add the table: `2.4.1. Table 2`.
Answer with JSON only: {"requirements": [{"regulation": "<the id used in the page markers>", "page": 12, "paragraph": "<label>", "quote": "...", "text": "..."}]}"""


# ---------------------------------------------------------------------------------------------------------------- text
def tokens_of(text: str) -> int:
    return len(text) // 4


def fold(char: str) -> str:
    """One character as it is compared: raised digits plain, one multiplication dot, one apostrophe, lower case; '' for a space."""
    char = char.translate(PLAIN).replace("·", "∙").replace("⋅", "∙").replace("’", "'").replace("‑", "-")
    return "" if char.isspace() else char.lower()


def squash(text: str) -> str:
    """For comparing a quote with page text: case, spacing and raised digits do not count."""
    return "".join(fold(c) for c in text)


def exact_quote(body: str, quote: str) -> str | None:
    """The stretch of `body` that `quote` stands for when spacing, case and raised digits are ignored, as it is written in `body`;
    build_expected wants the quote verbatim, and a model copying it from page text may differ from our node text in those."""
    squashed = [(i, fold(c)) for i, c in enumerate(body) if fold(c)]
    wanted = squash(quote)
    if not wanted:
        return None
    flat = "".join(c for _, c in squashed)
    at = flat.find(wanted)
    if at < 0:
        return None
    return body[squashed[at][0]: squashed[at + len(wanted) - 1][0] + 1]


KEY_NAMES = ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY")
SETTING_NAMES = ("LLM_BASE_URL", "LLM_MODEL", "LLM_TIMEOUT_S")


def load_env(path: Path = ROOT / ".env") -> list[str]:
    """Put the API keys and the LLM_* settings of a .env file (KEY=value lines) into the environment, unless the environment has
    them already. Only those names are taken; the names that were found are returned, the values never leave this function. Called
    by main(), not by the library functions, so a test controls its own environment."""
    found = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            name, _, value = line.strip().removeprefix("export ").partition("=")
            if name.strip() in KEY_NAMES + SETTING_NAMES and value.strip():
                os.environ.setdefault(name.strip(), value.strip().strip("\"'"))
                found.append(name.strip())
    return found


def read_json(text: str) -> dict:
    """The JSON object in a model's reply, which may be wrapped in a code fence or in a sentence."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


# ------------------------------------------------------------------------------------------------------------ catalogue
def catalogue_entries(only: list[str] | None = None) -> list[dict]:
    return [e for e in corpus.load_index() if corpus.pdf_path(e, "base") and (not only or e["regulation"] in only)]


def candidates(regulation: str) -> list[Node]:
    """The nodes a pick can list: paragraphs and tables, except a bare heading that has sub-paragraphs (it is structure, not a
    requirement). A bare line without sub-paragraphs stays: R128's 2.3.1.1 "the rated voltage;" is a gold paragraph."""
    doc = parsed(regulation)
    parents = {(n.scope, n.num[:k]) for n in doc.nodes if n.kind == "para" for k in range(1, len(n.num))}
    return [n for n in doc.nodes if n.kind in ("para", "table") and not (heading_only(n) and (n.scope, n.num) in parents)]


def sections_of(regulation: str) -> list[tuple[str, str, int]]:
    """(id, heading, number of nodes) of the sections a pick may name: depth-2 body sections and annex, appendix and part scopes,
    in document order. The ids are baseline.section_of, the sections the scoring uses."""
    doc = parsed(regulation)
    heads: dict[str, str] = {}
    for n in doc.nodes:
        if n.kind in SCOPE_KINDS:
            heads.setdefault(n.scope, n.body)
    own = {(n.scope, n.num): n.body for n in doc.nodes if n.kind == "para"}
    nodes = candidates(regulation)
    count: dict[str, int] = defaultdict(int)
    first: dict[str, Node] = {}
    for n in nodes:
        count[section_of(n)] += 1
        first.setdefault(section_of(n), n)
    out = []
    for root in count:  # insertion order is document order
        if " " in root:  # 'Annex 4 Part 1', 'Appendix 2': a scope; its heading starts with the id again
            heading = re.sub(r"\s+", " ", heads.get(root, ""))
            heading = SCOPE_ID.sub("", heading)[:90]
        else:
            heading = NUMBER_PREFIX.sub("", own.get(("", tuple(int(x) for x in root.split("."))), first[root].body))[:90]
        out.append((root, heading, count[root]))
    return out


def catalogue(only: list[str] | None = None, scope_chars: int = 600) -> tuple[str, dict[str, set[str]]]:
    """The text a model chooses from, and {regulation: {section ids}} to check its answer against."""
    from simulate_mapping import make_card  # the card's scope text and the regulations it replaces

    lines, menu = [], {}
    for entry in catalogue_entries(only):
        regulation, card, sections = entry["regulation"], make_card(entry), sections_of(entry["regulation"])
        menu[regulation] = {root for root, _, _ in sections}
        lines.append(f"## {regulation} — {entry['title']}")
        lines.append("Scope: " + re.sub(r"\s+", " ", card["scope"])[:scope_chars])
        if card["supersedes"]:
            lines.append("Replaces: " + ", ".join(card["supersedes"]))
        lines.append("Sections (id — heading (paragraphs)):")
        lines += [f"- {root} — {heading} ({n})" for root, heading, n in sections]
        lines.append("")
    return "\n".join(lines), menu


def page_text(regulation: str) -> str:
    """The raw text of the base PDF, page by page, as PyMuPDF reads it: our paragraph logic is not in it."""
    with pymupdf.open(corpus.pdf_path(corpus.entry_for(regulation), "base")) as pdf:
        return "\n".join(f"=== {regulation} page {i} of {pdf.page_count} ===\n{page.get_text('text').strip()}\n"
                         for i, page in enumerate(pdf, start=1))


# --------------------------------------------------------------------------------------------------------------- prompts
def select_prompt(spec: str, catalogue_text: str, variant: str) -> tuple[str, str]:
    system = ("You are a regulatory engineer who decides, for a product, which UN Regulations a type-approval must be checked "
              "against and which sections of them hold the engineering requirements it must fulfil. You answer with JSON only.")
    user = f"""# Task
Below are a product specification and a catalogue of UN Regulations. For each regulation the catalogue gives its title, the start of its scope, the regulations it replaces, and its sections as `id — heading (number of paragraphs)`.

Pick the regulations and the sections. Rules:
{PICK_RULES[variant]}
- Use only regulations and section ids that appear in the catalogue, written exactly as there.

Answer with JSON only, in this shape, the ids copied from the catalogue:
{{"regulations": [{{"regulation": "<regulation id>", "why": "one line"}}], "sections": [{{"regulation": "<regulation id>", "root": "<section id>", "why": "one line"}}]}}

# Product specification
{spec}

# Catalogue of regulations
{catalogue_text}"""
    return system, user


def spec_prompt(brief: str, names: str) -> tuple[str, str]:
    system = "You are a product engineer and regulatory expert. You answer with JSON only."
    user = (f"# Task\nInvent the product described by this brief and write its specification in exactly the markdown format below, in plain "
            f"engineering words (not the words of any regulation). Then list the UN Regulations of the catalogue whose requirements the product "
            f"must fulfil: the ones a type-approval of this product would rest on, three at most.\n\nBrief: {brief}\n\n"
            f"# Format of the specification\n{SPEC_TEMPLATE}\n# Catalogue (id — title)\n{names}\n\n"
            f'Answer with JSON only: {{"spec_md": "the specification, in markdown", "regulations": ["<regulation id>"]}}')
    return system, user


def gold_prompt(spec: str, regulations: list[str]) -> tuple[str, str]:
    system = "You are a regulatory expert at a type-approval authority. You answer with JSON only."
    text = "\n".join(page_text(r) for r in regulations)
    return system, f"# Task\n{GOLD_RULES}\n\n# Product specification\n{spec}\n\n# Regulations (page text)\n{text}"


# --------------------------------------------------------------------------------------------------------------- models
def request_for(provider: str, model: str, system: str, user: str, image: Path | None, thinking: bool = False) -> tuple[str, dict, dict]:
    """(url, headers, body) of one JSON-answer call. The key is read from the environment and goes in a header, never in the URL.
    `llm` asks the model not to think (`thinking: disabled`, DeepSeek's switch, checked live: no reasoning tokens come back) unless
    `thinking` is set, in which case the model's own default applies."""
    picture = base64.b64encode(image.read_bytes()).decode("ascii") if image else None
    if provider in ("openai", "llm"):
        content: list[dict] | str = [{"type": "text", "text": user}]
        if picture:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{picture}"}})
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                "response_format": {"type": "json_object"}}
        if provider == "openai":
            return "https://api.openai.com/v1/chat/completions", {"Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", "")}, body
        base = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
        if not base:
            raise SystemExit("error: LLM_BASE_URL is not set (the endpoint of --provider llm, e.g. https://api.deepseek.com)")
        if not picture:  # the plain string every compatible server takes; the list form only where an image needs it
            body["messages"][1]["content"] = user
        body["max_tokens"] = LLM_MAX_TOKENS
        if not thinking:
            body["thinking"] = {"type": "disabled"}
        return base + "/chat/completions", {"Authorization": "Bearer " + os.environ.get("LLM_API_KEY", "")}, body
    if provider == "gemini":
        parts: list[dict] = [{"text": user}]
        if picture:
            parts.append({"inlineData": {"mimeType": "image/png", "data": picture}})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseMimeType": "application/json"}}
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", {"x-goog-api-key": key}, body
    raise SystemExit(f"error: unknown provider {provider!r}")


def reply_text(provider: str, answer: dict) -> str:
    if provider in ("openai", "llm"):
        choice = answer["choices"][0]
        message, why = choice["message"], choice.get("finish_reason")
        if message.get("refusal"):
            raise RuntimeError("the model refused: " + message["refusal"][:200])
        if why == "length":  # cut off at the output limit: the JSON is incomplete, and a reasoning model may have spent it all thinking
            raise RuntimeError("the reply was cut off at the output limit (finish_reason: length); raise the cap or ask for less")
        if not (message.get("content") or "").strip():
            raise RuntimeError(f"the model returned no content (finish_reason: {why})")
        return message["content"]
    if provider == "gemini":
        if answer.get("promptFeedback", {}).get("blockReason"):
            raise RuntimeError("the prompt was blocked: " + answer["promptFeedback"]["blockReason"])
        return "".join(p.get("text", "") for p in answer["candidates"][0]["content"]["parts"] if not p.get("thought"))
    raise SystemExit(f"error: unknown provider {provider!r}")


def post(url: str, headers: dict, body: dict, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """POST a JSON body and return the JSON answer. `timeout` is how long the connection may stay silent, not a total."""
    data, delay = json.dumps(body).encode("utf-8"), 5
    for attempt in range(4):
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:600]
            if error.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(delay)
                delay *= 3
                continue
            raise SystemExit(f"error: {url.split('?')[0]} answered {error.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError) as error:  # a read that stalls raises TimeoutError, which is not a URLError
            if attempt < 3:
                time.sleep(delay)
                delay *= 3
                continue
            reason = f"no answer within {timeout:g} s (LLM_TIMEOUT_S, or --timeout)" if isinstance(error, TimeoutError) else error.reason
            raise SystemExit(f"error: {url.split('?')[0]} not reachable: {reason}") from None
    raise SystemExit("error: no answer")


def timeout_for(provider: str, flag: float | None) -> float:
    """--timeout, else LLM_TIMEOUT_S for --provider llm, else the default."""
    if flag:
        return flag
    wanted = os.environ.get("LLM_TIMEOUT_S", "").strip()
    if provider == "llm" and wanted:
        try:
            return float(wanted)
        except ValueError:
            raise SystemExit(f"error: LLM_TIMEOUT_S={wanted!r} is not a number of seconds") from None
    return DEFAULT_TIMEOUT_S


class Model:
    """One provider and model, and the folder that keeps the exact prompt and the raw reply of every call."""

    HOSTS = {"openai": "api.openai.com", "gemini": "generativelanguage.googleapis.com", "replay": "(a file)"}

    def __init__(self, args: argparse.Namespace, work: Path, image: Path | None = None) -> None:
        self.provider, self.send, self.context = args.provider, args.send, args.context
        self.name = args.model or (os.environ.get("LLM_MODEL") if args.provider == "llm" else None)
        self.timeout = timeout_for(args.provider, getattr(args, "timeout", None))
        self.thinking = getattr(args, "thinking", False)
        self.replies, self.work, self.image = list(args.reply or []), work, image

    @property
    def host(self) -> str:
        if self.provider == "llm":
            return urllib.parse.urlparse(os.environ.get("LLM_BASE_URL", "")).netloc or "(LLM_BASE_URL is not set)"
        return self.HOSTS[self.provider]

    def ask(self, label: str, system: str, user: str) -> str | None:
        """The reply text; None for a dry run, which says what it would send and stops."""
        self.work.mkdir(parents=True, exist_ok=True)
        kept = self.work / f"{label}.prompt.txt"
        kept.write_text(f"# SYSTEM\n{system}\n\n# USER\n{user}\n", encoding="utf-8")
        size = tokens_of(system) + tokens_of(user)
        print(f"{label}: {self.provider}/{self.name or '-'} at {self.host}: about {size:,} tokens ({len(user):,} characters)"
              + (f" and {self.image.name}" if self.image else "") + f"; the prompt is kept in {kept}")
        if size > self.context:
            raise SystemExit(f"error: the prompt is about {size:,} tokens, over --context {self.context:,}; narrow it or raise --context")
        if self.provider == "replay":
            if not self.replies:
                raise SystemExit("error: --provider replay needs one --reply FILE for each call")
            text = Path(self.replies.pop(0)).read_text(encoding="utf-8")
        elif not self.send:
            have = {"openai": os.environ.get("OPENAI_API_KEY"), "gemini": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
                    "llm": os.environ.get("LLM_API_KEY")}[self.provider]
            print(f"dry run: nothing was sent. An API key for {self.provider} was {'found' if have else 'NOT found'}. Add --send to call the model.")
            return None
        else:
            if not self.name:
                raise SystemExit("error: --model is required with --send (for --provider llm: or LLM_MODEL)")
            url, headers, body = request_for(self.provider, self.name, system, user, self.image, self.thinking)
            if not any(v.removeprefix("Bearer ").strip() for v in headers.values()):
                raise SystemExit("error: no API key in the environment (OPENAI_API_KEY, GEMINI_API_KEY / GOOGLE_API_KEY, or LLM_API_KEY)")
            text = reply_text(self.provider, post(url, headers, body, self.timeout))
        (self.work / f"{label}.reply.txt").write_text(text, encoding="utf-8")
        return text


# --------------------------------------------------------------------------------------------------------- the answers
def resolve_picks(answer: dict, menu: dict[str, set[str]]) -> tuple[list[dict], list[dict], list[str]]:
    """(sections, regulations, rejected): the picks that name a regulation and a section that exist; the others are listed with the
    reason. Names are matched ignoring case, spacing and a closing dot."""
    norm = lambda x: re.sub(r"\s+", " ", str(x)).strip().rstrip(".").lower()  # noqa: E731
    by_name = {norm(r): r for r in menu}
    regulations, sections, rejected = [], [], []
    for item in answer.get("regulations", []):
        name = by_name.get(norm(item.get("regulation", "")))
        if name:
            regulations.append({"regulation": name, "why": item.get("why", "")})
        else:
            rejected.append(f"regulation {item.get('regulation')!r} is not in the catalogue")
    for item in answer.get("sections", []):
        name = by_name.get(norm(item.get("regulation", "")))
        root = {norm(r): r for r in menu.get(name, ())}.get(norm(item.get("root", "")))
        if name and root:
            sections.append({"regulation": name, "root": root, "why": item.get("why", "")})
        else:
            rejected.append(f"section {item.get('root')!r} of {item.get('regulation')!r} is not in the catalogue")
    return sections, regulations, rejected


def nodes_under(sections: list[dict]) -> list[tuple[str, Node]]:
    """The nodes of the picked sections, as (regulation, node)."""
    picks = []
    for regulation in dict.fromkeys(s["regulation"] for s in sections):
        wanted = {s["root"] for s in sections if s["regulation"] == regulation}
        picks += [(regulation, n) for n in candidates(regulation) if section_of(n) in wanted]
    return picks


def score_picks(case: Case, sections: list[dict], regulations: list[dict]) -> dict:
    """Regulation, section and paragraph level of a pick, as the funnel of spec/precision.md M3 counts them."""
    chosen = sorted({r["regulation"] for r in regulations})
    picked = {(s["regulation"], s["root"]) for s in sections}
    nodes = nodes_under(sections)
    empty = {"nodes": 0, "found": 0, "paragraph_precision": 0.0, "paragraph_recall": 0.0, "paragraph_f2": 0.0,
             "regulation_level": {"precision": 0.0, "recall": 0.0}, "page_level": {"precision": 0.0, "recall": 0.0}}
    result = case.evaluate(nodes) if nodes else empty
    cited = {(reg, _paragraph_key(n.label)) for reg, n in nodes}
    reachable = sum(1 for r in case.expected["requirements"] if (r["source"]["regulation"], _paragraph_key(r["source"]["paragraph"])) in cited)
    return {
        "regulations": {"chosen": chosen, "gold": list(case.regulations), **prf(len(set(chosen) & set(case.regulations)), len(chosen), len(case.regulations))},
        "sections": {"picked": len(picked), "gold": len(case.sections), "hit": len(picked & case.sections),
                     **prf(len(picked & case.sections), len(picked), len(case.sections))},
        "paragraphs": {k: result[k] for k in ("nodes", "found", "paragraph_precision", "paragraph_recall", "paragraph_f2")},
        "gold_paragraphs": len(case.paragraphs), "requirements_reachable": f"{reachable}/{case.requirements}",
        "regulation_level": result["regulation_level"], "page_level": result["page_level"],
    }


def print_score(name: str, s: dict) -> None:
    r, sec, p = s["regulations"], s["sections"], s["paragraphs"]
    print(f"\n{name}")
    print(f"  regulations  chosen {r['chosen']}  gold {r['gold']}  P {r['precision']:.2f}  R {r['recall']:.2f}  F2 {r['f2']:.2f}")
    print(f"  sections     picked {sec['picked']}, gold {sec['gold']}, hit {sec['hit']}  P {sec['precision']:.2f}  R {sec['recall']:.2f}  F2 {sec['f2']:.2f}")
    print(f"  paragraphs   {p['nodes']} nodes hold {p['found']}/{s['gold_paragraphs']} gold paragraphs  P {p['paragraph_precision']:.2f}  "
          f"R {p['paragraph_recall']:.2f}  F2 {p['paragraph_f2']:.2f}   requirements reachable {s['requirements_reachable']}")
    print(f"  score_local  regulation P {s['regulation_level']['precision']:.2f} R {s['regulation_level']['recall']:.2f}"
          f"   page P {s['page_level']['precision']:.2f} R {s['page_level']['recall']:.2f}")


# ------------------------------------------------------------------------------------------------------------ grounding
VERDICTS = ("ok", "wrong page", "hallucinated", "other node", "spans nodes", "no node")
TABLE_WORD = re.compile(r"\btable\b")
ROW_ID = re.compile(r"\s[a-z]{1,2}\d+$")  # a table row the model names in the label: "m10", "a1"


def label_readings(key: str | None) -> list[tuple[str, str]]:
    """What a model's paragraph label may mean, as (key, reading), most literal first. A model writes the table under a paragraph into
    the label ('6.9.1. Table 3b', '5.2.1.4. Table', 'Annex 5 Part B 1. Table B1 M10', 'Annex 5 Part B 1. M10': a row id after the
    caption, or in its place). The parser has that table in the paragraph's own node when the table has no caption line (R10 6.9.1)
    and as '<paragraph>. Table B1' when it has: so the label is also read without the row id and without the Table clause."""
    key = key or ""
    out = [(key, "as written")]
    if (m := TABLE_WORD.search(key)):
        words = key[m.start():].split()  # 'table', its id, then whatever the model added after it
        if len(words) > 2:
            out.append((key[: m.start()] + " ".join(words[:2]), "without the row id"))
        if key[: m.start()].strip():
            out.append((key[: m.start()].strip(), "without the table"))
    elif (m := ROW_ID.search(key)):
        out.append((key[: m.start()].strip(), "without the row id"))
    words = key.split()
    for k in range(len(words) - 1, 1, -1):  # a descriptor the model added to a scope ("Annex 2 Model A", "Annex 3 a"): words with no digit
        if any(c.isdigit() for c in words[k]):  # a number is never dropped: "Annex 4 Part 1 1.2" is not "Annex 4 Part 1"
            break
        if (prefix := " ".join(words[:k])) not in [p for p, _ in out]:
            out.append((prefix, "without the trailing words"))
    return out


def ground_nodes(regulation: str) -> list[tuple[Node, str]]:
    """The nodes a label can name, with their squashed text: paragraphs and tables (candidates) and the headings of annexes,
    appendices and parts, whose own text (a model of the approval mark, a communication form) a requirement may quote."""
    heads = [n for n in parsed(regulation).nodes if n.kind in SCOPE_KINDS]
    return [(n, squash(n.body)) for n in [*candidates(regulation), *heads]]


def ground(requirements: list[dict]) -> list[dict]:
    """Triage a provider's requirements (regulation, page, paragraph, quote). Each gets a verdict:
      ok            a parsed node with that label holds the quote, on the page the provider gave (+-1); the label may differ from the
                    node's by a Table clause or a row id the model added (label_readings), or by a table that the parser names
                    '<paragraph>. Table N' where the model names the paragraph: `read` says how
      wrong page    that node holds the quote, but not near the page the provider gave
      hallucinated  the quote is on no page of the regulation's raw text
      other node    the quote is in a parsed node with another label: the provider's label or our segmentation differs
      spans nodes   the label exists but no single parsed node holds the quote: a table, or a paragraph we split
      no node       the quote is on a page but no parsed node has the label
    Everything but ok and hallucinated is for a person to open in the PDF: it is a defect of the parser, or of the label.
    `exact` is the quote as our node writes it, for build_expected; `label` the label of the node that holds it."""
    raw: dict[str, list[str]] = {}
    nodes_of: dict[str, list[tuple[Node, str]]] = {}
    out = []
    for item in requirements:
        regulation = item.get("regulation", "")
        if regulation not in raw:
            with pymupdf.open(corpus.pdf_path(corpus.entry_for(regulation), "base")) as pdf:
                raw[regulation] = [squash(p.get_text("text")) for p in pdf]
            nodes_of[regulation] = ground_nodes(regulation)
        quote = squash(item.get("quote", ""))
        on_pages = [i + 1 for i, text in enumerate(raw[regulation]) if quote and quote in text]
        if not on_pages and len(quote) > 20:  # a quote that crosses a page break: find its first half
            on_pages = [i + 1 for i, text in enumerate(raw[regulation]) if quote[: len(quote) // 2] in text]
        key, page = _paragraph_key(item.get("paragraph", "")), item.get("page")
        near = lambda n: isinstance(page, int) and n.page_start - 1 <= page <= n.page_end + 1  # noqa: E731
        labelled = [(n, s) for n, s in nodes_of[regulation] if _paragraph_key(n.label) == key]
        holding, read = [], "as written"
        for reading_key, read in label_readings(key):
            holding = [n for n, s in nodes_of[regulation] if quote and quote in s and _paragraph_key(n.label) == reading_key]
            if holding:
                break
        tables = [(n, _paragraph_key(n.label) or "") for n, s in nodes_of[regulation] if quote and quote in s and n.kind == "table"]
        if not holding:  # the model names the paragraph and the parser has its table as '<paragraph>. Table N'
            for reading_key, _ in label_readings(key):
                holding = [n for n, k in tables if k.startswith(reading_key + " table")]
                if holding:
                    read = "table of the paragraph"
                    break
        if not holding and (m := TABLE_WORD.search(key or "")) and len((key or "")[m.start():].split()) > 1:  # the right table, another owner
            wanted = " ".join((key or "")[m.start():].split()[:2])
            holding = [n for n, k in tables if k == wanted or k.endswith(" " + wanted)]
            read = "table by its id"
        elsewhere = [n for n, s in nodes_of[regulation] if quote and quote in s and _paragraph_key(n.label) != key]
        if not on_pages:
            verdict = "hallucinated"
        elif any(near(n) for n in holding):
            verdict = "ok"
        elif holding:
            verdict = "wrong page"
        elif elsewhere:
            verdict = "other node"
        elif labelled:
            verdict = "spans nodes"
        else:
            verdict = "no node"
        row = {"regulation": regulation, "paragraph": item.get("paragraph"), "page": page, "raw_pages": on_pages[:4], "verdict": verdict}
        if verdict in ("ok", "wrong page"):
            holder = next(n for n in holding if near(n) or verdict == "wrong page")
            row["exact"] = exact_quote(holder.body, item["quote"])
            row["label"] = holder.label
            if read != "as written":
                row["read"] = read
        elif verdict == "other node":
            row["our_labels"] = [n.label for n in elsewhere][:3]
        out.append(row)
    return out


def print_ground(rows: list[dict]) -> None:
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    read = sum(1 for r in rows if r.get("read"))
    print("grounding of %d: " % len(rows) + ", ".join(f"{v} {n}" for v, n in counts.items() if n)
          + (f" ({read} of the ok or wrong page with a label read as the node's)" if read else ""))
    for row in rows:
        if row["verdict"] != "ok":
            extra = f"  our labels {row['our_labels']}" if row.get("our_labels") else ""
            print(f"  {row['verdict']:<13}{row['regulation']} {row['paragraph']!r} p{row['page']}  quote on page(s) {row['raw_pages']}{extra}")


def authoring_from(requirements: list[dict], rows: list[dict], case_id: str) -> dict:
    """build_expected's authoring file from the requirements that ground, with the quote and the label as our node writes them."""
    keep = [(r, row) for r, row in zip(requirements, rows) if row["verdict"] in ("ok", "wrong page") and row.get("exact")]
    return {"case_id": case_id, "regulation": keep[0][0]["regulation"] if keep else "",
            "requirements": [{"regulation": r["regulation"], "paragraph": row.get("label") or r["paragraph"], "quote": row["exact"],
                              "text": r["text"]} for r, row in keep]}


# --------------------------------------------------------------------------------------------------------------- commands
def cmd_catalogue(args: argparse.Namespace) -> int:
    text, menu = catalogue(args.only)
    print(f"{len(menu)} regulations, {sum(len(v) for v in menu.values()):,} sections, {len(text):,} characters, about {tokens_of(text):,} tokens")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print("written to", args.out)
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    case = Path(args.case)
    work = WORK / f"select-{case.name}-{args.provider}-{args.variant}"
    text, menu = catalogue()
    system, user = select_prompt((case / "spec.md").read_text(encoding="utf-8"), text, args.variant)
    image = case / "exploded_view.png"
    reply = Model(args, work, image if args.image and image.is_file() else None).ask("select", system, user)
    if reply is None:
        return 0
    sections, regulations, rejected = resolve_picks(read_json(reply), menu)  # expected.json is read from here on, to score
    for line in rejected:
        print("  rejected:", line)
    (work / "picks.json").write_text(json.dumps(sections, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (work / "regulations.json").write_text(json.dumps(regulations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(regulations)} regulations and {len(sections)} sections picked, {len(rejected)} rejected; picks in {work / 'picks.json'}")
    print_score(f"{case.name} · {args.provider} {args.model or ''} · prompt {args.variant}", score_picks(Case(case), sections, regulations))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    sections = json.loads(Path(args.picks).read_text(encoding="utf-8"))
    regulations = [{"regulation": r} for r in dict.fromkeys(s["regulation"] for s in sections)]
    print_score(f"{Path(args.case).name} · {Path(args.picks).name}", score_picks(Case(Path(args.case)), sections, regulations))
    return 0


def cmd_ground(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    rows = ground(data["requirements"] if isinstance(data, dict) else data)
    print_ground(rows)
    Path(args.file).with_name("ground.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def cmd_regrade(args: argparse.Namespace) -> int:
    """Offline: ground the saved provider.json of every case again with the parser as it is now, and show how the verdicts moved
    against the ground.json kept when the case was written. `--write` keeps the new verdicts and rebuilds authoring.json and
    expected.json from them (labels and pages come from the parser, so a parser fix changes them)."""
    cases = [Path(c) for c in args.cases] or sorted(p.parent for p in CASES.glob("*/provider.json"))
    moved: dict[tuple[str, str], int] = defaultdict(int)
    totals = {"before": defaultdict(int), "after": defaultdict(int)}
    print(f"{'case':<26}{'wrote':>6}{'ok':>6}{'(was)':>7}{'wrong':>6}{'hall':>5}{'other':>6}{'spans':>6}{'nonode':>7}{'kept':>6}{'(was)':>7}")
    for case in cases:
        requirements = json.loads((case / "provider.json").read_text(encoding="utf-8"))["requirements"]
        rows = ground(requirements)
        saved = json.loads((case / "ground.json").read_text(encoding="utf-8")) if (case / "ground.json").is_file() else []
        before = [r["verdict"] for r in saved] if len(saved) == len(rows) else ["?"] * len(rows)
        for was, row in zip(before, rows):
            moved[(was, row["verdict"])] += 1
            totals["before"][was] += 1
            totals["after"][row["verdict"]] += 1
        now = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
        kept_now = now["ok"] + now["wrong page"]
        kept_was = sum(1 for v in before if v in ("ok", "wrong page"))
        print(f"{case.name:<26}{len(rows):>6}{now['ok']:>6}{before.count('ok'):>7}{now['wrong page']:>6}{now['hallucinated']:>5}"
              f"{now['other node']:>6}{now['spans nodes']:>6}{now['no node']:>7}{kept_now:>6}{kept_was:>7}")
        if args.write:
            (case / "ground.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            authoring = authoring_from(requirements, rows, case.name)
            (case / "authoring.json").write_text(json.dumps(authoring, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            expected, problems = build_expected.build(authoring) if authoring["requirements"] else ({}, ["nothing grounded"])
            for problem in problems:
                print("   build_expected:", problem)
            if not problems:
                (case / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    n = sum(totals["after"].values())
    kept_was = sum(totals["before"][v] for v in ("ok", "wrong page"))
    kept_now = sum(totals["after"][v] for v in ("ok", "wrong page"))
    print(f"{'TOTAL':<26}{n:>6}  kept {kept_now} ({100 * kept_now / max(1, n):.1f}%), was {kept_was} ({100 * kept_was / max(1, n):.1f}%)")
    print("moved:", ", ".join(f"{a} -> {b} {k}" for (a, b), k in sorted(moved.items(), key=lambda kv: -kv[1]) if a != b) or "nothing")
    return 0


def write_gold(model: Model, spec: str, regulations: list[str], target: Path) -> tuple[list[dict], list[dict]] | None:
    """Ask for the requirements, ground them, and keep both in `target`. None for a dry run."""
    reply = model.ask("gold", *gold_prompt(spec, regulations))
    if reply is None:
        return None
    requirements = [r for r in read_json(reply)["requirements"] if r.get("regulation") in regulations]
    rows = ground(requirements)
    target.mkdir(parents=True, exist_ok=True)
    (target / "provider.json").write_text(json.dumps({"requirements": requirements}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (target / "ground.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print_ground(rows)
    return requirements, rows


def known(regulation: str) -> bool:
    try:
        return corpus.pdf_path(corpus.entry_for(regulation), "base") is not None
    except KeyError:
        return False


def cmd_author(args: argparse.Namespace) -> int:
    target = CASES / args.id
    model = Model(args, WORK / f"author-{args.id}-{args.provider}")
    names = "\n".join(f"{e['regulation']} — {e['title']}" for e in catalogue_entries())
    reply = model.ask("spec", *spec_prompt(args.brief, names))
    if reply is None:
        return 0
    answer = read_json(reply)
    spec, chosen = answer["spec_md"].rstrip() + "\n", [r for r in answer["regulations"] if known(r)][: args.max_regulations]
    target.mkdir(parents=True, exist_ok=True)
    (target / "spec.md").write_text(spec, encoding="utf-8")
    profile = read_spec(target / "spec.md")
    print(f"spec written to {target / 'spec.md'} ({len(profile.facets)} facets); regulations: {chosen}")
    done = write_gold(model, spec, chosen, target)
    if done is None:
        return 0
    requirements, rows = done
    authoring = authoring_from(requirements, rows, args.id)
    (target / "authoring.json").write_text(json.dumps(authoring, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    expected, problems = build_expected.build(authoring) if authoring["requirements"] else ({}, ["nothing grounded"])
    for problem in problems:
        print("  build_expected:", problem)
    if not problems:
        (target / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{target / 'expected.json'}: {len(expected['requirements'])} grounded of the {len(requirements)} the provider wrote")
    return 0


def cmd_agree(args: argparse.Namespace) -> int:
    case = Path(args.case)
    ours = Case(case)  # only the names of its regulations go into the prompt
    work = WORK / f"agree-{case.name}-{args.provider}"
    done = write_gold(Model(args, work), (case / "spec.md").read_text(encoding="utf-8"), list(ours.regulations), work)
    if done is None:
        return 0
    requirements, rows = done
    grounded = [r for r, row in zip(requirements, rows) if row["verdict"] in ("ok", "wrong page")]
    picks, seen = [], set()
    for r in grounded:
        key = (r["regulation"], _paragraph_key(r["paragraph"]))
        node = next((n for n in candidates(r["regulation"]) if _paragraph_key(n.label) == key[1]), None)
        if node is not None and key not in seen:
            seen.add(key)
            picks.append((r["regulation"], node))
    print(f"\nagreement on {case.name}: the provider wrote {len(requirements)} requirements ({len(grounded)} grounded) on {len(picks)} paragraphs; "
          f"ours has {ours.requirements} on {len(ours.paragraphs)}")
    if picks:
        result = ours.evaluate(picks)
        print(f"  paragraph level  P {result['paragraph_precision']:.2f} (of the provider's paragraphs, ours cites them)   "
              f"R {result['paragraph_recall']:.2f} (of ours, the provider cites them)   F2 {result['paragraph_f2']:.2f}")
        print(f"  score_local      regulation P {result['regulation_level']['precision']:.2f} R {result['regulation_level']['recall']:.2f}"
              f"   page P {result['page_level']['precision']:.2f} R {result['page_level']['recall']:.2f}")
    return 0


# ------------------------------------------------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Questions of the pipeline put to a model from another provider.")
    sub = parser.add_subparsers(dest="command", required=True)

    def model_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--provider", choices=["openai", "gemini", "llm", "replay"], default="openai",
                       help="llm: an OpenAI-compatible endpoint set by LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_S (.env)")
        p.add_argument("--model", help="the provider's model id (--provider llm: LLM_MODEL when left out)")
        p.add_argument("--timeout", type=float, help="seconds a connection may stay silent (--provider llm: LLM_TIMEOUT_S; else 1200)")
        p.add_argument("--thinking", action="store_true", help="--provider llm: leave the model's thinking on (without it: thinking disabled)")
        p.add_argument("--send", action="store_true", help="actually call the model (without it: print what would be sent and stop)")
        p.add_argument("--reply", action="append", help="--provider replay: the file that answers the next call (once per call)")
        p.add_argument("--context", type=int, default=CONTEXT_TOKENS, help="refuse a prompt above this many tokens (4 characters each)")

    p = sub.add_parser("catalogue", help="the size of the catalogue that select sends")
    p.add_argument("--only", nargs="+", help="only these regulations")
    p.add_argument("--out", help="write the catalogue here")
    p = sub.add_parser("select", help="the provider picks regulations and sections for a case's spec")
    p.add_argument("case", help="a case folder with spec.md and expected.json")
    p.add_argument("--variant", choices=["strategy", "plain"], default="strategy", help="strategy: the proposal's rules in the prompt; plain: none")
    p.add_argument("--image", action="store_true", help="also send the case's exploded_view.png")
    model_options(p)
    p = sub.add_parser("score", help="score a picks file offline")
    p.add_argument("case")
    p.add_argument("picks")
    p = sub.add_parser("ground", help="check a provider's requirements against the PDFs offline")
    p.add_argument("file", help="a JSON file with a list of requirements (regulation, page, paragraph, quote), or {requirements: [...]}")
    p = sub.add_parser("regrade", help="ground the saved provider.json of cases again with the current parser (offline) and show what moved")
    p.add_argument("cases", nargs="*", help="case folders (default: every spec/testing/cases/* with a provider.json)")
    p.add_argument("--write", action="store_true", help="keep the new verdicts and rebuild authoring.json and expected.json")
    p = sub.add_parser("author", help="the provider invents a product and writes a gold for it")
    p.add_argument("--id", required=True, help="the case id; the case goes to spec/testing/cases/ID/")
    p.add_argument("--brief", required=True, help="one line: the product, e.g. 'front bumper with parking sensors and fog lamps, M1'")
    p.add_argument("--max-regulations", type=int, default=3)
    model_options(p)
    p = sub.add_parser("agree", help="the provider writes its own gold for a case; compare it with the case's")
    p.add_argument("case")
    model_options(p)

    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env()
    return {"catalogue": cmd_catalogue, "select": cmd_select, "score": cmd_score, "ground": cmd_ground, "regrade": cmd_regrade,
            "author": cmd_author, "agree": cmd_agree}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
