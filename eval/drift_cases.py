#!/usr/bin/env python3
"""Build the drift cases of spec/testing/cases-drift/: real base -> latest pairs of UN Regulations, a window of sections of each, the
requirements an expert would have derived from the OLD window (written by DeepSeek) and the changes the NEW version makes to them (also
DeepSeek, from the old and new paragraph text, the deterministic diff of src/ai_agent/drift.py and the list of added paragraphs).

    python eval/drift_cases.py scan                      # alignment counts of every regulation that has a latest version
    python eval/drift_cases.py build                     # dry run: print what would be sent for every case
    python eval/drift_cases.py build --send [ID ...]     # call DeepSeek (--provider llm of eval/xprovider.py, thinking off) and write the cases
    python eval/drift_cases.py check                     # validate every case folder with tools/validate.py and refresh the README table

Only public regulation text and the public example subgoal/dev/requirements_old.json style go to the provider; cases/ is never read.
The reasons in expected.json are built in code (the diff of the two paragraphs, in the format of subgoal/dev/expected.json); DeepSeek decides
WHICH requirements change, writes the new wording, and lists the added obligations. Its raw replies are kept in provider.json. A gold written
by a model is noisy: the checks in `sanity` drop what contradicts the alignment and log it in notes.md.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import socket
import sys
import time
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from ai_agent import drift  # noqa: E402
from ai_agent.store import label_key  # noqa: E402
from regcomp import corpus  # noqa: E402

OUT = ROOT / "spec" / "testing" / "cases-drift"
DEV_OLD = ROOT / "subgoal" / "dev" / "requirements_old.json"
TEAM = "synthetic"

CASES = [
    {"id": "drift-r39-speedometer", "regulation": "UN R39", "window": ["2", "5"], "trap": "ADS exemptions, one-word typography fixes",
     "about": "Speedometer: ADS sentences added to 5.1, 5.2, 5.5, 5.11; 'onboard' -> 'on-board' and 'UN' insertions that change nothing; a table caption removed."},
    {"id": "drift-r100-battery-adsf", "regulation": "UN R100", "window": ["5"], "trap": "the same sentence added to many paragraphs; a cross-reference re-pointed",
     "about": "Battery-electric vehicle safety: 'Whilst an ADSF-2 is active ...' added to eight warning paragraphs (5.1.3.3-5.3.4); 5.4.1 now cites 7.1."},
    {"id": "drift-r131-aebs-rewrite", "regulation": "UN R131", "window": ["5"], "trap": "same label, paragraph rewritten (alignment sees a removal and an addition)",
     "about": "AEBS: paragraph 5.4.5 ('the AEBS function may be suspended while ALKS is active') is replaced by a heading and three obligations (deactivate, reactivate, 5.4.4 not applicable)."},
    {"id": "drift-r156-ota-renumber", "regulation": "UN R156", "window": ["6", "7"], "trap": "renumbering only: 13 paragraphs shift by one with the text unchanged",
     "about": "Software update management: paragraphs 7.1.1.3-7.1.1.12 become 7.1.1.4-7.1.1.13 and 7.1.4 becomes 7.1.5 because one paragraph is inserted; one removed paragraph; three added."},
    {"id": "drift-r149-lamp-uid-removed", "regulation": "UN R149", "window": ["3.2", "3.3"], "trap": "a removed section shifts the numbering below it ('formerly 3.3.4'); removal of a phrase in many paragraphs",
     "about": "Road illumination devices, marking: the Unique Identifier section 3.3.3 is deleted, so 3.3.4-3.3.6 become 3.3.3-3.3.5 (14 renumbered), and 'the Unique Identifier or' is cut from several paragraphs."},
    {"id": "drift-r10-emc-few-changes", "regulation": "UN R10", "window": ["6"], "trap": "almost everything unchanged; only added paragraphs (every unchanged requirement is a false-flag risk)",
     "about": "EMC specifications: nothing in 6.1-6.10 changes; 6.11 (special requirements for vehicles with an ADS) is new."},
    {"id": "drift-r132-reagent-restructure", "regulation": "UN R132", "window": ["7", "8"], "trap": "a list merged into one paragraph (five removals and one addition that say the same)",
     "about": "Retrofit emission control devices: the approval conditions 7.9.1-7.9.4 become items (a)-(d) of a single paragraph 7.9; 7.5.1 'may interrupt' becomes 'shall include the detection of the interruption of'."},
    {"id": "drift-r51-noise-asep", "regulation": "UN R51", "window": ["Annex 7"], "trap": "formulas and a new table; wording of calculations",
     "about": "Noise, Annex 7 (ASEP): the control range moves into a table, the evaluation formulas change (3 dB(A) -> 2 dB, new term delta L), purely electric vehicles get a separate method."},
    {"id": "drift-r174-belt-reminder", "regulation": "UN R174", "window": ["5"], "trap": "footnote text changes and ADS sentences; a reference fixed (6.2.4.1.1 -> 5.2.4.1.1)",
     "about": "Safety-belt reminder: footnote 3 changes, the reminder now covers first-row occupants of category X vehicles, 'Whilst an ADSF-2 is active, paragraph 5.1.4 shall apply' is added, 5.1.4 is new."},
    {"id": "drift-r64-tyre-terms", "regulation": "UN R64", "window": ["Annex 3", "Annex 4"], "trap": "terminology swap that changes the test trigger ('ignition' -> 'vehicle master control'), 'must' -> 'shall'",
     "about": "Run-flat/TPMS test procedure: 'ignition' becomes 'vehicle master control (switch)' in eight paragraphs, 'must' becomes 'shall', and an ADS sentence is added to 2.1 and 2.2."},
]

# --------------------------------------------------------------------------------------------------------------------------- windows


def in_window(node, window: list[str]) -> bool:
    for p in window:
        if p.startswith(("Annex", "Appendix")):
            if node.scope == p or node.scope.startswith(p + " "):
                return True
        elif not node.scope and (node.label == p or node.label.startswith(p + ".")):
            return True
    return False


def load_pair(reg: str):
    entry = corpus.entry_for(reg)
    old = drift.Version.from_pdf(corpus.pdf_path(entry, "base"), reg, corpus.version_label(entry, "base"))
    new = drift.Version.from_pdf(corpus.pdf_path(entry, "latest"), reg, corpus.version_label(entry, "latest"))
    return entry, old, new


def window_matches(old, new, matches, window):
    """The matches that touch the window: the old node is in it, or (an added node) the new one is."""
    rows = []
    for m in matches:
        if m.old is not None and in_window(old.nodes[m.old], window):
            rows.append(m)
        elif m.old is None and in_window(new.nodes[m.new], window):
            rows.append(m)
    return rows


def pages(node) -> int:
    return node.page_start


CLIP = 3500


def render_old(old, rows) -> str:
    out = []
    for m in rows:
        if m.old is None:
            continue
        i = m.old
        out.append(f"[{old.ids[i]} | page {old.nodes[i].page_start}]\n{old.texts[i][:CLIP]}")
    return "\n\n".join(out)


# --------------------------------------------------------------------------------------------------------------------------- prompts
STYLE = """How an expert writes requirements:
- One requirement is one subject and one constraint, with its condition: a sentence of the form "The <system> shall ...". Each independent constraint of a paragraph is a requirement of its own (usually one per sentence, one per list item that is a separate constraint, one per row of a table); the lead-in's condition goes into each. An exception that follows a constraint is part of it.
- Keep the paragraph's words, numbers, units and cross-references exactly. Add nothing that is not in the paragraph.
- Product requirements only: design, performance, marking, installation, test procedure and test pass criteria, conformity of production. Skip definitions, scope statements, headings, pure cross-references, the approval application and administrative procedure, duties of the authority, transitional provisions and forms - unless the paragraph imposes an obligation on the product or the manufacturer.
- About 1.6 requirements per paragraph that has an obligation; a paragraph with none gets none."""

EXAMPLE_PARAGRAPHS = "5.1.4 5.1.5 6.1.7"


def example_block() -> str:
    reqs = json.loads(DEV_OLD.read_text(encoding="utf-8"))
    pick = [r for r in reqs if r["source"]["paragraph"] in EXAMPLE_PARAGRAPHS.split()][:5]
    lines = [f'- paragraph {r["source"]["paragraph"]}: "{r["text"][:400]}"' for r in pick]
    return "Examples of requirements as the experts wrote them (from another regulation, UN R175):\n" + "\n".join(lines)


SYSTEM_OLD = f"""You are a regulatory expert who turns the provisions of a UN Regulation into the engineering requirements of a product. You get the paragraphs of one part of a regulation, each as [label | page N] and its text, and write the requirements of that part.

{STYLE}

{example_block()}

Answer with JSON only: {{"requirements": [{{"paragraph": "<the label exactly as given>", "text": "<the requirement>"}}]}}, in document order. The label must be one of the labels given."""

SYSTEM_NEW = f"""You are a regulatory expert checking, version by version, which engineering requirements of a UN Regulation have to change. The requirements were derived from the OLD version. You get, for every paragraph of a window of the regulation that is NOT identical in the NEW version: the old paragraph, the requirements derived from it (with ids), the matching new paragraph (or candidate new paragraphs, when the old one was deleted or rewritten), and a word-level diff. You also get the list of NEW paragraphs that have no old counterpart.

Decide, for each existing requirement, whether it:
- "modified": its content changed - a different condition, number, limit, scope, exception, or an added or removed obligation or sentence that belongs to it. Give the requirement rewritten for the new version (`new_text`: the old requirement with the change applied, same style, a standalone "X shall ..." sentence) and the label of the NEW paragraph where it now sits (`new_paragraph`, one of the labels given).
- "removed": the content is gone from the new version altogether.
- unchanged: say nothing. A requirement is NOT changed by: a change of paragraph number or of the order of paragraphs; spelling, hyphenation, capitalisation, punctuation, units written another way ("per cent"), the same word in another form; a footnote renumbered; a clause that changes only another requirement of the same paragraph; wording that means the same. A change of a cross-reference number that only follows a renumbering is not a change either.

Also list the ADDED obligations: obligations on the product or the manufacturer that the new version states and the old requirements do not cover, in the new paragraphs that have no old counterpart (or a new sentence of a changed paragraph that no old requirement covers). One entry per obligation, atomic, in the style "The <system> shall ...", with the label of the new paragraph it comes from (`new_paragraph`). Do not list definitions, headings, transitional provisions, administrative procedure or forms, and do not list again what a modified requirement already carries.

{STYLE}

Answer with JSON only:
{{"changes": [
  {{"change": "modified", "requirement_id": "R-012", "new_text": "...", "new_paragraph": "<label of the new paragraph>"}},
  {{"change": "removed", "requirement_id": "R-013"}},
  {{"change": "added", "new_text": "...", "new_paragraph": "<label of the new paragraph>"}}
]}}
Use only requirement ids that are given. An empty list is a correct answer when nothing changes."""


def old_user(reg, old, rows) -> str:
    return (f"Regulation: {reg} - {old.doc.path.name} (version {old.label})\nWindow: the paragraphs below\n\n"
            + render_old(old, rows) + "\n\nWrite the requirements.")


def requirement_list(requirements: list[dict], old, i) -> list[dict]:
    key = old.key(i)
    return [r for r in requirements if label_key(r["source"]["paragraph"]) == key]


def new_user(reg, old, new, rows, requirements) -> tuple[str, list[dict]]:
    """The user message of call 2 and the list of affected old nodes it covers."""
    blocks, covered = [], []
    pool = [m.new for m in rows if m.kind == drift.ADDED] + [m.new for m in rows if m.kind == drift.MODIFIED]
    for m in rows:
        if m.kind in (drift.SAME, drift.RENUMBERED, drift.ADDED):
            continue
        i = m.old
        reqs = requirement_list(requirements, old, i)
        head = f"### OLD paragraph {old.ids[i]} (page {old.nodes[i].page_start}) - {m.kind}\n{old.texts[i][:CLIP]}"
        rq = "\n".join(f'{r["id"]}: {r["text"]}' for r in reqs) or "(no requirement was derived from this paragraph)"
        if m.kind == drift.MODIFIED:
            j = m.new
            body = (f"NEW paragraph {new.ids[j]} (page {new.nodes[j].page_start}){' [renumbered]' if m.renumbered else ''}:\n{new.texts[j][:CLIP]}\n"
                    f"Word diff:\n{drift.diff_summary(old.plain(i), new.plain(j))[:3000]}")
        else:
            cands = [(c, s) for c, s in new.search(old.texts[i][:1200], 4, among=[x for x in pool if x is not None]) if s > 0]
            body = ("The old paragraph has no counterpart in the new version. Candidate new paragraphs:\n"
                    + ("\n".join(f"NEW paragraph {new.ids[c]} (page {new.nodes[c].page_start}):\n{new.texts[c][:CLIP]}" for c, _ in cands) or "(none)"))
        blocks.append(f"{head}\nRequirements derived from it:\n{rq}\n{body}")
        covered.append({"old": old.ids[i], "kind": m.kind, "requirements": [r["id"] for r in reqs]})
    added = [m for m in rows if m.kind == drift.ADDED]
    add_text = "\n\n".join(f"[NEW {new.ids[m.new]} | page {new.nodes[m.new].page_start}]\n{new.texts[m.new][:CLIP]}" for m in added) or "(none)"
    user = (f"Regulation: {reg}, old version {old.label}, new version {new.label}\n\n# Paragraphs that differ\n\n" + ("\n\n".join(blocks) or "(none)")
            + f"\n\n# New paragraphs with no old counterpart\n\n{add_text}\n\nAnswer.")
    return user, covered


# --------------------------------------------------------------------------------------------------------------------------- provider
class PacedConnection(http.client.HTTPSConnection):
    """HTTPS with the request written in small pieces and a pause after each. On this machine's network path a request over about 15 KB
    is lost when its packets arrive back to back (the server waits 19 s and closes the connection); eval/xprovider.py's small segments
    alone did not get a 25 KB prompt through, 10 ms between 900-byte writes does."""
    SEGMENT, PAUSE = 900, 0.01

    def connect(self) -> None:
        super().connect()
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send(self, data) -> None:
        if isinstance(data, (bytes, bytearray)):
            for i in range(0, len(data), self.SEGMENT):
                super().send(data[i:i + self.SEGMENT])
                time.sleep(self.PAUSE)
        else:
            super().send(data)


class Provider:
    """DeepSeek through eval/xprovider.py's request and reply helpers (thinking off, JSON object), over a paced connection."""

    def __init__(self, timeout: float = 900.0):
        import xprovider as xp
        self.xp, self.timeout = xp, timeout
        xp.load_env()
        self.model = os.environ.get("LLM_MODEL", "").strip()
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def post(self, url: str, headers: dict, body: dict) -> dict:
        data, delay = json.dumps(body).encode("utf-8"), 5
        parts = urllib.parse.urlsplit(url)
        for attempt in range(4):
            conn = PacedConnection(parts.hostname, parts.port or 443, timeout=self.timeout)
            try:
                conn.request("POST", parts.path, body=data, headers={"Content-Type": "application/json", **headers})
                response = conn.getresponse()
                raw = response.read()
                if response.status < 400:
                    return json.loads(raw.decode("utf-8"))
                if response.status not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise SystemExit(f"error: {url} answered {response.status}: {raw[:300].decode('utf-8', 'replace')}")
            except (OSError, http.client.HTTPException) as error:
                if attempt == 3:
                    raise SystemExit(f"error: {url} not reachable: {error!r}") from None
            finally:
                conn.close()
            time.sleep(delay)
            delay *= 3
        raise SystemExit("error: no answer")

    def ask(self, system: str, user: str) -> tuple[dict, dict]:
        url, headers, body = self.xp.request_for("llm", self.model, system, user, None, thinking=False)
        answer = self.post(url, headers, body)
        text = self.xp.reply_text("llm", answer)
        u = answer.get("usage") or {}
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += u.get("completion_tokens", 0)
        return self.xp.read_json(text), {"text": text, "usage": u, "model": answer.get("model")}


# --------------------------------------------------------------------------------------------------------------------------- build
def to_requirements(reg: str, old, rows, reply: dict) -> tuple[list[dict], list[str]]:
    by_key = {old.key(m.old): m.old for m in rows if m.old is not None}
    out, log = [], []
    order = {old.key(m.old): k for k, m in enumerate(rows) if m.old is not None}
    items = [x for x in reply.get("requirements", []) if isinstance(x, dict) and str(x.get("text", "")).strip()]
    items = [x for x in items if label_key(x.get("paragraph")) in by_key or log.append(f"unknown paragraph {x.get('paragraph')!r}")]
    items.sort(key=lambda x: order[label_key(x["paragraph"])])  # stable: the model's order inside a paragraph is kept
    for k, x in enumerate(items, 1):
        i = by_key[label_key(x["paragraph"])]
        out.append({"id": f"R-{k:03d}", "text": " ".join(str(x["text"]).split()),
                    "source": {"regulation": reg, "page": old.nodes[i].page_start, "paragraph": old.ids[i]}})
    return out, log


def to_changes(reg, old, new, rows, requirements, reply: dict, window: list[str]) -> tuple[list[dict], list[str]]:
    """The model's decisions, checked against the alignment, with the reasons built in code."""
    log: list[str] = []
    by_id = {r["id"]: r for r in requirements}
    match_of = {old.key(m.old): m for m in rows if m.old is not None}
    out, seen = [], set()
    for c in reply.get("changes", []):
        kind, rid = c.get("change"), c.get("requirement_id")
        if kind in ("modified", "removed"):
            r = by_id.get(rid)
            if r is None or rid in seen:
                log.append(f"dropped {kind} {rid}: unknown or repeated id")
                continue
            m = match_of.get(label_key(r["source"]["paragraph"]))
            if m is None or m.kind in (drift.SAME, drift.RENUMBERED):
                log.append(f"dropped {kind} {rid}: its paragraph {r['source']['paragraph']} has the same text in the new version")
                continue
            seen.add(rid)
            i = m.old
            if kind == "removed":
                out.append({"requirement_id": rid, "change": "removed",
                            "reason": drift.removed_reason(reg, new.label, old.ids[i], r["text"])})
                continue
            text = " ".join(str(c.get("new_text") or "").split())
            if not text or text == r["text"]:
                log.append(f"dropped modified {rid}: no new wording")
                continue
            j = m.new if m.kind == drift.MODIFIED else new.by_key.get(label_key(c.get("new_paragraph")))
            if j is None:
                log.append(f"dropped modified {rid}: new paragraph {c.get('new_paragraph')!r} is not in the new version")
                continue
            former = old.ids[i] if old.key(i) != new.key(j) else None
            out.append({"requirement_id": rid, "change": "modified", "new_text": text,
                        "reason": drift.modified_reason(reg, new.label, new.ids[j], former, old.plain(i), new.plain(j)),
                        "source": {"page": new.nodes[j].page_start, "paragraph": new.ids[j]}})
        elif kind == "added":
            text = " ".join(str(c.get("new_text") or "").split())
            j = new.by_key.get(label_key(c.get("new_paragraph")))
            if not text or j is None:
                log.append(f"dropped added {str(c.get('new_text'))[:50]!r}: no text or unknown paragraph {c.get('new_paragraph')!r}")
                continue
            if not in_window(new.nodes[j], window):
                log.append(f"dropped added at {new.ids[j]}: outside the window")
                continue
            out.append({"requirement_id": None, "change": "added", "new_text": text,
                        "reason": drift.added_reason(reg, new.label, new.ids[j], new.plain(j)),
                        "source": {"page": new.nodes[j].page_start, "paragraph": new.ids[j]}})
        else:
            log.append(f"dropped unknown change {kind!r}")
    return out, log


def build_case(case: dict, provider: Provider | None, send: bool) -> dict | None:
    reg = case["regulation"]
    entry, old, new = load_pair(reg)
    matches = drift.align(old, new)
    rows = window_matches(old, new, matches, case["window"])
    n_old = sum(1 for m in rows if m.old is not None)
    counts = drift.counts(rows)
    print(f"{case['id']}: {reg} {old.label}->{new.label} window {case['window']}: {n_old} old nodes, {counts}")
    user1 = old_user(reg, old, rows)
    if not send or provider is None:
        print(f"  call 1 would send {len(SYSTEM_OLD) + len(user1):,} characters")
        return None
    folder = OUT / case["id"]
    folder.mkdir(parents=True, exist_ok=True)
    raw1_obj, raw1 = provider.ask(SYSTEM_OLD, user1)
    requirements, log1 = to_requirements(reg, old, rows, raw1_obj)
    print(f"  {len(requirements)} requirements over {len({r['source']['paragraph'] for r in requirements})} paragraphs; log {log1}")
    user2, covered = new_user(reg, old, new, rows, requirements)
    print(f"  call 2 sends {len(SYSTEM_NEW) + len(user2):,} characters over {len(covered)} changed paragraphs")
    raw2_obj, raw2 = provider.ask(SYSTEM_NEW, user2)
    changes, log2 = to_changes(reg, old, new, rows, requirements, raw2_obj, case["window"])
    c = {k: sum(1 for x in changes if x["change"] == k) for k in ("modified", "removed", "added")}
    print(f"  changes {c}; dropped {len(log2)}")
    write_case(case, folder, entry, old, new, rows, requirements, changes, raw1, raw2, covered, log1 + log2, c)
    return c


def write_case(case, folder, entry, old, new, rows, requirements, changes, raw1, raw2, covered, log, c):
    reg = case["regulation"]
    pair = {"regulation": reg, "base_version": old.label, "latest_version": new.label,
            "base_pdf": f"regulations/data/{corpus.slug(reg)}/base/{corpus.pdf_path(entry, 'base').name}",
            "latest_pdf": f"regulations/data/{corpus.slug(reg)}/latest/{corpus.pdf_path(entry, 'latest').name}",
            "window": case["window"], "trap": case["trap"]}
    (folder / "pair.json").write_text(json.dumps(pair, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (folder / "requirements_old.json").write_text(json.dumps(requirements, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    expected = {"team_id": TEAM, "case_id": case["id"], "changes": changes}
    (folder / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (folder / "provider.json").write_text(json.dumps({"provider": "llm (DeepSeek)", "model": raw1.get("model"), "written": time.strftime("%Y-%m-%d"),
                                                      "call_1_requirements": raw1, "call_2_changes": raw2}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = drift.counts(rows)
    key_of = {r["id"]: r for r in requirements}
    flagged = {x["requirement_id"] for x in changes if x.get("requirement_id")}
    lines = [f"# {case['id']}", "", f"{reg}, base {old.label} -> latest {new.label}; window: sections {', '.join(case['window'])}.", "",
             f"What changed: {case['about']}", "", f"Trap: {case['trap']}.", "",
             f"Alignment of the window (src/ai_agent/drift.py): {counts}.", "",
             f"Old requirements: {len(requirements)}; gold changes: {c['modified']} modified, {c['removed']} removed, {c['added']} added "
             f"({len(flagged)} of {len(requirements)} old requirements flagged).", "",
             "The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.", ""]
    if log:
        lines += ["Dropped or logged by the sanity check:", ""] + [f"- {x}" for x in log] + [""]
    lines += ["Changed paragraphs sent to the provider:", ""] + [f"- {x['old']} ({x['kind']}): {', '.join(x['requirements']) or 'no requirement'}" for x in covered] + [""]
    (folder / "notes.md").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------------------- commands
def cmd_scan(_args) -> int:
    for e in corpus.load_index():
        reg = e["regulation"]
        if not (corpus.pdf_path(e, "base") and corpus.pdf_path(e, "latest")):
            continue
        entry, old, new = load_pair(reg)
        m = drift.align(old, new)
        c = drift.counts(m)
        print(f"{reg:8s} {old.label:>8s}->{new.label:<8s} old {len(old.content):5d} new {len(new.content):5d}  "
              + " ".join(f"{k} {v}" for k, v in c.items()))
    return 0


def cmd_build(args) -> int:
    chosen = [c for c in CASES if not args.ids or c["id"] in args.ids]
    provider = Provider(args.timeout) if args.send else None
    for case in chosen:
        build_case(case, provider, args.send)
    if provider:
        print("DeepSeek usage:", provider.usage)
    return 0


def cmd_check(_args) -> int:
    import subprocess
    rows = []
    for case in CASES:
        folder = OUT / case["id"]
        if not (folder / "expected.json").is_file():
            print(f"{case['id']}: missing")
            continue
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "validate.py"), str(folder / "expected.json"), "--kind", "subgoal",
                            "--requirements-old", str(folder / "requirements_old.json")], capture_output=True, text=True, encoding="utf-8")
        print(f"{case['id']}: {r.stdout.strip() or r.stderr.strip()}")
        pair = json.loads((folder / "pair.json").read_text(encoding="utf-8"))
        reqs = json.loads((folder / "requirements_old.json").read_text(encoding="utf-8"))
        exp = json.loads((folder / "expected.json").read_text(encoding="utf-8"))["changes"]
        n = {k: sum(1 for x in exp if x["change"] == k) for k in ("modified", "removed", "added")}
        rows.append((case, pair, len(reqs), len({r["source"]["paragraph"] for r in reqs}), n))
    write_readme(rows)
    return 0


def write_readme(rows) -> None:
    lines = ["# Drift cases", "",
             "Ten real base -> latest pairs of UN Regulations for the sub-goal \"which requirements derived from the old version change\" "
             "(README.md section 3). Each folder has `pair.json` (regulation, versions, PDFs under regulations/data, the window of sections), "
             "`requirements_old.json` (the requirements an expert would derive from the old window, written by DeepSeek in the format of "
             "subgoal/dev), `expected.json` (the changes, subgoal schema, team_id `synthetic`), `provider.json` (the raw DeepSeek replies) and `notes.md`.", "",
             "Both files were written by a model (DeepSeek, thinking off), not by experts: the decisions were checked against the deterministic "
             "alignment of the two versions (a flagged requirement on a paragraph with the same text is dropped) and the `reason` strings were "
             "built in code from the paragraph diff in the format of subgoal/dev/expected.json. The gold is noisy: use it for insight, and "
             "subgoal/dev for the number that counts.", "",
             "Regenerate: `python eval/drift_cases.py build --send` (needs the LLM_* lines of .env), check: `python eval/drift_cases.py check`.", "",
             "| Case | Regulation | Versions | Window | Old reqs (paragraphs) | Modified | Removed | Added | Trap |",
             "|---|---|---|---|---|---|---|---|---|"]
    for case, pair, nreq, npar, n in rows:
        lines.append(f"| {case['id']} | {pair['regulation']} | {pair['base_version']} -> {pair['latest_version']} | {', '.join(pair['window'])} | "
                     f"{nreq} ({npar}) | {n['modified']} | {n['removed']} | {n['added']} | {case['trap']} |")
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan")
    b = sub.add_parser("build")
    b.add_argument("ids", nargs="*")
    b.add_argument("--send", action="store_true")
    b.add_argument("--timeout", type=float, default=900.0)
    sub.add_parser("check")
    args = parser.parse_args(argv)
    return {"scan": cmd_scan, "build": cmd_build, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
