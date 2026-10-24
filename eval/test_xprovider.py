#!/usr/bin/env python3
"""Tests of eval/xprovider.py that need no key and no network: the requests it builds, the replies it reads, what it refuses to
send, and, with the PDFs fetched, how it grounds and scores a provider's answer.

    python eval/test_xprovider.py            # unit tests, then the corpus tests if regulations/data has the PDFs
    python eval/test_xprovider.py --unit     # unit tests only

The live calls themselves (the two HTTP endpoints) cannot be tried without a key: the request bodies and the reply shapes are
pinned here from the providers' documented formats, and `--provider replay` runs everything else on a file.
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import xprovider as X  # noqa: E402
from test_parse import run_tests, skip  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _set_environment(values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@contextmanager
def environment(**values: str | None):
    """Set (or, with None, remove) environment variables for the block, and put them back after."""
    saved = {key: os.environ.get(key) for key in values}
    try:
        _set_environment(values)
        yield
    finally:
        _set_environment(saved)


def ask(model: "X.Model", label: str, system: str, user: str):
    """model.ask without its progress line in the test output."""
    with redirect_stdout(io.StringIO()):
        return model.ask(label, system, user)


def args_for(provider: str = "openai", send: bool = False, replies: list[str] | None = None, context: int = X.CONTEXT_TOKENS) -> argparse.Namespace:
    return argparse.Namespace(provider=provider, model="m", send=send, reply=replies, context=context)


# ------------------------------------------------------------------------------------------------------ requests
def test_openai_request():
    with environment(OPENAI_API_KEY="k1"):
        url, headers, body = X.request_for("openai", "gpt-m", "SYS", "USR", None)
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers == {"Authorization": "Bearer k1"}
    assert body["model"] == "gpt-m" and body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert body["messages"][1] == {"role": "user", "content": [{"type": "text", "text": "USR"}]}


def test_gemini_request_keeps_the_key_out_of_the_url():
    with environment(GEMINI_API_KEY="k2", GOOGLE_API_KEY=None):
        url, headers, body = X.request_for("gemini", "gem-m", "SYS", "USR", None)
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gem-m:generateContent" and "k2" not in url
    assert headers == {"x-goog-api-key": "k2"}
    assert body["systemInstruction"] == {"parts": [{"text": "SYS"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "USR"}]}]
    assert body["generationConfig"] == {"responseMimeType": "application/json"}
    with environment(GEMINI_API_KEY=None, GOOGLE_API_KEY="k3"):
        assert X.request_for("gemini", "m", "", "", None)[1] == {"x-goog-api-key": "k3"}


def test_an_image_goes_as_base64_in_both_formats():
    with tempfile.TemporaryDirectory() as folder:
        picture = Path(folder) / "view.png"
        picture.write_bytes(b"\x89PNG-bytes")
        with environment(OPENAI_API_KEY="k", GEMINI_API_KEY="k"):
            openai = X.request_for("openai", "m", "s", "u", picture)[2]["messages"][1]["content"][1]
            gemini = X.request_for("gemini", "m", "s", "u", picture)[2]["contents"][0]["parts"][1]
    assert openai["image_url"]["url"].startswith("data:image/png;base64,iVBORy1ieXRlcw")
    assert gemini["inlineData"]["mimeType"] == "image/png" and gemini["inlineData"]["data"] == "iVBORy1ieXRlcw=="


def test_openai_reply():
    answer = {"choices": [{"message": {"role": "assistant", "content": '{"a": 1}'}}], "usage": {}}
    assert X.reply_text("openai", answer) == '{"a": 1}'
    refused = {"choices": [{"message": {"content": None, "refusal": "I can't help with that"}}]}
    try:
        X.reply_text("openai", refused)
    except RuntimeError as why:
        assert "refused" in str(why)
    else:
        raise AssertionError("a refusal must not pass as an answer")


def test_gemini_reply_skips_thought_parts():
    answer = {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"a": '}, {"text": "1}"}]}}]}
    assert X.reply_text("gemini", answer) == '{"a": 1}'
    try:
        X.reply_text("gemini", {"promptFeedback": {"blockReason": "SAFETY"}})
    except RuntimeError as why:
        assert "SAFETY" in str(why)
    else:
        raise AssertionError("a blocked prompt must not pass as an answer")


def test_read_json_finds_the_object_in_a_fenced_or_chatty_reply():
    assert X.read_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert X.read_json('Sure! Here it is: {"a": {"b": 2}} Hope that helps.') == {"a": {"b": 2}}
    try:
        X.read_json("no object here")
    except ValueError:
        pass
    else:
        raise AssertionError("no JSON must be an error")


# ------------------------------------------------------------------------------------------- what is not sent
def test_a_dry_run_sends_nothing_and_keeps_the_prompt():
    with tempfile.TemporaryDirectory() as folder, environment(OPENAI_API_KEY="k"):
        sent = []
        post, X.post = X.post, lambda *a, **k: sent.append(a) or {}
        try:
            assert ask(X.Model(args_for(send=False), Path(folder)), "select", "SYS", "USR") is None
        finally:
            X.post = post
        assert not sent
        assert "USR" in (Path(folder) / "select.prompt.txt").read_text(encoding="utf-8")
        assert not (Path(folder) / "select.reply.txt").exists()


def test_a_missing_key_stops_before_the_request():
    with tempfile.TemporaryDirectory() as folder, environment(OPENAI_API_KEY=None, GEMINI_API_KEY=None, GOOGLE_API_KEY=None):
        post, X.post = X.post, lambda *a, **k: (_ for _ in ()).throw(AssertionError("a request was made without a key"))
        try:
            for provider in ("openai", "gemini"):
                try:
                    ask(X.Model(args_for(provider, send=True), Path(folder)), "x", "s", "u")
                except SystemExit as why:
                    assert "no API key" in str(why)
                else:
                    raise AssertionError(provider + ": no key must stop the call")
        finally:
            X.post = post


def test_a_prompt_over_the_context_is_refused_before_it_is_sent():
    with tempfile.TemporaryDirectory() as folder:
        try:
            ask(X.Model(args_for("replay", replies=["unused"], context=100), Path(folder)), "x", "s", "u" * 4000)
        except SystemExit as why:
            assert "over --context" in str(why)
        else:
            raise AssertionError("an oversized prompt must stop")


def test_the_replay_provider_answers_from_files_in_order():
    with tempfile.TemporaryDirectory() as folder:
        first, second = Path(folder) / "1.json", Path(folder) / "2.json"
        first.write_text('{"n": 1}', encoding="utf-8")
        second.write_text('{"n": 2}', encoding="utf-8")
        model = X.Model(args_for("replay", replies=[str(first), str(second)]), Path(folder) / "work")
        assert [ask(model, "a", "s", "u"), ask(model, "b", "s", "u")] == ['{"n": 1}', '{"n": 2}']
        assert (Path(folder) / "work" / "b.reply.txt").read_text(encoding="utf-8") == '{"n": 2}'


def test_load_env_takes_only_the_key_names_and_does_not_override_the_environment():
    with tempfile.TemporaryDirectory() as folder, environment(OPENAI_API_KEY="from-env", GEMINI_API_KEY=None, GOOGLE_API_KEY=None, OTHER_SECRET=None):
        env = Path(folder) / ".env"
        env.write_text('# a comment\nOPENAI_API_KEY=from-file\nexport GEMINI_API_KEY="quoted"\nOTHER_SECRET=nope\nGOOGLE_API_KEY=\n', encoding="utf-8")
        assert X.load_env(env) == ["OPENAI_API_KEY", "GEMINI_API_KEY"]  # names only; an empty value is not a key
        assert os.environ["OPENAI_API_KEY"] == "from-env" and os.environ["GEMINI_API_KEY"] == "quoted"
        assert "OTHER_SECRET" not in os.environ and "GOOGLE_API_KEY" not in os.environ
        assert X.load_env(Path(folder) / "missing.env") == []


def test_the_prompts_hold_no_hint_taken_from_the_dev_gold():
    # the proposal's strategy may be in the prompt (it is what is under test); the regulations, sections, labels and wording the dev
    # gold needed may not, not even as the example of an answer's format
    hint = re.compile(r"electromagnetic|\bEMC\b|\bESA\b|\bR(?:10|148|150|48)\b|\b6\.10\b|3\.3\.1\.1|Annex 4 Part 1|Annex 6 Part 6|\bTable 3\b|lamp|reflector|lens", re.I)
    for variant, rules in X.PICK_RULES.items():
        assert not hint.search(rules), variant
    assert not hint.search(X.GOLD_RULES)
    assert not hint.search(X.SPEC_TEMPLATE)
    for variant in X.PICK_RULES:
        system, user = X.select_prompt("THE-SPEC", "THE-CATALOGUE", variant)
        assert "THE-SPEC" in user and "THE-CATALOGUE" in user and "THE-SPEC" not in system
        assert not hint.search(system + user.replace("THE-SPEC", "").replace("THE-CATALOGUE", "")), variant
    assert not hint.search("".join(X.spec_prompt("a brief", "THE-NAMES")).replace("THE-NAMES", "").replace("a brief", ""))


# ------------------------------------------------------------------------------------------------- reading answers
def test_picks_are_matched_ignoring_case_spacing_and_a_closing_dot_and_the_unknown_are_listed():
    menu = {"UN R48": {"6.10", "Annex 4 Part 1"}, "UN R150": {"3.3"}}
    answer = {"regulations": [{"regulation": "un r48", "why": "a"}, {"regulation": "UN R999"}],
              "sections": [{"regulation": "UN R48", "root": "6.10."}, {"regulation": "UN R48", "root": "annex  4 part 1"},
                           {"regulation": "UN R48", "root": "7.1"}, {"regulation": "UN R150", "root": "6.10"}, {"regulation": "UN R999", "root": "1"}]}
    sections, regulations, rejected = X.resolve_picks(answer, menu)
    assert [(s["regulation"], s["root"]) for s in sections] == [("UN R48", "6.10"), ("UN R48", "Annex 4 Part 1")]
    assert [r["regulation"] for r in regulations] == ["UN R48"]
    assert len(rejected) == 4 and any("UN R999" in line for line in rejected)


def test_squash_ignores_case_spacing_and_raised_digits():
    assert X.squash("3.00∙10²  Cd\nat 20'") == X.squash("3.00·102 cd at 20'")
    assert X.squash("it’s") == X.squash("it's")
    assert X.squash("6.4") != X.squash("6.5")


def test_exact_quote_gives_back_the_nodes_own_spelling():
    body = "6.1. The light shall be 3.00∙10² cd at\nthe angle of divergence."
    assert X.exact_quote(body, "SHALL be 3.00·102   cd at the angle") == "shall be 3.00∙10² cd at\nthe angle"
    assert X.exact_quote(body, "not in the body") is None and X.exact_quote(body, "   ") is None


def test_authoring_keeps_only_what_grounds_and_uses_our_spelling_of_the_quote():
    requirements = [{"regulation": "UN R79", "paragraph": "5.1.1", "quote": "a", "text": "A"},
                    {"regulation": "UN R79", "paragraph": "5.1.2", "quote": "b", "text": "B"},
                    {"regulation": "UN R79", "paragraph": "5.1.3", "quote": "c", "text": "C"}]
    rows = [{"verdict": "ok", "exact": "A!"}, {"verdict": "hallucinated"}, {"verdict": "wrong page", "exact": "C!"}]
    authoring = X.authoring_from(requirements, rows, "xp")
    assert authoring["case_id"] == "xp" and authoring["regulation"] == "UN R79"
    assert [(r["paragraph"], r["quote"], r["text"]) for r in authoring["requirements"]] == [("5.1.1", "A!", "A"), ("5.1.3", "C!", "C")]


# ------------------------------------------------------------------------------------------------------- corpus
def _need(*regulations: str) -> None:
    for regulation in regulations:
        if X.corpus.pdf_path(X.corpus.entry_for(regulation), "base") is None:
            skip(f"{regulation}: the base PDF is not in regulations/data")


def _synthetic_requirements(case: str) -> list[dict]:
    folder = ROOT / "spec" / "testing" / "cases" / case
    authoring = json.loads((folder / "authoring.json").read_text(encoding="utf-8"))
    expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    return [{"regulation": authoring["regulation"], "page": gold["source"]["page"], "paragraph": item["paragraph"], "quote": item["quote"],
             "text": item["text"]} for item, gold in zip(authoring["requirements"], expected["requirements"])]


def test_corpus_section_ids_are_the_ids_the_scoring_uses():
    _need("UN R150", "UN R10")
    ids = {root: (heading, n) for root, heading, n in X.sections_of("UN R150")}
    assert {"3.3", "5.1", "Annex 6 Part 6"} <= set(ids)
    assert ids["Annex 6 Part 6"][0].startswith("Resistance to weathering")  # the id is not repeated in the heading
    assert {"6.8", "6.9", "Annex 9"} <= {root for root, _, _ in X.sections_of("UN R10")}
    from baseline import parsed, section_of
    assert set(ids) <= {section_of(n) for n in parsed("UN R150").nodes if n.kind in ("para", "table")}


def test_corpus_a_heading_with_children_is_structure_but_a_leaf_line_stays():
    _need("UN R150", "UN R128")
    labels = {n.label for n in X.candidates("UN R150")}
    assert not labels & {"3.3", "3.3.1"}  # "3.3 Approval marking ..." and "3.3.1 General provisions": bare headings with sub-paragraphs
    assert {"3.3.1.1", "3.3.2"} <= labels  # the paragraphs under them stay ("3.3.2 ... shall consist of:" is a lead-in with children)
    assert "2.3.1.1" in {n.label for n in X.candidates("UN R128")}  # "the rated voltage;" is a leaf and a gold paragraph


def test_corpus_the_gold_sections_reach_every_gold_paragraph():
    _need("UN R128", "UN R79")
    for case in ("synth-r128-led-source", "synth-r79-eps"):
        folder = ROOT / "spec" / "testing" / "cases" / case
        gold = X.Case(folder)
        sections = [{"regulation": reg, "root": root} for reg, root in gold.sections]
        result = X.score_picks(gold, sections, [{"regulation": r} for r in gold.regulations])
        assert result["paragraphs"]["found"] == len(gold.paragraphs), case
        assert result["regulations"]["f2"] == 1.0 and result["sections"]["recall"] == 1.0


def test_corpus_a_wrong_regulation_costs_regulation_precision_and_paragraph_precision():
    _need("UN R79", "UN R10")
    gold = X.Case(ROOT / "spec" / "testing" / "cases" / "synth-r79-eps")
    right = [{"regulation": reg, "root": root} for reg, root in gold.sections]
    wrong = right + [{"regulation": "UN R10", "root": "6.8"}]
    a = X.score_picks(gold, right, [{"regulation": "UN R79"}])
    b = X.score_picks(gold, wrong, [{"regulation": "UN R79"}, {"regulation": "UN R10"}])
    assert b["regulations"]["precision"] == 0.5 and a["regulations"]["precision"] == 1.0
    assert b["paragraphs"]["paragraph_precision"] < a["paragraphs"]["paragraph_precision"]
    assert b["paragraphs"]["found"] == a["paragraphs"]["found"]


def test_corpus_ground_tells_each_defect_apart():
    _need("UN R79")
    good = _synthetic_requirements("synth-r79-eps")
    assert {row["verdict"] for row in X.ground(good)} == {"ok"}
    assert all(row["exact"] for row in X.ground(good))
    bad = copy.deepcopy(good)
    bad[0]["quote"] = "the steering shall be made of unobtainium and shall glow in the dark at night"
    bad[1]["page"] += 6
    bad[2]["paragraph"] = "5.1.3"
    bad[3]["paragraph"] = "99.1"
    bad[4]["quote"] = bad[4]["quote"].upper().replace(" ", "  ")
    verdicts = [row["verdict"] for row in X.ground(bad)[:5]]
    assert verdicts == ["hallucinated", "wrong page", "other node", "other node", "ok"], verdicts
    assert X.ground(bad)[2]["our_labels"] == [good[2]["paragraph"]]


def test_corpus_the_catalogue_is_what_the_prompt_says_it_is():
    _need("UN R150", "UN R128")
    text, menu = X.catalogue(["UN R150", "UN R128"])
    assert set(menu) == {"UN R150", "UN R128"} and "## UN R150 — " in text and "Replaces: UN R3" in text
    assert "- 3.3 — Approval marking and other markings (" in text


def main(argv: list[str] | None = None) -> int:
    return run_tests(globals(), sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
