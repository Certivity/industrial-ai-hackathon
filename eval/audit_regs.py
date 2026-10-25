#!/usr/bin/env python3
"""Blind, pre-registered audit of regulation applicability for the 26 testing/ts-* cases (spec/finding/audited-regulations.md).

  python eval/audit_regs.py build     candidates per case (gold + agent runs + 2 TF-IDF distractors), shuffled; writes the protocol
                                      and the candidate list into testing/_audited_regs.json (no DeepSeek call)
  python eval/audit_regs.py judge     3 samples per candidate with DeepSeek (thinking off), batches of at most 4; resumable
  python eval/audit_regs.py tally     votes -> decisions in testing/_audited_regs.json

The adjudicator never learns which source proposed a candidate, and cases/ is never read. The prompt is fixed in PROTOCOL below.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

OUT = ROOT / "testing" / "_audited_regs.json"
WORK = ROOT / "runs" / "_audit"
RUN_NAMES = ("c2-base", "c2-vet2", "c2-v2")
SEED = 20261025

SYSTEM = """You are a type-approval engineer at a UNECE technical service. You decide, for one product and one UN Regulation at a time, whether the Regulation applies to the product, i.e. whether you would list it in the type-approval test plan for this product.

Rules (fixed):
- Decide only from the product specification and the Regulation text given (card, verbatim scope paragraph, supersession note). Do not use other knowledge about which regulations 'usually' go with such a product.
- A Regulation applies when the product, or a sub-assembly or function of it, falls inside the scope as the scope text prints it, including the vehicle categories the scope names. It does not apply when the scope excludes the product's vehicle category or kind of product.
- Expert convention 1: cite the current regulation, not a superseded one. A Regulation marked SUPERSEDED (its provisions now sit in another Regulation) does not apply; its successor is the one to cite.
- Expert convention 2: a horizontal regulation such as electromagnetic compatibility (UN R10) applies only if the product contains electrical or electronic sub-assemblies (powered electronics, control units, sensors, wiring harnesses with electronics, LED drivers and the like). A purely passive or mechanical product does not trigger it.
- Judge every Regulation of the request separately.
Answer with JSON only: {"decisions": [{"regulation": "<id as given>", "applies": "yes" or "no", "scope_clause": "<short verbatim quote from the scope text that decides it>", "product_part": "<the part or function of the product it concerns, or 'none'>", "reason": "<one line>"}]}"""

PROTOCOL = {
    "name": "blind regulation-applicability audit",
    "written_before_results": True,
    "candidates": "per case (all 26 testing/ts-*): union of (a) regulations of testing/<case>/expected.json, (b) regulations in runs/<case>/{c2-base,c2-vet2,c2-v2}/upper_bound.json, regulations.json selected and citation_hop.json vetted.add (those runs that exist; c2-v2 exists for the 10 tune cases only), (c) 2 distractors: the regulations outside (a)+(b) whose card text (title + scope + contents, runs/_cards) has the highest TF-IDF cosine similarity (sublinear tf, smooth idf, over the 56 cards) with technical_spec.md. Shuffled; the source of a candidate is never shown.",
    "adjudicator": "DeepSeek (LLM_MODEL of .env, deepseek-flash), thinking disabled, temperature 0.7, via eval/xprovider.py request_for/post/reply_text; nothing from cases/ or subgoal/ is sent",
    "input_per_request": "technical_spec.md; for each candidate in the request its card (catalog card_text) + the FULL verbatim scope paragraph 1 and sub-paragraphs (regcomp parse of the base PDF the agent uses) + the supersession note",
    "samples": "3 independent samples per candidate; each sample shuffles the candidates of the case with its own seed and cuts them in batches of at most 4 (one request per batch), so batch-mates differ between samples",
    "decision": "applies when >=2 of 3 votes say yes; contested when the vote is 2-1 either way",
    "seed": SEED,
    "system_prompt": SYSTEM,
    "quality_report": ["distractor false-accept rate", "share of candidates where all 3 samples agree", "15 random decisions read by hand against the scope text (seeded, reported honestly)"],
    "scoring": "eval/score_audited.py: regulation P/R/F1/F2 of a run against the original gold and against the audited positive set (majority yes); page-level diagnostic on regulations both accept; macro mean and sample std over cases, split by testing/_split.json",
    "rules_not_to_change_after_results": True,
}


def load_cards() -> dict:
    files = sorted((ROOT / "runs" / "_cards").glob("cards-*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(files[-1].read_text(encoding="utf-8"))


def catalog():
    from ai_agent.catalog import Catalog
    cat = Catalog(cache_dir=None)
    cat.cards = load_cards()
    return cat


def rj(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------------------------------------------------ candidates
def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z\-]{2,}", text.lower())]


def tfidf_rank(docs: dict[str, str], query: str) -> list[tuple[str, float]]:
    toks = {k: Counter(tokens(v)) for k, v in docs.items()}
    n = len(docs)
    df = Counter(t for c in toks.values() for t in c)
    idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}

    def vec(c: Counter) -> dict:
        v = {t: (1 + math.log(f)) * idf[t] for t, f in c.items() if t in idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    q = vec(Counter(tokens(query)))
    out = []
    for k, c in toks.items():
        d = vec(c)
        out.append((k, sum(x * d.get(t, 0.0) for t, x in q.items())))
    return sorted(out, key=lambda kv: -kv[1])


def full_scope(reg: str) -> str:
    cache = WORK / "scope" / (reg.replace(" ", "_") + ".txt")
    if cache.is_file():
        return cache.read_text(encoding="utf-8")
    from regcomp import corpus
    from regcomp.parse import parse_pdf
    path = corpus.pdf_path(corpus.entry_for(reg), "base")
    nodes = parse_pdf(path, grids=False).nodes
    scope = "\n".join(re.sub(r"\s+", " ", n.body).strip() for n in nodes if n.kind == "para" and not n.scope and n.num[:1] == (1,))
    scope = scope.strip()
    if not scope:  # GTRs have no numbered first section: say so, the card carries the document's first words
        scope = "(no numbered paragraph 1 in this document; see the card)"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(scope, encoding="utf-8")
    return scope


def build() -> None:
    cat = catalog()
    cards = cat.cards
    docs = {r: f"{c['title']} {c['title']} {c['scope']} {c['toc']}" for r, c in cards.items()}
    cases = {}
    for case in sorted(p for p in (ROOT / "testing").glob("ts-*") if p.is_dir()):
        spec = (case / "technical_spec.md").read_text(encoding="utf-8")
        gold = sorted({r["source"]["regulation"] for r in rj(case / "expected.json")["requirements"]})
        agent: dict[str, set] = {}
        for name in RUN_NAMES:
            run = ROOT / "runs" / case.name / name
            if not (run / "upper_bound.json").is_file():
                continue
            regs = {r["source"]["regulation"] for r in rj(run / "upper_bound.json")["requirements"]}
            regs |= {s["regulation"] for s in (rj(run / "regulations.json", {}) or {}).get("selected", [])}
            regs |= {a["regulation"] for a in ((rj(run / "citation_hop.json", {}) or {}).get("vetted", {}) or {}).get("add", [])}
            agent[name] = regs
        union = set(gold).union(*agent.values()) if agent else set(gold)
        dis = [r for r, _ in tfidf_rank(docs, spec) if r not in union][:2]
        cands = sorted(union | set(dis))
        random.Random(f"{SEED}-{case.name}-order").shuffle(cands)
        cases[case.name] = {"candidates": [{"regulation": r} for r in cands],
                            "_sources": {r: [s for s, c in (("gold", set(gold)), ("distractor", set(dis)), *[(k, v) for k, v in agent.items()]) if r in c] for r in cands}}
    bad = {r["regulation"] for c in cases.values() for r in c["candidates"]} - set(cards)
    if bad:
        raise SystemExit(f"no card for {sorted(bad)}")
    for c in cases.values():  # sources are kept apart from the candidate records the adjudicator sees; used only by tally/report
        pass
    OUT.write_text(json.dumps({"protocol": PROTOCOL, "cases": cases}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n = sum(len(c["candidates"]) for c in cases.values())
    print(f"{len(cases)} cases, {n} candidates -> {OUT}")


# ------------------------------------------------------------------------------------------------------------------ judge
def user_prompt(spec: str, regs: list[str], cat) -> str:
    blocks = []
    for r in regs:
        note = f"SUPERSEDED: its provisions are now in {cat.superseded_by(r)}" if cat.superseded_by(r) else "not superseded"
        blocks.append(f"=== {r} ===\n{cat.card_text(r)}\n\nScope paragraph (verbatim):\n{full_scope(r)}\n\nSupersession note: {note}")
    return f"# Product specification\n{spec}\n\n# Regulations to decide (one decision each)\n\n" + "\n\n".join(blocks) + "\n\nAnswer with the JSON object."


def judge(workers: int) -> None:
    import xprovider as xp
    xp.load_env()
    data = json.loads(OUT.read_text(encoding="utf-8"))
    cat = catalog()
    for r in sorted({c["regulation"] for rec in data["cases"].values() for c in rec["candidates"]}):  # PyMuPDF is not thread-safe: parse serially first
        print("scope", r, len(full_scope(r)), flush=True)
    jobs = []
    for case, rec in data["cases"].items():
        spec = (ROOT / "testing" / case / "technical_spec.md").read_text(encoding="utf-8")
        regs = [c["regulation"] for c in rec["candidates"]]
        for k in range(3):
            order = list(regs)
            random.Random(f"{SEED}-{case}-sample{k}").shuffle(order)
            for b in range(0, len(order), 4):
                jobs.append((case, k, b // 4, spec, order[b:b + 4]))
    url_headers = {}
    lock = threading.Lock()
    done = [0]

    def run(job):
        case, k, b, spec, batch = job
        f = WORK / "replies" / f"{case}.s{k}.b{b}.json"
        if f.is_file():
            return
        user = user_prompt(spec, batch, cat)
        url, headers, body = xp.request_for("llm", xp.os.environ["LLM_MODEL"], SYSTEM, user, None, thinking=False)
        body["temperature"] = 0.7
        body["max_tokens"] = 4000
        for attempt in range(3):
            try:
                text = xp.reply_text("llm", xp.post(url, headers, body, 300.0))
                answer = xp.read_json(text)
                got = {d["regulation"]: d for d in answer["decisions"]}
                if set(got) >= set(batch):
                    break
            except (SystemExit, Exception) as e:  # noqa: BLE001
                err = repr(e)[:200]
        else:
            print(f"FAILED {case} s{k} b{b}: {err}")
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"case": case, "sample": k, "batch": batch, "decisions": [got[r] for r in batch]}, ensure_ascii=False, indent=1), encoding="utf-8")
        with lock:
            done[0] += 1
            if done[0] % 10 == 0:
                print(f"{done[0]} requests done", flush=True)

    print(f"{len(jobs)} requests, {sum(1 for j in jobs if not (WORK / 'replies' / f'{j[0]}.s{j[1]}.b{j[2]}.json').is_file())} to send")
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(run, jobs))


# ------------------------------------------------------------------------------------------------------------------ tally
def squash(t: str) -> str:
    return re.sub(r"\W+", "", t.lower())


def tally() -> None:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    for case, rec in data["cases"].items():
        scope_sq = {}
        votes: dict[str, list] = {c["regulation"]: [] for c in rec["candidates"]}
        for f in sorted((WORK / "replies").glob(f"{case}.s*.b*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            for d in r["decisions"]:
                reg = d["regulation"]
                sq = scope_sq.setdefault(reg, squash(full_scope(reg)))
                quote = (d.get("scope_clause") or "").strip()
                votes[reg].append({"sample": r["sample"], "applies": str(d.get("applies", "")).strip().lower().startswith("y"),
                                   "scope_clause": quote, "quote_verbatim": bool(quote) and squash(quote) in sq,
                                   "product_part": d.get("product_part", ""), "reason": d.get("reason", "")})
        for c in rec["candidates"]:
            v = sorted(votes[c["regulation"]], key=lambda x: x["sample"])
            yes = sum(x["applies"] for x in v)
            c["votes"] = v
            c["yes"] = yes
            c["n_votes"] = len(v)
            c["applies"] = yes * 2 > len(v) if len(v) == 3 else yes >= 2
            c["contested"] = len(v) == 3 and yes in (1, 2)
            c["sources"] = rec["_sources"][c["regulation"]]
    data["tally_done"] = True
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("tallied")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["build", "judge", "tally"])
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    {"build": build, "judge": lambda: judge(a.workers), "tally": tally}[a.command]()


if __name__ == "__main__":
    main()
