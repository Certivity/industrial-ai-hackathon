#!/usr/bin/env python3
"""Tests of eval/xprovider.py that need no key and no network: the requests it builds, the replies it reads, what it refuses to
send, and, with the PDFs fetched, how it grounds and scores a provider's answer.

    python eval/test_xprovider.py            # unit tests, then the corpus tests if regulations/data has the PDFs
    python eval/test_xprovider.py --unit     # unit tests only

The live calls themselves (the HTTP endpoints) cannot be tried without a key: the request bodies and the reply shapes are
pinned here from the providers' documented formats, and `--provider replay` runs everything else on a file. The `llm` provider
(an OpenAI-compatible endpoint set by the LLM_* lines of .env) has been tried live against DeepSeek: spec/testing/report.md section 10.
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


def test_llm_request_goes_to_the_base_url_with_a_plain_string_and_an_output_cap():
    with environment(LLM_API_KEY="k4", LLM_BASE_URL=" https://api.example.com/ "):
        url, headers, body = X.request_for("llm", "deepseek-m", "SYS", "USR", None)
    assert url == "https://api.example.com/chat/completions" and "k4" not in url
    assert headers == {"Authorization": "Bearer k4"}
    assert body["model"] == "deepseek-m" and body["response_format"] == {"type": "json_object"} and body["max_tokens"] == X.LLM_MAX_TOKENS
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USR"}]
    with environment(LLM_API_KEY="k4", LLM_BASE_URL=None):
        try:
            X.request_for("llm", "m", "s", "u", None)
        except SystemExit as why:
            assert "LLM_BASE_URL" in str(why)
        else:
            raise AssertionError("no endpoint must stop the call")
    assert "max_tokens" not in X.request_for("openai", "m", "s", "u", None)[2]  # newer OpenAI models reject the old name


def test_llm_request_turns_thinking_off_unless_asked_and_only_for_llm():
    with environment(LLM_API_KEY="k", LLM_BASE_URL="https://api.example.com", OPENAI_API_KEY="k"):
        assert X.request_for("llm", "m", "s", "u", None)[2]["thinking"] == {"type": "disabled"}
        assert "thinking" not in X.request_for("llm", "m", "s", "u", None, thinking=True)[2]  # the model's own default
        assert "thinking" not in X.request_for("openai", "m", "s", "u", None)[2]
        asked = argparse.Namespace(provider="llm", model="m", send=False, reply=None, context=X.CONTEXT_TOKENS)
        assert X.Model(asked, Path("unused")).thinking is False
        asked.thinking = True
        assert X.Model(asked, Path("unused")).thinking is True


def test_an_image_goes_as_base64_in_both_formats():
    with tempfile.TemporaryDirectory() as folder:
        picture = Path(folder) / "view.png"
        picture.write_bytes(b"\x89PNG-bytes")
        with environment(OPENAI_API_KEY="k", GEMINI_API_KEY="k", LLM_API_KEY="k", LLM_BASE_URL="https://api.example.com"):
            openai = X.request_for("openai", "m", "s", "u", picture)[2]["messages"][1]["content"][1]
            gemini = X.request_for("gemini", "m", "s", "u", picture)[2]["contents"][0]["parts"][1]
            llm = X.request_for("llm", "m", "s", "u", picture)[2]["messages"][1]["content"]
    assert openai["image_url"]["url"].startswith("data:image/png;base64,iVBORy1ieXRlcw")
    assert gemini["inlineData"]["mimeType"] == "image/png" and gemini["inlineData"]["data"] == "iVBORy1ieXRlcw=="
    assert llm[0] == {"type": "text", "text": "u"} and llm[1]["image_url"]["url"].startswith("data:image/png;base64,iVBORy1ieXRlcw")


def test_openai_reply():
    answer = {"choices": [{"message": {"role": "assistant", "content": '{"a": 1}'}}], "usage": {}}
    assert X.reply_text("openai", answer) == '{"a": 1}' and X.reply_text("llm", answer) == '{"a": 1}'
    refused = {"choices": [{"message": {"content": None, "refusal": "I can't help with that"}}]}
    try:
        X.reply_text("openai", refused)
    except RuntimeError as why:
        assert "refused" in str(why)
    else:
        raise AssertionError("a refusal must not pass as an answer")


def test_a_reply_cut_off_at_the_output_limit_or_without_content_is_an_error_not_json():
    # a reasoning model can spend the whole cap thinking: the content is then empty or half a JSON object
    cut = {"choices": [{"finish_reason": "length", "message": {"content": '{"requirements": [{"regulation": "UN R79", "pa'}}]}
    empty = {"choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "hmm..."}}]}
    blank = {"choices": [{"finish_reason": "stop", "message": {"content": None}}]}
    for provider in ("openai", "llm"):
        for answer, words in ((cut, "cut off"), (empty, "cut off"), (blank, "no content")):
            try:
                X.reply_text(provider, answer)
            except RuntimeError as why:
                assert words in str(why), (provider, str(why))
            else:
                raise AssertionError(f"{provider}: a reply that cannot be the whole answer must not pass")
    fine = {"choices": [{"finish_reason": "stop", "message": {"content": '{"a": 1}', "reasoning_content": "thinking"}}]}
    assert X.reply_text("llm", fine) == '{"a": 1}'  # the reasoning is kept apart from the answer


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
    with tempfile.TemporaryDirectory() as folder, environment(OPENAI_API_KEY=None, GEMINI_API_KEY=None, GOOGLE_API_KEY=None,
                                                              LLM_API_KEY=None, LLM_BASE_URL="https://api.example.com"):
        post, X.post = X.post, lambda *a, **k: (_ for _ in ()).throw(AssertionError("a request was made without a key"))
        try:
            for provider in ("openai", "gemini", "llm"):
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


def test_load_env_reads_the_four_llm_lines_in_the_format_of_the_env_file():
    with tempfile.TemporaryDirectory() as folder, environment(LLM_API_KEY=None, LLM_BASE_URL=None, LLM_MODEL="from-env", LLM_TIMEOUT_S=None, LLM_OTHER=None):
        env = Path(folder) / ".env"
        env.write_text("LLM_API_KEY=sk-abc\nLLM_BASE_URL=https://api.example.com\nLLM_MODEL=file-model\nLLM_TIMEOUT_S=15\nLLM_OTHER=x\n", encoding="utf-8")
        assert X.load_env(env) == ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_TIMEOUT_S"]
        assert os.environ["LLM_API_KEY"] == "sk-abc" and os.environ["LLM_BASE_URL"] == "https://api.example.com"
        assert os.environ["LLM_MODEL"] == "from-env" and os.environ["LLM_TIMEOUT_S"] == "15" and "LLM_OTHER" not in os.environ


def test_llm_provider_takes_model_host_and_timeout_from_the_llm_settings():
    with environment(LLM_MODEL="deepseek-m", LLM_BASE_URL="https://api.example.com/v1", LLM_TIMEOUT_S="15"):
        asked = argparse.Namespace(provider="llm", model=None, send=False, reply=None, context=X.CONTEXT_TOKENS)
        model = X.Model(asked, Path("unused"))
        assert (model.name, model.host, model.timeout) == ("deepseek-m", "api.example.com", 15.0)
        asked.timeout, asked.model = 900.0, "chosen"
        model = X.Model(asked, Path("unused"))
        assert (model.name, model.timeout) == ("chosen", 900.0)  # a flag beats the file
        asked.provider, asked.timeout, asked.model = "openai", None, None
        model = X.Model(asked, Path("unused"))
        assert (model.name, model.timeout) == (None, X.DEFAULT_TIMEOUT_S)  # LLM_* is for --provider llm only
    with environment(LLM_TIMEOUT_S="soon"):
        try:
            X.timeout_for("llm", None)
        except SystemExit as why:
            assert "LLM_TIMEOUT_S" in str(why)
        else:
            raise AssertionError("a timeout that is not a number must stop")


def test_a_dry_run_of_the_llm_provider_names_the_host_and_never_prints_the_key():
    with tempfile.TemporaryDirectory() as folder, environment(LLM_API_KEY="sk-secret-value", LLM_BASE_URL="https://api.example.com"):
        out = io.StringIO()
        with redirect_stdout(out):
            assert X.Model(args_for("llm"), Path(folder)).ask("select", "SYS", "USR") is None
        assert "at api.example.com" in out.getvalue() and "was found" in out.getvalue() and "sk-secret-value" not in out.getvalue()
        assert "sk-secret-value" not in (Path(folder) / "select.prompt.txt").read_text(encoding="utf-8")


def test_a_stalled_connection_ends_in_a_message_about_the_timeout_not_a_traceback():
    calls, sleeps = [], []
    urlopen, sleep = X.urllib.request.urlopen, X.time.sleep

    def stalled(request, timeout):
        calls.append(timeout)
        raise TimeoutError("timed out")

    X.urllib.request.urlopen, X.time.sleep = stalled, sleeps.append
    try:
        X.post("https://api.example.com/chat/completions", {}, {}, timeout=15)
    except SystemExit as why:
        assert "no answer within 15 s" in str(why) and "LLM_TIMEOUT_S" in str(why)
    else:
        raise AssertionError("a stalled connection must stop with a message")
    finally:
        X.urllib.request.urlopen, X.time.sleep = urlopen, sleep
    assert calls == [15, 15, 15, 15] and sleeps == [5, 15, 45]  # the timeout reaches urlopen; four tries, as for any network error


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


def test_label_readings_drop_a_table_clause_and_a_row_id_but_never_a_number():
    assert X.label_readings("6.9.1 table 3b") == [("6.9.1 table 3b", "as written"), ("6.9.1", "without the table")]
    assert X.label_readings("annex 5 part b 1 table b1 m10") == [
        ("annex 5 part b 1 table b1 m10", "as written"), ("annex 5 part b 1 table b1", "without the row id"),
        ("annex 5 part b 1", "without the table")]
    assert X.label_readings("annex 5 part b 1 m10")[1:] == [("annex 5 part b 1", "without the row id")]
    assert X.label_readings("5.2.1.4 table")[1:] == [("5.2.1.4", "without the table")]
    assert X.label_readings("annex 2 model a")[1:] == [("annex 2 model", "without the trailing words"), ("annex 2", "without the trailing words")]
    assert X.label_readings("annex 3 a")[1:] == [("annex 3", "without the trailing words")]
    assert X.label_readings("annex 4 part 1 1.2")[1:] == [] and X.label_readings("annex a")[1:] == []  # a number stays; one word is not a label
    for plain in ("6.4", "annex 4 part 1 1.2", "5.1.4.4.1", ""):
        assert X.label_readings(plain) == [(plain, "as written")]
    assert X.label_readings(None) == [("", "as written")]


def test_authoring_keeps_only_what_grounds_and_uses_our_spelling_of_the_quote():
    requirements = [{"regulation": "UN R79", "paragraph": "5.1.1", "quote": "a", "text": "A"},
                    {"regulation": "UN R79", "paragraph": "5.1.2", "quote": "b", "text": "B"},
                    {"regulation": "UN R79", "paragraph": "5.1.3", "quote": "c", "text": "C"}]
    rows = [{"verdict": "ok", "exact": "A!"}, {"verdict": "hallucinated"}, {"verdict": "wrong page", "exact": "C!"}]
    authoring = X.authoring_from(requirements, rows, "xp")
    assert authoring["case_id"] == "xp" and authoring["regulation"] == "UN R79"
    assert [(r["paragraph"], r["quote"], r["text"]) for r in authoring["requirements"]] == [("5.1.1", "A!", "A"), ("5.1.3", "C!", "C")]
    rows[0]["label"] = "5.1.1"  # a label read as the node's: the case is written with the node's own label
    rows[2]["label"] = "5.1.3. Table 2"
    assert [r["paragraph"] for r in X.authoring_from(requirements, rows, "xp")["requirements"]] == ["5.1.1", "5.1.3. Table 2"]


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


def _words(text: str, start: int, count: int) -> str:
    return " ".join(text.split()[start:start + count])


def test_corpus_ground_reads_a_table_clause_as_the_paragraph_that_holds_the_table():
    # DeepSeek wrote "6.9.1. Table 3b" for R10's test pulses; the tables have no caption line, so the parser has them in node 6.9.1
    _need("UN R10")
    node = next(n for n in X.candidates("UN R10") if n.label == "6.9.1")
    quote = _words(" ".join(node.text[:2]), 2, 10)
    ask_ = lambda label: X.ground([{"regulation": "UN R10", "page": node.page_start, "paragraph": label, "quote": quote, "text": "t"}])[0]  # noqa: E731
    row = ask_("6.9.1. Table 3b")
    assert (row["verdict"], row["label"], row["read"]) == ("ok", "6.9.1", "without the table")
    assert "read" not in ask_("6.9.1") and ask_("6.9.1")["verdict"] == "ok"
    assert ask_("6.9.2. Table 3b")["verdict"] == "other node"  # the model's paragraph number is wrong: not forgiven


def test_corpus_ground_reads_a_row_id_and_another_owner_as_the_table_by_its_caption():
    # "Annex 5 Part B 1. Table B1 M10" and "7.3.4. Table B1 M10": the model named a mitigation row; the parser has Table B1 under Annex 5 Part B 1
    _need("UN R155")
    table = next(n for n in X.candidates("UN R155") if n.label == "Annex 5 Part B 1. Table B1")
    quote = _words(table.text[0], 0, 8)
    for label, read in (("Annex 5 Part B 1. Table B1 M10", "without the row id"), ("Annex 5 Part B 1. M10", "table of the paragraph"),
                        ("7.3.4. Table B1 M10", "table by its id")):
        row = X.ground([{"regulation": "UN R155", "page": table.page_start, "paragraph": label, "quote": quote, "text": "t"}])[0]
        assert (row["verdict"], row["label"], row["read"]) == ("ok", table.label, read), (label, row)


def test_corpus_ground_takes_the_text_of_an_annex_heading_as_a_node():
    _need("UN R19")  # Annex 5 opens with three paragraphs of text before its "1." (the model cited "Annex 5 1.", which is wrong)
    from baseline import parsed
    head = next(n for n in parsed("UN R19").nodes if n.kind == "annex" and n.label == "Annex 5")
    quote = _words(" ".join(head.text[2:4]), 0, 12)
    row = X.ground([{"regulation": "UN R19", "page": head.page_start, "paragraph": "Annex 5", "quote": quote, "text": "t"}])[0]
    assert (row["verdict"], row["label"]) == ("ok", "Annex 5")
    assert X.ground([{"regulation": "UN R19", "page": head.page_start, "paragraph": "Annex 5 1.", "quote": quote, "text": "t"}])[0]["verdict"] == "other node"


def test_corpus_ground_reads_a_descriptor_after_an_annex_as_the_annex():
    _need("UN R26")  # DeepSeek: "Annex 2 Model A" for text under the heading of Annex 2 (the arrangement of the approval mark)
    from baseline import parsed
    head = next(n for n in parsed("UN R26").nodes if n.kind == "annex" and n.label == "Annex 2")
    quote = _words(" ".join(head.text[1:4]), 0, 10)
    ask_ = lambda label: X.ground([{"regulation": "UN R26", "page": head.page_start, "paragraph": label, "quote": quote, "text": "t"}])[0]  # noqa: E731
    row = ask_("Annex 2 Model A")
    assert (row["verdict"], row["label"], row["read"]) == ("ok", "Annex 2", "without the trailing words")
    assert ask_("Annex 3 Model A")["verdict"] != "ok"  # the annex number is the model's to get right


def test_corpus_regrade_moves_the_verdicts_of_a_saved_case_and_rebuilds_its_expected_file():
    _need("UN R79")
    good = _synthetic_requirements("synth-r79-eps")
    with tempfile.TemporaryDirectory() as folder:
        case = Path(folder) / "xp-case"
        case.mkdir()
        (case / "provider.json").write_text(json.dumps({"requirements": good}), encoding="utf-8")
        stale = [{"verdict": "other node"} for _ in good]  # what an earlier parser said
        (case / "ground.json").write_text(json.dumps(stale), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            X.cmd_regrade(argparse.Namespace(cases=[str(case)], write=True))
        assert f"other node -> ok {len(good)}" in out.getvalue() and f"kept {len(good)}" in out.getvalue()
        rebuilt = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        assert rebuilt["case_id"] == "xp-case" and len(rebuilt["requirements"]) == len(good)
        assert {r["verdict"] for r in json.loads((case / "ground.json").read_text(encoding="utf-8"))} == {"ok"}


def test_corpus_the_catalogue_is_what_the_prompt_says_it_is():
    _need("UN R150", "UN R128")
    text, menu = X.catalogue(["UN R150", "UN R128"])
    assert set(menu) == {"UN R150", "UN R128"} and "## UN R150 — " in text and "Replaces: UN R3" in text
    assert "- 3.3 — Approval marking and other markings (" in text


def main(argv: list[str] | None = None) -> int:
    return run_tests(globals(), sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
