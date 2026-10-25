"""Stage 5: from candidates to the submission file (spec/proposal.md A4.6).

The policy is filters on the labels the extractor put on each candidate, and every dropped candidate keeps the rule that dropped it:
  modality    only obligations (not permissions, exemptions, definitions, scope)
  addressee   only what constrains the product (the device, or the pass criterion a test judges it by); not test set-up, the applicant's
              paperwork or the authority's actions
  applies     certain, likely and possible; not unlikely (a variant the profile does not have)
  kind        not conformity-of-production (the manufacturer's and the authority's control of the series, not a property of the product)
and two checks on groups of candidates, after the per-candidate rules:
  regulation  a regulation none of whose emitted candidates is `certain`, picked at less than high confidence, is probably not about the product
  page        a page whose emitted candidates are all `possible` and at most three is a stray hit, not a section the experts would cite
The thresholds were measured against the F2/5 bar of spec/precision.md 4.5 on one case; spec/finding/precision-tuning.md has the bins and what
was rejected. `baseline-v1` is the policy before that tuning (the first three filters only); AI_AGENT_POLICY=baseline-v1 selects it.
`precision-v2`, the default, leaves the regulation check off: on a text-and-image run of the dev case it dropped a correct horizontal regulation
whose few `certain` grades did not survive sampling (strict F2 0.62 to 0.53), while the wrong one it removes costs about 0.01. AI_AGENT_POLICY=
precision-v1 turns it back on.
The citation of a requirement (regulation, base version, page, paragraph) is written here from the node, never taken from the model.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from .config import ROOT


@dataclass(frozen=True)
class Policy:
    name: str = "precision-v2"
    modality: frozenset = frozenset({"obligation"})
    addressee: frozenset = frozenset({"product", "product_via_test"})
    applies: frozenset = frozenset({"certain", "likely", "possible"})
    drop_kinds: frozenset = frozenset({"conformity-of-production"})
    drop_kind_applies: frozenset = frozenset()   # (kind, applies) pairs dropped: a kind kept only when the model is `certain` about it
    max_per_node: int = 0              # keep at most this many emitted candidates per node, best grade first, then in extraction order (0 = no cap)
    regulation_check: bool = False     # drop a regulation with no emitted `certain` candidate unless it was selected at high confidence
    sparse_possible_pages: int = 3     # drop a page whose emitted candidates are all `possible` and at most this many (0 = off)


BASELINE_POLICY = Policy(name="baseline-v1", drop_kinds=frozenset(), regulation_check=False, sparse_possible_pages=0)
PRECISION_V1 = Policy(name="precision-v1", regulation_check=True)
CAP3 = Policy(name="cap3-experiment", max_per_node=3)   # tried on the synthetic split, rejected (spec/finding/synthetic-tuning.md)
POLICIES = {p.name: p for p in (Policy(), PRECISION_V1, BASELINE_POLICY, CAP3)}
DEFAULT_POLICY = POLICIES[os.environ.get("AI_AGENT_POLICY", "precision-v2")]
MAX_TEXT = 2000


def policy_summary(policy: Policy) -> dict:
    """The policy as plain JSON (for run.json)."""
    return {k: (sorted(v) if isinstance(v, frozenset) else v) for k, v in vars(policy).items()}


def decide(candidate: dict, policy: Policy) -> str:
    """'emitted', or 'dropped:<rule>=<value>' (a candidate that did not ground in its node keeps its 'rejected:<why>')."""
    if str(candidate.get("status", "")).startswith("rejected"):
        return candidate["status"]
    for rule in ("modality", "addressee", "applies"):
        if candidate.get(rule) not in getattr(policy, rule):
            return f"dropped:{rule}={candidate.get(rule)}"
    if candidate.get("kind") in policy.drop_kinds:
        return f"dropped:kind={candidate.get('kind')}"
    if (candidate.get("kind"), candidate.get("applies")) in policy.drop_kind_applies:
        return f"dropped:kind={candidate.get('kind')}/{candidate.get('applies')}"
    return "emitted"


def fit(text: str) -> str:
    """The platform allows 2,000 characters; cut longer text at the last sentence end that fits."""
    if len(text) <= MAX_TEXT:
        return text
    cut = text[:MAX_TEXT - 1]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:end + 1] if end > MAX_TEXT // 2 else cut).rstrip()


def apply_policy(candidates: list[dict], policy: Policy = DEFAULT_POLICY, confidence: dict[str, str] | None = None) -> list[dict]:
    """Set `status` on every candidate. Exact repeats (same regulation, same words) after the first are dropped as duplicates; then the regulation
    and page checks. `confidence` maps a regulation to the confidence it was selected with (high, medium, low); None skips the regulation check,
    and a regulation missing from it counts as medium."""
    seen: set[tuple[str, str]] = set()
    for c in candidates:
        c["status"] = decide(c, policy)
        if c["status"] == "emitted":
            key = (c["regulation"], re.sub(r"\W+", " ", c["text"].casefold()).strip())
            if key in seen:
                c["status"] = "dropped:duplicate"
            seen.add(key)
    if policy.max_per_node:
        cap_nodes(candidates, policy.max_per_node)
    if policy.regulation_check and confidence is not None:
        check_regulations(candidates, confidence)
    if policy.sparse_possible_pages:
        check_pages(candidates, policy.sparse_possible_pages)
    return candidates


def emitted(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if c["status"] == "emitted"]


def cap_nodes(candidates: list[dict], most: int) -> None:
    """One paragraph or table is cited once by the experts, usually with one requirement (1.1 to 1.4 per cited paragraph on the synthetic
    cases); a node the extractor split into many pieces is over-split. Past the `most` best-graded candidates, further ones are dropped."""
    grade = {"certain": 0, "likely": 1, "possible": 2}
    nodes: dict[tuple, list[dict]] = defaultdict(list)
    for c in emitted(candidates):
        nodes[(c["regulation"], c["node_idx"])].append(c)
    for items in nodes.values():
        items.sort(key=lambda c: (grade.get(c["applies"], 3), c.get("ordinal", 0)))
        for c in items[most:]:
            c["status"] = "dropped:node=over_split"


def check_regulations(candidates: list[dict], confidence: dict[str, str]) -> None:
    """A regulation with no `certain` emitted candidate that was not picked at high confidence is dropped whole. It is never applied to every
    regulation at once: with no regulation left there is nothing to say."""
    by_reg: dict[str, list[dict]] = defaultdict(list)
    for c in emitted(candidates):
        by_reg[c["regulation"]].append(c)
    weak = [reg for reg, items in by_reg.items() if confidence.get(reg, "medium") != "high" and not any(c["applies"] == "certain" for c in items)]
    if len(weak) == len(by_reg):
        return
    for reg in weak:
        for c in by_reg[reg]:
            c["status"] = "dropped:regulation=no_certain"


def check_pages(candidates: list[dict], most: int) -> None:
    """A page (of a regulation) whose emitted candidates are all `possible`, and at most `most` of them, is dropped."""
    pages: dict[tuple, list[dict]] = defaultdict(list)
    for c in emitted(candidates):
        pages[(c["regulation"], c["version"], int(c["page"]))].append(c)
    for items in pages.values():
        if len(items) <= most and all(c["applies"] == "possible" for c in items):
            for c in items:
                c["status"] = "dropped:page=only_possible"


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
