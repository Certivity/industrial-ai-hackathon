"""The whole chain for one case: spec.md and/or exploded view -> (vision) -> profile -> regulations -> section walks -> citation hop -> obligations -> submission.

    from ai_agent.pipeline import run_case
    from ai_agent.config import Settings
    result = run_case("cases/dev-rear-lamp", Settings.from_env())

Everything a stage produces is written to runs/<case>/<run id>/ as it is produced (profile.json, regulations.json, sections.json, walk-*.json,
candidates.json, submission.json, trace.json, usage.json, calls.jsonl, run.json), so a run can be read, scored and compared afterwards. The
case folder is read for its text spec and image only (inputs.py). The expected answer of a case (expected.json) is never opened here: it belongs to the benchmark.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from regcomp import corpus

from .catalog import Catalog
from .config import ROOT, Settings
from .components import build_component_map
from .inputs import find_inputs
from .emit import DEFAULT_POLICY, Policy, apply_policy, build_submission, policy_summary, validate_submission
from .llm import LLM, BudgetExceeded, stderr_log
from .obligations import extract_all
from .profile import build_profile, profile_text
from .regulations import select_regulations, vet_cited
from .sections import WalkResult, transcript, walk
from .store import RegGraph
from .verify import accepted_items, scope_text, shortlist_union, verify_all


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


STOP_STAGES = ("profile", "regulations", "sections")


def upper_bound_submission(graphs: dict[str, RegGraph], walks: dict[str, WalkResult], regs: list[str], case_id: str, team_id: str) -> dict:
    """A pseudo-submission that cites every selected content node once, as the emitter would cite it (regulation, version, the node's
    paragraph label, its first page). tools/score_local.py scores it: the regulation level is exact, the page level is a recall ceiling
    (nothing is dropped by extraction or policy) and a lower bound of the precision. Nodes without a label are left out."""
    requirements = []
    for reg in regs:
        graph = graphs[reg]
        for i in sorted(walks[reg].nodes):
            node = graph.nodes[i]
            if graph.is_content(i) and node.label:
                requirements.append({"id": f"R-{len(requirements) + 1:05d}", "text": f"Upper bound: {reg} {node.label}",
                                     "source": {"regulation": reg, "version": graph.version, "page": int(node.page_start), "paragraph": node.label}})
    return {"team_id": team_id, "case_id": case_id, "requirements": requirements}


@dataclass
class RunResult:
    run_dir: Path
    submission: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    regulations: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    ledger: dict = field(default_factory=dict)


def walk_all(llm: LLM, graphs: dict[str, RegGraph], regs: list[str], profile_md: str, settings: Settings, run_dir: Path,
             failures: list[dict], log) -> dict[str, WalkResult]:
    results: dict[str, WalkResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, settings.workers)) as pool:
        futures = {pool.submit(walk, llm, graphs[reg], profile_md, settings): reg for reg in regs}
        for future in as_completed(futures):
            reg = futures[future]
            try:
                results[reg] = future.result()
            except BudgetExceeded:
                raise
            except Exception as error:
                failures.append({"stage": "sections", "regulation": reg, "error": f"{type(error).__name__}: {error}"})
                log(f"[sections] {reg} failed: {error}")
                continue
            r = results[reg]
            save(run_dir / f"walk-{corpus.slug(reg)}.json", {**r.summary(graphs[reg]), "transcript": transcript(r.messages)})
            log(f"[sections] {reg}: {'ok' if r.finished else 'NOT FINISHED (' + r.reason + ')'} in {r.turns} turns, "
                f"{len(r.selections)} selections, {sum(1 for i in r.nodes if graphs[reg].is_content(i))} provisions")
    return results


def cited_by_walks(graphs: dict[str, RegGraph], walks: dict[str, WalkResult], taken: set[str], catalog: Catalog) -> dict[str, dict]:
    """Regulations of the index that the selected text cites, mapped to their successor, not yet chosen."""
    cited: dict[str, dict] = {}
    for reg, result in walks.items():
        for target, row in graphs[reg].cited_in(result.nodes).items():
            if target not in catalog.cards:
                continue
            successor = catalog.successor(target)
            if successor in taken or successor == reg:
                continue
            entry = cited.setdefault(successor, {"count": 0, "nodes": [], "snippet": "", "by": [], "cited_as": []})
            entry["count"] += row["count"]
            entry["nodes"] += [f"{reg} {n}" for n in row["nodes"]]
            entry["by"] = sorted({*entry["by"], reg})
            entry["cited_as"] = sorted({*entry["cited_as"], target})
            entry["snippet"] = entry["snippet"] or row["snippet"]
    return cited


def run_case(case_dir: str | Path, settings: Settings, run_dir: Path | None = None, log=stderr_log, llm: LLM | None = None,
             policy: Policy = DEFAULT_POLICY, catalog: Catalog | None = None, use_image: bool = True,
             image: str | Path | None = None, component_map: bool | None = None, use_text: bool = True,
             stop_after: str | None = None) -> RunResult:
    if stop_after is not None and stop_after not in STOP_STAGES:
        raise ValueError(f"stop_after must be one of {STOP_STAGES}, not {stop_after!r}")
    case_dir = Path(case_dir)
    inputs = find_inputs(case_dir, use_text=use_text, use_image=use_image, image=image)  # the text spec and/or the image: the only files of the case that are read
    spec_text = inputs.read_text()
    case_id = case_dir.resolve().name
    run_dir = Path(run_dir) if run_dir else ROOT / "runs" / case_id / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    llm = llm or LLM(settings, log=log, call_log=run_dir / "calls.jsonl")
    result = RunResult(run_dir)
    started = time.time()
    log(f"[run] {case_id} -> {run_dir} (model {settings.model}, fallbacks {'on' if settings.fallbacks else 'off'})")
    try:
        # 1. profile (a drawing is read first; its facts join the text's)
        log(f"[inputs] {inputs.describe()}")
        facts = None
        if inputs.image_path is not None:
            from .vision import read_drawing
            facts = read_drawing(llm, inputs.image_path, settings, run_dir, log)
            save(run_dir / "vision.json", facts)
        result.profile = build_profile(llm, spec_text, facts)
        profile_md = profile_text(result.profile, facts)
        save(run_dir / "profile.json", result.profile)
        (run_dir / "profile.md").write_text(profile_md, encoding="utf-8")
        if stop_after == "profile":
            log("[run] --stop-after profile: stopping before the regulations")
            return result

        # 2. regulations
        catalog = catalog or Catalog().load(log)
        chosen = select_regulations(llm, catalog, profile_md, settings.max_regulations, settings.select)
        save(run_dir / "regulations.json", chosen)
        regs = [s["regulation"] for s in chosen["selected"]]
        log(f"[regulations] chosen: {', '.join(regs) or 'none'}" + (f" (redirected {chosen['redirects']})" if chosen["redirects"] else ""))

        graphs: dict[str, RegGraph] = {}
        rejected_by_verify: set[str] = set()
        if settings.select == "v3":  # shortlist (the v2 selection), then verify each against the verbatim scope text
            for reg in regs:  # PyMuPDF is not thread-safe: parse here
                graphs[reg] = RegGraph(reg)
            decisions = verify_all(llm, catalog, profile_md, {reg: scope_text(graphs[reg].nodes) for reg in regs}, settings.workers)
            chosen = {**chosen, "shortlist": chosen["selected"], "verification": decisions, "selected": accepted_items(chosen["selected"], decisions)}
            save(run_dir / "regulations.json", chosen)
            rejected_by_verify = {reg for reg in regs if not decisions[reg]["accepted"]}
            regs = [s["regulation"] for s in chosen["selected"]]
            log(f"[regulations] verified: kept {', '.join(regs) or 'none'}; dropped {', '.join(sorted(rejected_by_verify)) or 'none'}")

        if stop_after == "regulations":
            result.regulations = regs
            log("[run] --stop-after regulations: stopping before the section walks")
            return result

        # 3. section walks, then one hop along the citations of the selected text
        for reg in regs:  # PyMuPDF is not thread-safe: parse here, walk in threads
            graphs.setdefault(reg, RegGraph(reg))
        walks = walk_all(llm, graphs, regs, profile_md, settings, run_dir, result.failures, log)
        hop: dict = {"cited": {}, "vetted": {}}
        room = settings.max_regulations - len(regs)
        cited = cited_by_walks(graphs, walks, set(regs) | rejected_by_verify, catalog) if room > 0 else {}
        hop["cited"] = cited
        if cited:
            vetted = vet_cited(llm, catalog, profile_md, cited, settings.vet)
            hop["vetted"] = vetted
            added = [item["regulation"] for item in vetted["add"]][:room]
            if settings.select == "v3" and added:  # a vetted citation is a shortlist member too: verify it before walking it
                for reg in added:
                    graphs.setdefault(reg, RegGraph(reg))
                extra = verify_all(llm, catalog, profile_md, {reg: scope_text(graphs[reg].nodes) for reg in added}, settings.workers)
                hop["verification"] = extra
                chosen["verification"].update(extra)
                kept = shortlist_union([], [item for item in vetted["add"] if extra[item["regulation"]]["accepted"]], room)
                chosen["selected"] += accepted_items(kept, extra)
                chosen["shortlist"] += kept
                save(run_dir / "regulations.json", chosen)
                added = [item["regulation"] for item in kept]
            log(f"[regulations] cited by the selected text: {', '.join(sorted(cited))}; added: {', '.join(added) or 'none'}")
            for reg in added:
                graphs.setdefault(reg, RegGraph(reg))
            walks.update(walk_all(llm, graphs, added, profile_md, settings, run_dir, result.failures, log))
            regs += [reg for reg in added if reg in walks]
        save(run_dir / "citation_hop.json", hop)
        regs = [reg for reg in regs if reg in walks]
        result.regulations = regs
        save(run_dir / "sections.json", {reg: walks[reg].summary(graphs[reg]) for reg in regs})
        if stop_after == "sections":
            save(run_dir / "upper_bound.json", upper_bound_submission(graphs, walks, regs, case_id, settings.team_id))
            log("[run] --stop-after sections: stopping before the obligation extraction (upper_bound.json written)")
            return result

        # 4. obligations
        selected_nodes = {reg: walks[reg].nodes for reg in regs if walks[reg].nodes}
        candidates, plan, chunk_failures, chunk_stats = extract_all(llm, graphs, selected_nodes, profile_md, settings.workers, settings.chunk_chars, log)
        result.failures += [{"stage": "obligations", **f} for f in chunk_failures]
        save(run_dir / "chunks.json", {"plan": {reg: [{"index": c.index, "nodes": len(c.nodes), "chars": c.chars, "context": c.context} for c in chunks]
                                                for reg, chunks in plan.items()}, "stats": chunk_stats})

        # 5. emit
        apply_policy(candidates, policy, {s["regulation"]: s["confidence"] for s in chosen["selected"]})  # regulations added by a citation hop count as medium
        result.candidates = candidates
        save(run_dir / "candidates.json", candidates)
        result.submission, trace = build_submission(candidates, regs, case_id, settings.team_id)
        result.problems = validate_submission(result.submission)
        save(run_dir / "submission.json", result.submission)
        save(run_dir / "trace.json", trace)
        if facts is not None if component_map is None else component_map:  # component_map.json: on by default when a drawing was read
            try:
                build_component_map(llm, run_dir, case_id, log)
            except BudgetExceeded:
                raise
            except Exception as error:  # a demo artifact: its failure must not lose the run
                result.failures.append({"stage": "components", "error": f"{type(error).__name__}: {error}"})
                log(f"[components] failed: {error}")
        counts = Counter(c["status"].split("=")[0] if c["status"].startswith("dropped") else c["status"] for c in candidates)
        log(f"[emit] {len(candidates)} candidates -> {len(result.submission['requirements'])} requirements; {dict(counts)}; "
            f"validation: {'OK' if not result.problems else result.problems[:3]}")
    finally:
        result.ledger = llm.ledger.summary()
        save(run_dir / "usage.json", result.ledger)
        save(run_dir / "run.json", {
            "case": case_id, "model": settings.model, "effort": settings.effort, "fallbacks": settings.fallbacks, "workers": settings.workers,
            "chunk_chars": settings.chunk_chars, "policy": policy_summary(policy),
            "regulations": result.regulations, "requirements": len(result.submission.get("requirements", [])), "failures": result.failures,
            "validation": result.problems, "seconds": round(time.time() - started), "spent_usd": result.ledger.get("spent_usd"),
            "replayed_usd": result.ledger.get("replayed_usd")})
        pointer = ROOT / "runs" / case_id
        if pointer.is_dir() and stop_after is None:  # a partial run has no submission.json: it must not become the latest run
            (pointer / "latest.txt").write_text(str(run_dir), encoding="utf-8")
    log(f"[run] done in {time.time() - started:.0f}s, spent ${result.ledger['spent_usd']:.2f} "
        f"(+${result.ledger['replayed_usd']:.2f} replayed from the cache)")
    return result
