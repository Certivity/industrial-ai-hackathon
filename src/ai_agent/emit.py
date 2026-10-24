"""Stage 5: from candidates to the submission file (spec/proposal.md A4.6).

The policy is three filters on the labels the extractor put on each candidate, and every dropped candidate keeps the rule that dropped it:
  modality    only obligations (not permissions, exemptions, definitions, scope)
  addressee   only what constrains the product (the device, or the pass criterion a test judges it by); not test set-up, the applicant's
              paperwork or the authority's actions
  applies     certain, likely and possible; not unlikely (a variant the profile does not have)
`unlikely` is the threshold to tune: spec/precision.md 4.5 measures the match rate of each bin against the F2/5 bar before moving it.
The citation of a requirement (regulation, base version, page, paragraph) is written here from the node, never taken from the model.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from functools import lru_cache

from .config import ROOT


@dataclass(frozen=True)
class Policy:
    modality: frozenset = frozenset({"obligation"})
    addressee: frozenset = frozenset({"product", "product_via_test"})
    applies: frozenset = frozenset({"certain", "likely", "possible"})


DEFAULT_POLICY = Policy()
MAX_TEXT = 2000


def decide(candidate: dict, policy: Policy) -> str:
    """'emitted', or 'dropped:<rule>=<value>' (a candidate that did not ground in its node keeps its 'rejected:<why>')."""
    if str(candidate.get("status", "")).startswith("rejected"):
        return candidate["status"]
    for rule in ("modality", "addressee", "applies"):
        if candidate.get(rule) not in getattr(policy, rule):
            return f"dropped:{rule}={candidate.get(rule)}"
    return "emitted"


def fit(text: str) -> str:
    """The platform allows 2,000 characters; cut longer text at the last sentence end that fits."""
    if len(text) <= MAX_TEXT:
        return text
    cut = text[:MAX_TEXT - 1]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:end + 1] if end > MAX_TEXT // 2 else cut).rstrip()


def apply_policy(candidates: list[dict], policy: Policy = DEFAULT_POLICY) -> list[dict]:
    """Set `status` on every candidate. Exact repeats (same regulation, same words) after the first are dropped as duplicates."""
    seen: set[tuple[str, str]] = set()
    for c in candidates:
        c["status"] = decide(c, policy)
        if c["status"] == "emitted":
            key = (c["regulation"], re.sub(r"\W+", " ", c["text"].casefold()).strip())
            if key in seen:
                c["status"] = "dropped:duplicate"
            seen.add(key)
    return candidates


def build_submission(candidates: list[dict], regulation_order: list[str], case_id: str, team_id: str) -> tuple[dict, list[dict]]:
    """(submission, trace). Requirements are ordered by regulation (in the order they were chosen), then document order of the node, then
    the order the extractor listed them."""
    rank = {reg: k for k, reg in enumerate(regulation_order)}
    kept = sorted((c for c in candidates if c["status"] == "emitted"),
                  key=lambda c: (rank.get(c["regulation"], 99), c["node_idx"], c.get("ordinal", 0)))
    width = max(3, len(str(len(kept))))
    requirements, trace = [], []
    for k, c in enumerate(kept, 1):
        rid = f"R-{k:0{width}d}"
        requirements.append({"id": rid, "text": fit(c["text"]),
                             "source": {"regulation": c["regulation"], "version": c["version"], "page": int(c["page"]), "paragraph": c["paragraph"]}})
        trace.append({"id": rid, **{key: c.get(key) for key in ("regulation", "node", "paragraph", "page", "quote", "quote_match", "reassigned", "kind",
                                                                 "addressee", "applies", "why", "chunk")}})
    return {"team_id": team_id, "case_id": case_id, "requirements": requirements}, trace


@lru_cache(maxsize=None)
def _validator():
    """tools/validate.py, loaded from its file (it is the platform's own check). It must be in sys.modules before it runs: its dataclass
    looks its module up there."""
    spec = importlib.util.spec_from_file_location("hackathon_validate", ROOT / "tools" / "validate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_submission(submission: dict, strict: bool = True) -> list[str]:
    """The problems tools/validate.py finds in the submission (empty when it is valid); a note when the check could not run."""
    try:
        module = _validator()
        index = module.load_index(ROOT / "regulations" / "index.json")
        return [str(p) for p in module.validate(submission, "main", index=index, strict=strict)]
    except ModuleNotFoundError as error:
        return [f"validation skipped: {error}"]
