#!/usr/bin/env python3
"""Run the drift agent: requirements derived from an old version of a regulation + the old and the new PDF in, the changes out.

    python src/ai_agent/run_drift.py --old-pdf OLD.pdf --new-pdf NEW.pdf --requirements-old R.json --out runs/drift/case --max-cost 3
    python src/ai_agent/run_drift.py subgoal/dev --out runs/drift/subgoal-dev
    python src/ai_agent/run_drift.py spec/testing/cases-drift/drift-r156-ota-renumber --out runs/drift/r156

A case folder holds requirements_old.json and either pair.json (spec/testing/cases-drift: regulation, base_pdf, latest_pdf), or old.pdf and
new.pdf, or neither (subgoal/dev: the PDFs are the base and latest version of the regulation the requirements cite, from regulations/data).
No other file of the folder is read. changes.json (subgoal schema) is validated with tools/validate.py; trace.json, usage.json and the
call log are kept next to it. AI_AGENT_KEY comes from the environment or the git-ignored .env, as for run.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from ai_agent import drift  # noqa: E402
from ai_agent.config import MissingKey, Settings  # noqa: E402
from ai_agent.llm import LLM, BudgetExceeded, stderr_log  # noqa: E402
from regcomp import corpus  # noqa: E402


def resolve_case(case: Path, args) -> dict:
    """The inputs of a run: the two PDFs, the requirements file, the regulation and the version labels."""
    folder = Path(case) if case else None
    req_path = Path(args.requirements_old) if args.requirements_old else (folder / "requirements_old.json" if folder else None)
    if req_path is None or not req_path.is_file():
        raise SystemExit("error: --requirements-old (or a case folder with requirements_old.json) is required")
    requirements = json.loads(req_path.read_text(encoding="utf-8"))
    regulation = args.regulation or drift.regulation_of(requirements, None)
    old_pdf, new_pdf = args.old_pdf, args.new_pdf
    old_label, new_label = args.old_version, args.version_label
    if folder is not None and (folder / "pair.json").is_file():
        pair = json.loads((folder / "pair.json").read_text(encoding="utf-8"))
        old_pdf = old_pdf or ROOT / pair["base_pdf"]
        new_pdf = new_pdf or ROOT / pair["latest_pdf"]
        regulation = args.regulation or pair["regulation"]
        old_label, new_label = old_label or pair.get("base_version"), new_label or pair.get("latest_version")
    elif folder is not None and (folder / "old.pdf").is_file() and (folder / "new.pdf").is_file():
        old_pdf, new_pdf = old_pdf or folder / "old.pdf", new_pdf or folder / "new.pdf"
    if not (old_pdf and new_pdf):
        entry = corpus.entry_for(regulation)
        old_pdf, new_pdf = old_pdf or corpus.pdf_path(entry, "base"), new_pdf or corpus.pdf_path(entry, "latest")
        if not (old_pdf and new_pdf):
            raise SystemExit(f"error: no old/new PDF for {regulation}: pass --old-pdf and --new-pdf")
    try:
        entry = corpus.entry_for(regulation)
        old_label = old_label or corpus.version_label(entry, "base") or ""
        new_label = new_label or corpus.version_label(entry, "latest") or ""
    except KeyError:
        old_label, new_label = old_label or "", new_label or ""
    return {"requirements": requirements, "regulation": regulation, "old_pdf": Path(old_pdf), "new_pdf": Path(new_pdf),
            "old_label": old_label, "new_label": new_label}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find which requirements derived from an old version of a regulation change in a new one.")
    parser.add_argument("case", nargs="?", help="a case folder (see the module docstring)")
    parser.add_argument("--old-pdf")
    parser.add_argument("--new-pdf")
    parser.add_argument("--requirements-old", help="requirements_old.json (default: the one of the case folder)")
    parser.add_argument("--regulation", help='e.g. "UN R175": the name used in the reasons (default: from the requirements)')
    parser.add_argument("--version-label", help="label of the new version used in the reasons (default: the latest version of the index)")
    parser.add_argument("--old-version", help="label of the old version")
    parser.add_argument("--case-id", help="case_id of changes.json (default: the folder name)")
    parser.add_argument("--out", required=True, help="run folder: changes.json, trace.json, usage.json")
    parser.add_argument("--max-cost", type=float, default=3.0, help="stop before a call that would start above this many USD (default 3)")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--team-id")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--no-fallbacks", action="store_true")
    parser.add_argument("--no-new-in-modified", action="store_true", help="report as added only the obligations of added paragraphs")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    overrides: dict = {"max_cost_usd": args.max_cost}
    if args.workers:
        overrides["workers"] = args.workers
    if args.team_id:
        overrides["team_id"] = args.team_id
    if args.no_cache:
        overrides["cache_dir"] = None
    if args.no_fallbacks:
        overrides["fallbacks"] = False
    try:
        settings = Settings.from_env(**overrides)
    except MissingKey as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    inputs = resolve_case(Path(args.case) if args.case else None, args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    case_id = args.case_id or (Path(args.case).name if args.case else out.name)
    t0 = time.time()
    old = drift.Version.from_pdf(inputs["old_pdf"], inputs["regulation"], inputs["old_label"])
    new = drift.Version.from_pdf(inputs["new_pdf"], inputs["regulation"], inputs["new_label"])
    llm = LLM(settings, log=stderr_log, call_log=out / "calls.jsonl")
    try:
        result = drift.run_drift(old, new, inputs["requirements"], settings, case_id, inputs["regulation"], llm=llm, log=stderr_log,
                                 new_in_modified=not args.no_new_in_modified)
    except BudgetExceeded as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 3
    (out / "changes.json").write_text(json.dumps(result.changes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "trace.json").write_text(json.dumps(result.trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "usage.json").write_text(json.dumps({**result.cost, "seconds": round(time.time() - t0, 1)}, indent=2) + "\n", encoding="utf-8")

    from validate import validate  # noqa: E402
    problems = validate(result.changes, "subgoal", requirements_old=inputs["requirements"])
    for p in problems:
        print(f"invalid: {p}", file=sys.stderr)
    c = result.trace["counts"]
    print(f"{case_id}: {c['modified']} modified, {c['removed']} removed, {c['added']} added -> {out / 'changes.json'} "
          f"(${result.cost['spent_usd']:.2f} spent, ${result.cost['replayed_usd']:.2f} replayed, {time.time() - t0:.0f}s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
