#!/usr/bin/env python3
"""Offline tests (scripted model, no API) for the appended-sentence convention of the drift agent: `drift.appended_sentences` and the
three `appended` modes of `drift.run_drift` (added | modified | both).   python eval/test_drift_appended.py [name ...]"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from test_ai_agent import SETTINGS, _version  # noqa: E402
from test_parse import run_tests  # noqa: E402

from ai_agent import drift  # noqa: E402
from ai_agent.llm import Ledger  # noqa: E402

OLD = [("5.1", "5.1. The lamp shall emit red light. The lamp shall be marked with the trade name.", 3),
       ("5.2", "5.2. The lamp shall be tested at 20 degrees.", 3)]
EXEMPTION = "The provisions of this paragraph do not apply to type B lamps."
NEW = [("5.1", "5.1. The lamp shall emit red light. The lamp shall be marked with the trade name. " + EXEMPTION, 4),
       ("5.2", "5.2. The lamp shall be tested at 25 degrees.", 4)]
REQS = [{"id": "R-001", "text": "The lamp shall emit red light.", "source": {"regulation": "UN R150", "page": 3, "paragraph": "5.1"}},
        {"id": "R-002", "text": "The lamp shall be marked with the trade name.", "source": {"regulation": "UN R150", "page": 3, "paragraph": "5.1"}},
        {"id": "R-003", "text": "The lamp shall be tested at 20 degrees.", "source": {"regulation": "UN R150", "page": 3, "paragraph": "5.2"}}]


class Model:
    """The judge calls the appended sentence a new obligation and leaves both requirements of 5.1 unchanged (the behaviour the option exists for)."""

    def __init__(self):
        self.s, self.ledger, self.calls = SETTINGS, Ledger("claude-sonnet-5-5", 5.0), []

    def complete_json(self, *, stage, label, system, user, schema, effort=None, max_tokens=0):
        self.calls.append((stage, label))
        if stage == "drift_judge" and label == "5.1":
            return {"requirements": [{"id": "R-001", "verdict": "unchanged", "new_text": "", "new_paragraph": "", "note": "same"},
                                     {"id": "R-002", "verdict": "unchanged", "new_text": "", "new_paragraph": "", "note": "same"}],
                    "new_obligations": [{"text": "A lamp of type A shall not be exempt.", "new_paragraph": "5.1"}]}
        if stage == "drift_judge":
            return {"requirements": [{"id": "R-003", "verdict": "modified", "new_text": "The lamp shall be tested at 25 degrees.",
                                      "new_paragraph": "5.2", "note": "25"}], "new_obligations": []}
        return {"nodes": []}


def run(mode):
    return drift.run_drift(_version(OLD), _version(NEW, "1.1"), REQS, SETTINGS, "c", "UN R150", llm=Model(), appended=mode)


def by_kind(result):
    flagged = {c["requirement_id"]: c for c in result.changes["changes"] if c["requirement_id"]}
    added = [c for c in result.changes["changes"] if c["change"] == "added"]
    return flagged, added


def test_appended_sentences_are_found_only_when_whole_sentences_are_added_to_an_otherwise_kept_paragraph():
    f = drift.appended_sentences
    assert f("The lamp shall be red.", "The lamp shall be red. It shall be lit.") == ["It shall be lit."]
    assert f("A shall pass. B shall pass.", "A shall pass. New one. B shall pass.") == ["New one."]  # inside, between sentences
    assert f("The lamp shall be red", "The lamp shall be red. It shall be lit.") == ["It shall be lit."]  # old has no final full stop
    assert f("The lamp shall be red.", "The lamp shall be red.") == []  # nothing added
    assert f("The lamp shall be red.", "The lamp shall be blue. It shall be lit.") == []  # an edit as well
    assert f("The lamp shall be red.", "The lamp shall be red and lit.") == []  # a clause, not a sentence
    assert f("The lamp shall be red.", "The lamp shall be red. and so on") == []  # does not end a sentence
    assert f("The lamp shall be red.", "It shall be lit.") == []  # the old text is gone
    assert f("The lamp shall be red. It shall be lit.", "The lamp shall be red.") == []  # a sentence removed


def test_default_mode_keeps_the_old_behaviour_the_sentence_is_an_added_item_and_nothing_is_flagged_on_5_1():
    flagged, added = by_kind(run("added"))
    assert set(flagged) == {"R-003"}
    assert [c["new_text"] for c in added] == ["A lamp of type A shall not be exempt."]


def test_modified_mode_flags_every_requirement_of_the_paragraph_with_the_sentence_and_adds_no_item():
    result = run("modified")
    flagged, added = by_kind(result)
    assert set(flagged) == {"R-001", "R-002", "R-003"} and added == []
    for i in ("R-001", "R-002"):
        c = flagged[i]
        assert c["change"] == "modified" and c["new_text"].endswith(EXEMPTION) and EXEMPTION in c["reason"], c
        assert c["source"] == {"page": 4, "paragraph": "5.1"}
    assert flagged["R-001"]["new_text"] == "The lamp shall emit red light. " + EXEMPTION
    assert result.trace["appended_nodes"] == [{"old": "5.1", "new": "5.1", "sentences": [EXEMPTION]}]


def test_both_mode_flags_the_requirements_and_reports_the_sentence_once_as_added():
    flagged, added = by_kind(run("both"))
    assert set(flagged) == {"R-001", "R-002", "R-003"}
    assert [c["new_text"] for c in added] == ["A lamp of type A shall not be exempt."]  # the judge's own item, once
    assert added[0]["source"] == {"page": 4, "paragraph": "5.1"}


def test_both_mode_falls_back_to_the_sentence_when_the_judge_gave_no_obligation():
    class Silent(Model):
        def complete_json(self, **kw):
            out = super().complete_json(**kw)
            if kw["stage"] == "drift_judge" and kw["label"] == "5.1":
                out["new_obligations"] = []
            return out

    result = drift.run_drift(_version(OLD), _version(NEW, "1.1"), REQS, SETTINGS, "c", "UN R150", llm=Silent(), appended="both")
    assert [c["new_text"] for c in by_kind(result)[1]] == [EXEMPTION]


def test_a_changed_requirement_keeps_its_wording_in_every_mode_and_an_unknown_mode_is_refused():
    for mode in ("added", "modified", "both"):
        flagged, _ = by_kind(run(mode))
        assert flagged["R-003"]["new_text"] == "The lamp shall be tested at 25 degrees."  # not an appended sentence: untouched
    try:
        run("nonsense")
    except ValueError:
        return
    raise AssertionError("an unknown mode must be refused")


def test_modes_agree_on_a_paragraph_that_was_edited_inside_a_sentence():
    old = [("5.1", "5.1. The lamp shall emit red light.", 3)]
    new = [("5.1", "5.1. The lamp shall emit amber light.", 3)]
    req = [{"id": "R-001", "text": "The lamp shall emit red light.", "source": {"regulation": "UN R150", "page": 3, "paragraph": "5.1"}}]

    class M(Model):
        def complete_json(self, **kw):
            if kw["stage"] == "drift_judge":
                return {"requirements": [{"id": "R-001", "verdict": "modified", "new_text": "The lamp shall emit amber light.",
                                          "new_paragraph": "5.1", "note": ""}], "new_obligations": []}
            return {"nodes": []}

    out = [drift.run_drift(_version(old), _version(new, "1.1"), req, SETTINGS, "c", "UN R150", llm=M(), appended=m).changes for m in drift.APPENDED_MODES]
    assert out[0] == out[1] == out[2]


def main(argv=None) -> int:
    return run_tests(globals(), sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
