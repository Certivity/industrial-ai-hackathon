"""Settings of the agent. The Anthropic key and model come from AI_AGENT_KEY and AI_AGENT_MODEL, read from the environment or from
the git-ignored .env in the repository root (the environment wins, as in eval/xprovider.py). The key is never printed or logged.

    AI_AGENT_KEY      required, an Anthropic API key (sk-ant-...)
    AI_AGENT_MODEL    the model id; defaults to claude-sonnet-5-5
    AI_AGENT_FALLBACKS  "default" (the default) asks the API to retry a policy decline on a fallback model; "off" disables it
    AI_AGENT_SELECT   "v1" (the default), "v2", or "v3": the regulation selection (spec/finding/selection-tuning.md); v3 = the v2 selection as a
                      shortlist, each member then verified against the verbatim scope text of the regulation (verify.py)
    AI_AGENT_VET      "v1" or "v2": the citation-hop vetting prompt (default v1; v2 when AI_AGENT_SELECT=v3, whose verification filters the hop)
    AI_AGENT_MAX_COST_USD, AI_AGENT_WORKERS, AI_AGENT_TEAM_ID   optional
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "claude-sonnet-5-5"
# Effort per stage (output_config.effort). Sonnet 5.5 cannot switch thinking off, so effort is the only dial, and it matters a great deal for
# extraction: on UN R175 (eval/bench_extract.py) the same prompt and chunks gave 18 obligations at "medium" (one chunk of 110 nodes returned a
# single one) and 167 at "high", with recall against the experts going from 1% to 71%. "medium" is enough where the answer is short: the profile,
# the section walks (they reached every expected paragraph) and the judge.
DEFAULT_EFFORT = {"vision": "high", "components": "medium", "profile": "medium", "regulations": "high", "sections": "medium", "verify": "medium", "obligations": "high", "judge": "medium"}


class MissingKey(RuntimeError):
    pass


def load_env(path: Path = ROOT / ".env") -> None:
    """Put the KEY=value lines of a .env file into the environment unless a variable is already set there. Handles CRLF and quotes."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.removeprefix("export ").strip()
        if name:
            os.environ.setdefault(name, value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL
    team_id: str = "team-00"
    effort: dict = field(default_factory=lambda: dict(DEFAULT_EFFORT))
    max_cost_usd: float = 25.0  # the run stops before the first call that would start above this
    workers: int = 5  # concurrent requests (walkers, extraction chunks)
    fallbacks: bool = True  # server-side fallback on a policy decline (beta server-side-fallback-2026-07-01)
    eager_tools: bool = True  # eager_input_streaming on client tools; every tool input is validated in code either way
    cache_dir: Path | None = ROOT / "runs" / "_llm_cache"  # replay cache of identical requests; None switches it off
    max_regulations: int = 8
    chunk_chars: int = 24_000  # text of one extraction call, about 7K tokens: 12K and 40K characters gave the same recall at high effort
    walk_turns: int = 28  # tool turns of one section walk
    vet: str = "v1"  # citation-hop vetting prompt: "v1" (default) or "v2" recall-oriented (AI_AGENT_VET)
    select: str = "v1"  # regulation selection prompt: "v1" strict (default), "v2" recall-oriented, "v3" shortlist then verify (AI_AGENT_SELECT)

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        load_env()
        key = os.environ.get("AI_AGENT_KEY", "").strip()
        select = os.environ.get("AI_AGENT_SELECT", "").strip().lower() or cls.select
        if not key:
            raise MissingKey("AI_AGENT_KEY is not set: add AI_AGENT_KEY=sk-ant-... (and AI_AGENT_MODEL=claude-sonnet-5-5) to the .env in the "
                             "repository root, or export them")
        settings = cls(
            api_key=key,
            model=os.environ.get("AI_AGENT_MODEL", "").strip() or DEFAULT_MODEL,
            team_id=os.environ.get("AI_AGENT_TEAM_ID", "").strip() or "team-00",
            max_cost_usd=float(os.environ.get("AI_AGENT_MAX_COST_USD", "") or cls.max_cost_usd),
            workers=int(os.environ.get("AI_AGENT_WORKERS", "") or cls.workers),
            vet=os.environ.get("AI_AGENT_VET", "").strip().lower() or ("v2" if select == "v3" else cls.vet),
            select=select,
            fallbacks=os.environ.get("AI_AGENT_FALLBACKS", "default").strip().lower() not in ("off", "0", "false", "no"),
        )
        return replace(settings, **overrides) if overrides else settings

    def with_effort(self, **levels: str) -> "Settings":
        return replace(self, effort={**self.effort, **levels})
