#!/usr/bin/env python3
"""Run the agent on a case folder: a text spec (spec.md or technical_spec.md), an image (exploded_view.png or any png/jpg/webp), or both.

    python src/ai_agent/run.py cases/dev-rear-lamp
    python src/ai_agent/run.py cases/dev-rear-lamp --no-image         # text only; --image PATH picks the drawing
    python src/ai_agent/run.py cases/dev-rear-lamp --max-cost 10 --workers 4 --effort obligations=low --no-fallbacks

AI_AGENT_KEY (and AI_AGENT_MODEL, default claude-sonnet-5-5) are read from the environment or the git-ignored .env of the repository root.
The files of the run are written to runs/<case>/<run id>/; submission.json is the file to validate (tools/validate.py) and upload.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path[:0] = [str(Path(__file__).resolve().parents[1])]  # src/, for ai_agent and regcomp

from ai_agent.config import MissingKey, Settings  # noqa: E402
from ai_agent.llm import BudgetExceeded  # noqa: E402
from ai_agent.pipeline import run_case  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map a product spec to the requirements of the UN Regulations.")
    parser.add_argument("case", help="a case folder with a text spec (spec.md / technical_spec.md) and/or an image, e.g. cases/dev-rear-lamp")
    parser.add_argument("--no-image", action="store_true", help="ignore the image of the case folder (text only)")
    parser.add_argument("--no-text", action="store_true", help="ignore the text spec of the case folder (image only)")
    parser.add_argument("--image", metavar="PATH", help="use this image (a path, or a file name in the case folder) instead of the one found")
    parser.add_argument("--component-map", action=argparse.BooleanOptionalAction, default=None,
                        help="write component_map.json (component -> regulations, sections, requirements; default: when an image is read)")
    parser.add_argument("--out", help="run folder (default runs/<case>/<timestamp>)")
    parser.add_argument("--max-cost", type=float, help="stop before a call that would start above this many USD")
    parser.add_argument("--workers", type=int, help="concurrent requests")
    parser.add_argument("--effort", action="append", default=[], metavar="STAGE=LEVEL",
                        help="effort of a stage: vision, profile, regulations, sections, obligations, components (low|medium|high|xhigh|max); repeatable")
    parser.add_argument("--no-fallbacks", action="store_true", help="do not ask the API for a server-side fallback on a policy decline")
    parser.add_argument("--no-cache", action="store_true", help="do not replay or store identical requests (runs/_llm_cache)")
    parser.add_argument("--team-id", help="team_id of the submission file")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    overrides: dict = {}
    if args.max_cost is not None:
        overrides["max_cost_usd"] = args.max_cost
    if args.workers:
        overrides["workers"] = args.workers
    if args.no_fallbacks:
        overrides["fallbacks"] = False
    if args.no_cache:
        overrides["cache_dir"] = None
    if args.team_id:
        overrides["team_id"] = args.team_id
    try:
        settings = Settings.from_env(**overrides)
    except MissingKey as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    levels = dict(item.split("=", 1) for item in args.effort)
    settings = settings.with_effort(**levels) if levels else settings
    try:
        result = run_case(Path(args.case), settings, Path(args.out) if args.out else None,
                          use_image=not args.no_image, image=args.image, component_map=args.component_map, use_text=not args.no_text)
    except BudgetExceeded as error:
        print(f"stopped: {error}", file=sys.stderr)
        return 3
    print(f"{len(result.submission['requirements'])} requirements -> {result.run_dir / 'submission.json'}")
    return 1 if result.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
