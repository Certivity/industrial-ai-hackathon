#!/usr/bin/env python3
"""Offline tests of the selection switches (AI_AGENT_SELECT, AI_AGENT_VET): defaults unchanged, v2 prompts reach the model, supersession
and the cap still apply; v3 (shortlist, verify against the scope text): quote check, verify parsing, shortlist union. No model call.

    python eval/test_selection.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from test_parse import run_tests  # noqa: E402

from ai_agent import config, regulations, verify  # noqa: E402


class FakeLLM:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def complete_json(self, **kw):
        self.calls.append(kw)
        return self.answer


CATALOG = SimpleNamespace(names=["UN R10", "UN R48", "UN R148", "UN R23"], all_cards_text=lambda: "cards",
                          successor=lambda r: {"UN R23": "UN R148"}.get(r, r), card_text=lambda r: f"card {r}")


def pick(reg, conf):
    return {"regulation": reg, "level": "device", "confidence": conf, "covers": [], "reason": "x"}


def test_defaults_are_v1_and_env_switches_are_read():
    for var in ("AI_AGENT_SELECT", "AI_AGENT_VET"):
        os.environ.pop(var, None)
    os.environ["AI_AGENT_KEY"] = "k"
    s = config.Settings.from_env()
    assert (s.select, s.vet) == ("v1", "v1")
    os.environ["AI_AGENT_SELECT"], os.environ["AI_AGENT_VET"] = "V2", "v2"
    try:
        s = config.Settings.from_env()
        assert (s.select, s.vet) == ("v2", "v2")
    finally:
        os.environ.pop("AI_AGENT_SELECT"), os.environ.pop("AI_AGENT_VET")


def test_select_prompt_follows_version_and_v1_is_the_old_prompt():
    answer = {"selected": [pick("UN R48", "low"), pick("UN R23", "high"), pick("UN R148", "medium"), pick("UN R10", "high")], "close_calls": []}
    for version, system in (("v1", regulations.SELECT_SYSTEM), ("v2", regulations.SELECT_SYSTEM_V2)):
        llm = FakeLLM(answer)
        out = regulations.select_regulations(llm, CATALOG, "profile", 3, version)
        assert llm.calls[0]["system"] == system
        assert [s["regulation"] for s in out["selected"]] == ["UN R148", "UN R10", "UN R48"], out["selected"]  # R23 -> R148 once, high first, cap 3
        assert out["redirects"] == {"UN R23": "UN R148"} and out["dropped"] == []
    assert "Be strict" in regulations.SELECT_SYSTEM and "Be strict" not in regulations.SELECT_SYSTEM_V2
    assert regulations.select_regulations(FakeLLM(answer), CATALOG, "p", 8)["selected"]  # the default argument is v1


def test_vet_prompt_follows_version_and_empty_input_makes_no_call():
    cited = {"UN R10": {"count": 1, "nodes": ["UN R48 5.1"], "snippet": "approved to R10", "by": ["UN R48"]}}
    answer = {"add": [], "skip": []}
    for version, system in (("v1", regulations.VET_SYSTEM), ("v2", regulations.VET_SYSTEM_V2)):
        llm = FakeLLM(answer)
        regulations.vet_cited(llm, CATALOG, "profile", cited, version)
        assert llm.calls[0]["system"] == system
    llm = FakeLLM(answer)
    assert regulations.vet_cited(llm, CATALOG, "profile", {}, "v2") == answer and not llm.calls


# ------------------------------------------------------------------------------------------------ v3: shortlist, then verify
SCOPE = "1. Scope. This Regulation applies to vehicles of categories M and N with regard to the installation of lighting devices, 1,500 mm wide."


class Seq:
    """Answers in order, and keeps the calls."""
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete_json(self, **kw):
        self.calls.append(kw)
        return self.answers.pop(0)


def decision(applies, clause, part="lamp", reason="r"):
    return {"applies": applies, "scope_clause": clause, "product_part": part, "reason": reason}


def test_v3_setting_and_selection_prompt():
    for var in ("AI_AGENT_SELECT", "AI_AGENT_VET"):
        os.environ.pop(var, None)
    os.environ["AI_AGENT_KEY"] = "k"
    os.environ["AI_AGENT_SELECT"] = "v3"
    try:
        s = config.Settings.from_env()
        assert (s.select, s.vet) == ("v3", "v2")  # the verification filters the hop, so the recall-oriented vetting feeds it
        os.environ["AI_AGENT_VET"] = "v1"
        assert config.Settings.from_env().vet == "v1"
    finally:
        os.environ.pop("AI_AGENT_SELECT"), os.environ.pop("AI_AGENT_VET", None)
    assert config.Settings.from_env().select == "v1"  # the default is unchanged
    assert config.DEFAULT_EFFORT["verify"] == "medium"
    llm = FakeLLM({"selected": [], "close_calls": []})
    regulations.select_regulations(llm, CATALOG, "p", 8, "v3")
    assert llm.calls[0]["system"] == regulations.SELECT_SYSTEM_V2  # v3 reuses the v2 selection, so its calls replay from the v2 runs


def test_quote_check_is_verbatim_up_to_case_punctuation_and_thousands():
    assert verify.quote_is_verbatim("applies to vehicles of categories M and N", SCOPE)
    assert verify.quote_is_verbatim("Vehicles of categories M AND N, with regard", SCOPE)  # case and punctuation do not matter
    assert verify.quote_is_verbatim("1500 mm wide", SCOPE)  # a thousands separator does not matter
    assert verify.quote_is_verbatim("applies to vehicles ... lighting devices", SCOPE)  # pieces joined by an ellipsis, each verbatim
    assert not verify.quote_is_verbatim("applies to vehicles of categories L and M", SCOPE)  # one word changed
    assert not verify.quote_is_verbatim("lighting devices applies to vehicles", SCOPE)  # order matters
    assert not verify.quote_is_verbatim("", SCOPE) and not verify.quote_is_verbatim("applies to", SCOPE)  # empty or too short proves nothing
    assert not verify.quote_is_verbatim("applies to vehicles ... of tyres", SCOPE)  # one bad piece spoils it


def test_scope_text_takes_paragraph_1_and_short_definitions_only():
    def node(num, body, kind="para", scope=False):
        return SimpleNamespace(num=num, body=body, kind=kind, scope=scope)
    nodes = [node((1,), "Scope  text"), node((1, 1), "Sub  one"), node((2,), "Definitions"), node((2, 1), "a means b"),
             node((1,), "annex scope", scope=True), node((3,), "Other"), node((1, 2), "table", kind="table")]
    assert verify.scope_text(nodes) == ("Scope text\nSub one", "Definitions\na means b")
    nodes.append(node((2, 2), "x" * 3000))
    assert verify.scope_text(nodes)[1] == ""  # long definitions are left out


def test_verify_accepts_a_verbatim_yes_and_rejects_no_and_unverified():
    llm = Seq(decision("yes", "applies to vehicles of categories M and N"))
    got = verify.verify_regulation(llm, CATALOG_V3, "profile", "UN R48", SCOPE)
    assert got["accepted"] and got["quote_verbatim"] and not got["retried"] and len(llm.calls) == 1
    assert llm.calls[0]["stage"] == "verify" and SCOPE in llm.calls[0]["user"] and "profile" in llm.calls[0]["user"]
    assert llm.calls[0]["system"] == verify.VERIFY_SYSTEM
    got = verify.verify_regulation(Seq(decision("no", "categories M and N")), CATALOG_V3, "profile", "UN R48", SCOPE)
    assert not got["applies"] and not got["accepted"]
    # a yes with a made-up quote is asked once more; still made up -> unverified, not accepted
    llm = Seq(decision("yes", "applies to every vehicle"), decision("yes", "applies to every product"))
    got = verify.verify_regulation(llm, CATALOG_V3, "profile", "UN R48", SCOPE)
    assert got["applies"] and not got["quote_verbatim"] and not got["accepted"] and got["retried"] and len(llm.calls) == 2
    assert "not word for word" in llm.calls[1]["user"]
    # the retry can repair it
    llm = Seq(decision("yes", "invented"), decision("yes", "categories M and N with regard"))
    assert verify.verify_regulation(llm, CATALOG_V3, "profile", "UN R48", SCOPE)["accepted"]


def test_verify_carries_the_supersession_note_and_handles_a_missing_scope():
    llm = Seq(decision("no", ""))
    verify.verify_regulation(llm, CATALOG_V3, "p", "UN R23", "")
    assert "SUPERSEDED: its provisions are now in UN R148" in llm.calls[0]["user"] and "no numbered paragraph 1" in llm.calls[0]["user"]


def test_verify_all_keeps_the_order_and_empty_makes_no_call():
    assert verify.verify_all(Seq(), CATALOG_V3, "p", {}) == {}
    class ByReg:
        def complete_json(self, **kw):
            return decision("yes" if "=== UN R48 ===" in kw["user"] else "no", "categories M and N")
    out = verify.verify_all(ByReg(), CATALOG_V3, "p", {"UN R10": (SCOPE, ""), "UN R48": (SCOPE, "")}, workers=2)
    assert list(out) == ["UN R10", "UN R48"] and [d["accepted"] for d in out.values()] == [False, True]


def test_shortlist_union_and_accepted_items():
    selected = [pick("UN R48", "high"), pick("UN R10", "low")]
    cited = [{"regulation": "UN R10", "reason": "dup"}, {"regulation": "UN R148", "reason": "cited"}, {"regulation": "UN R79", "reason": "c2"}]
    out = verify.shortlist_union(selected, cited, 8)
    assert [i["regulation"] for i in out] == ["UN R48", "UN R10", "UN R148", "UN R79"]  # selection first, each once
    assert [i["source"] for i in out] == ["selection", "selection", "citation", "citation"] and out[2]["confidence"] == "medium"
    assert [i["regulation"] for i in verify.shortlist_union(selected, cited, 3)] == ["UN R48", "UN R10", "UN R148"]  # cap
    got = verify.accepted_items(out, {"UN R48": {"accepted": True}, "UN R10": {"accepted": False}, "UN R148": {"accepted": True}})
    assert [i["regulation"] for i in got] == ["UN R48", "UN R148"] and got[0]["verification"] == {"accepted": True}  # R79 was never verified


CATALOG_V3 = SimpleNamespace(superseded_by=lambda r: {"UN R23": "UN R148"}.get(r), card_text=lambda r: f"card {r}")


if __name__ == "__main__":
    raise SystemExit(run_tests(globals(), sys.argv[1:]))
