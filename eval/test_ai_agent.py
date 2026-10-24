#!/usr/bin/env python3
"""Tests of src/ai_agent without a model call: the settings and ledger, the request path of the LLM layer against a fake SDK client, the
tool loop, the graph views and the grounding check on a small synthetic regulation, the tools, the emission policy, and the whole chain
run by a scripted model over a real regulation.

    python eval/test_ai_agent.py            # all tests; the corpus ones need regulations/data and PyMuPDF
    python eval/test_ai_agent.py --unit     # leaves out test_corpus_*

Plain functions named test_*; the runner is the one of eval/test_parse.py. Nothing here reads AI_AGENT_KEY or calls the API.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from test_parse import Skip, run_tests  # noqa: E402

from ai_agent import config, emit, llm, obligations, store, tools  # noqa: E402
from ai_agent.config import MissingKey, Settings  # noqa: E402
from ai_agent.llm import LLM, BudgetExceeded, Ledger, Reply, ToolOutcome  # noqa: E402
from regcomp.parse import Node, ParsedDocument  # noqa: E402

SETTINGS = Settings(api_key="sk-test", cache_dir=None, workers=2, fallbacks=False)


# ------------------------------------------------------------------------------------------------------------ helpers
def node(label, text, page=1, parent=-1, kind="para", scope="", path=""):
    num = tuple(int(x) for x in label.split(".")) if kind == "para" and not scope and label[:1].isdigit() else ()
    if scope and kind == "para":
        num = tuple(int(x) for x in label[len(scope):].split("."))
    return Node(kind, label, scope, num, page, page, [text], [page], parent=parent, path=path or label)


def synthetic() -> store.RegGraph:
    """A small regulation shaped like the real ones: sections 5.x, a table, an annex. Titled as UN R150 for the index lookup."""
    nodes = [
        node("5", "5. Specifications", 3),
        node("5.1", "5.1. Colour. The retro-reflector shall emit red light.", 3, 0),
        node("5.1.1", "5.1.1. The reflecting surface shall be not less than 20 cm2 in area.", 3, 1),
        node("5.2", "5.2. Marking. Each device shall bear the trade name or mark of the applicant.", 4, 0),
        node("5.2.1", "5.2.1. The marking shall be clearly legible and indelible, also after 1,500 hours of exposure.", 4, 3),
        node("Annex 1", "Annex 1 Communication", 9, -1, kind="annex", scope="Annex 1"),
        node("Annex 1 1", "1. Name and address of the applicant as in paragraph 5.2.", 9, 5, scope="Annex 1"),
    ]
    return store.RegGraph("UN R150", doc=ParsedDocument(Path("synthetic.pdf"), 10, nodes))


def text_reply(payload) -> list[dict]:
    return [{"type": "text", "text": payload if isinstance(payload, str) else json.dumps(payload)}]


def tool_use(uid: str, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": uid, "name": name, "input": args}


class Scripted(LLM):
    """The real LLM class with `call` replaced by a script: complete_json, run_tools and everything above them run for real."""

    def __init__(self, script, settings=SETTINGS):
        super().__init__(settings, client=object())
        self.script, self.requests = script, []

    def call(self, *, stage, label, system, messages, tools=None, schema=None, effort=None, max_tokens=16_000, auto_cache=False):
        self.requests.append({"stage": stage, "label": label, "messages": [dict(m) for m in messages], "max_tokens": max_tokens,
                              "auto_cache": auto_cache})
        content, stop = self.script(stage, label, system, messages, tools, schema)
        reply = Reply(content, stop, "scripted", {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 0,
                                                   "cache_read_input_tokens": 0})
        self.ledger.add(stage, reply.usage, 0.0, cached=False)
        return reply


class FakeClient:
    """Enough of the SDK for LLM._send: .messages.stream and .beta.messages.stream, each a context manager with get_final_message()."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = SimpleNamespace(stream=lambda **kw: self._stream(False, kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: self._stream(True, kw)))

    def _stream(self, beta, kwargs):
        self.calls.append((beta, kwargs))
        text, stop = self.replies.pop(0)
        block = SimpleNamespace(model_dump=lambda **kw: {"type": "text", "text": text})
        final = SimpleNamespace(content=[block], stop_reason=stop, model="claude-sonnet-5-5", stop_details=None,
                                usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=500))
        return _Ctx(final)


class _Ctx:
    def __init__(self, final):
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.final


# --------------------------------------------------------------------------------------------------------- config
def test_env_file_is_read_with_crlf_and_quotes_and_never_overrides_the_environment():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".env"
        path.write_bytes(b'# comment\r\nTEST_AGENT_A="quoted value"\r\nexport TEST_AGENT_B=plain\r\nTEST_AGENT_C=from file\r\n\r\n')
        os.environ["TEST_AGENT_C"] = "from environment"
        try:
            config.load_env(path)
            assert os.environ["TEST_AGENT_A"] == "quoted value" and os.environ["TEST_AGENT_B"] == "plain"
            assert os.environ["TEST_AGENT_C"] == "from environment"
        finally:
            for name in ("TEST_AGENT_A", "TEST_AGENT_B", "TEST_AGENT_C"):
                os.environ.pop(name, None)


def test_settings_need_a_key_default_the_model_and_hide_the_key():
    saved = {n: os.environ.pop(n, None) for n in ("AI_AGENT_KEY", "AI_AGENT_MODEL", "AI_AGENT_FALLBACKS")}
    original = config.load_env
    config.load_env = lambda *a, **k: None
    try:
        try:
            Settings.from_env()
            raise AssertionError("no key must raise")
        except MissingKey:
            pass
        os.environ["AI_AGENT_KEY"] = "sk-ant-secret-value"
        settings = Settings.from_env()
        assert settings.model == "claude-sonnet-5-5" and settings.fallbacks
        assert "secret" not in repr(settings) and "secret" not in str(settings)
        os.environ["AI_AGENT_MODEL"], os.environ["AI_AGENT_FALLBACKS"] = "claude-opus-5-5", "off"
        settings = Settings.from_env()
        assert settings.model == "claude-opus-5-5" and not settings.fallbacks
    finally:
        config.load_env = original
        for name, value in saved.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value


def test_with_effort_changes_one_stage_only():
    s = SETTINGS.with_effort(obligations="low")
    assert s.effort["obligations"] == "low" and s.effort["regulations"] == SETTINGS.effort["regulations"]


# ------------------------------------------------------------------------------------------------------------ ledger
def test_ledger_prices_a_call_and_stops_before_the_budget_is_passed():
    ledger = Ledger("claude-sonnet-5-5", 0.01)
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0}
    assert abs(ledger.cost(usage) - (2.0 + 1.0 + 0.2)) < 1e-9
    ledger.check()
    ledger.add("obligations", usage, 1.0, cached=False)
    ledger.add("obligations", usage, 0.0, cached=True)
    assert abs(ledger.spent - 3.2) < 1e-9 and abs(ledger.replayed - 3.2) < 1e-9
    try:
        ledger.check()
        raise AssertionError("over budget must raise")
    except BudgetExceeded:
        pass


# --------------------------------------------------------------------------------------------------------- LLM layer
def test_llm_request_uses_effort_and_no_forbidden_parameter_and_caches_only_when_asked():
    client = FakeClient([('{"a": 1}', "end_turn"), ("ok", "end_turn")])
    model = LLM(Settings(api_key="k", cache_dir=None, fallbacks=False), client=client)
    out = model.complete_json(stage="profile", label="x", system="sys", user="hi", schema={"type": "object"})
    assert out == {"a": 1}
    beta, kwargs = client.calls[0]
    assert not beta and kwargs["output_config"]["effort"] == SETTINGS.effort["profile"] and kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "cache_control" not in kwargs and kwargs["model"] == "claude-sonnet-5-5"  # a prompt sent once would only pay the cache write premium
    for forbidden in ("temperature", "top_p", "top_k", "tool_choice", "thinking"):  # Sonnet 5.5 rejects these (400)
        assert forbidden not in kwargs
    model.call(stage="sections", label="y", system="s", messages=[{"role": "user", "content": "q"}], auto_cache=True)
    assert client.calls[1][1]["cache_control"] == {"type": "ephemeral"}


def test_llm_fallbacks_use_the_beta_endpoint_and_tools_stream_eagerly():
    client = FakeClient([("ok", "end_turn")])
    model = LLM(Settings(api_key="k", cache_dir=None, fallbacks=True), client=client)
    model.call(stage="sections", label="x", system="s", messages=[{"role": "user", "content": "q"}],
               tools=[{"name": "t", "description": "d", "input_schema": {"type": "object"}}])
    beta, kwargs = client.calls[0]
    assert beta and kwargs["betas"] == [llm.FALLBACK_BETA] and kwargs["fallbacks"] == "default"
    assert kwargs["tools"][0]["eager_input_streaming"] is True


def test_llm_replays_an_identical_request_from_the_disk_cache_for_free():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(api_key="k", cache_dir=Path(tmp), fallbacks=False)
        client = FakeClient([("first", "end_turn"), ("second", "end_turn")])
        model = LLM(settings, client=client)
        args = dict(stage="profile", label="x", system="s", messages=[{"role": "user", "content": "same"}])
        a, b = model.call(**args), model.call(**args)
        assert a.text == b.text == "first" and not a.cached and b.cached and len(client.calls) == 1
        row = model.ledger.stages["profile"]
        assert row["calls"] == 1 and row["replayed_calls"] == 1 and row["spent"] > 0 and abs(row["spent"] - row["replayed"]) < 1e-9
        c = model.call(stage="profile", label="x", system="s", messages=[{"role": "user", "content": "different"}])
        assert c.text == "second" and len(client.calls) == 2


def test_complete_json_asks_again_with_more_room_when_the_answer_was_cut_off():
    client = FakeClient([('{"a": ', "max_tokens"), ('{"a": 2}', "end_turn")])
    model = LLM(Settings(api_key="k", cache_dir=None, fallbacks=False), client=client)
    assert model.complete_json(stage="profile", label="x", system="s", user="u", schema={"type": "object"}, max_tokens=1000) == {"a": 2}
    assert client.calls[0][1]["max_tokens"] == 1000 and client.calls[1][1]["max_tokens"] == 2000


def test_complete_json_raises_refused_on_a_decline():
    class Declining(LLM):
        def call(self, **kw):
            return Reply([], "refusal", "m", {}, {"category": "cyber", "explanation": "no"})

    try:
        Declining(SETTINGS, client=object()).complete_json(stage="profile", label="x", system="s", user="u", schema={})
        raise AssertionError("must raise")
    except llm.Refused as error:
        assert error.category == "cyber"


# --------------------------------------------------------------------------------------------------------- tool loop
def test_tool_loop_answers_every_tool_call_in_one_message_and_keeps_the_history_append_only():
    seen = []

    def script(stage, label, system, messages, tools_, schema):
        seen.append([m["role"] for m in messages])
        if len(messages) == 1:  # two parallel calls in one turn, one of them bad
            return [{"type": "thinking", "thinking": "", "signature": "abc"}, tool_use("a", "get_toc", {}), tool_use("b", "read_node", {"node": "zzz"})], "tool_use"
        return [tool_use("c", "select_sections", {"selections": [{"node": "5.1", "category": "function", "reason": "r"}]})], "tool_use"

    g = synthetic()
    box = tools.WalkerTools(g)
    model = Scripted(script)
    result = model.run_tools(stage="sections", label="t", system="s", first_user="go", tools=box.schemas, handle=box.handle, done=lambda: box.done,
                             max_turns=5)
    assert result.finished and result.turns == 2 and box.done
    assert all(r["auto_cache"] for r in model.requests)  # the history of a loop is read again every turn
    first = model.requests[1]["messages"]
    assert [m["role"] for m in first] == ["user", "assistant", "user"]
    assert first[1]["content"][0]["type"] == "thinking" and first[1]["content"][0]["signature"] == "abc"  # passed back unchanged
    results = first[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"] and results[0]["is_error"] is False and results[1]["is_error"] is True
    assert "Closest labels" in results[1]["content"] or "No node" in results[1]["content"]
    assert seen[1][:len(seen[0])] == seen[0]  # what was sent before is a prefix of what is sent next


def test_tool_loop_nudges_a_model_that_stops_without_submitting_then_gives_up():
    def script(stage, label, system, messages, tools_, schema):
        return text_reply("I am done."), "end_turn"

    box = tools.WalkerTools(synthetic())
    model = Scripted(script)
    result = model.run_tools(stage="sections", label="t", system="s", first_user="go", tools=box.schemas, handle=box.handle, done=lambda: box.done,
                             max_turns=10, nudge="submit now")
    assert not result.finished and "without submitting" in result.reason
    assert sum(1 for m in model.requests[-1]["messages"] if m["role"] == "user" and m["content"] == "submit now") == 2


def test_tool_loop_retries_a_cut_off_turn_with_more_room_without_sending_it_back():
    calls = []

    def script(stage, label, system, messages, tools_, schema):
        calls.append(len(messages))
        if len(calls) == 1:
            return [tool_use("x", "select_sections", {"selections": [{"node": "5.1"}]})], "max_tokens"  # truncated: must not be run
        return [tool_use("y", "select_sections", {"selections": [{"node": "5.1", "category": "function", "reason": "r"}]})], "tool_use"

    box = tools.WalkerTools(synthetic())
    model = Scripted(script)
    result = model.run_tools(stage="sections", label="t", system="s", first_user="go", tools=box.schemas, handle=box.handle, done=lambda: box.done,
                             max_turns=4)
    assert result.finished and calls == [1, 1] and model.requests[1]["max_tokens"] == 2 * model.requests[0]["max_tokens"]


# ------------------------------------------------------------------------------------------------------------- store
def test_label_key_is_the_platforms_normalisation():
    from score_local import _paragraph_key
    for sample in ("5.4.2.3.", "Annex 8, 2.1.", "annex 8  2.1.", "Annex 4, Part 1, 1.2", "paragraph 5.4.2.3", "5.1.4.4.1. Table 3", "§ 6.10", "5.4.23",
                   "Annex 6 Part 6 3. Table A6-1", ""):
        assert store.label_key(sample) == (_paragraph_key(sample) or ""), sample


def test_quote_tokens_ignore_punctuation_pipes_and_thousands_separators():
    assert store.norm_tokens("not more than 1,500 mm.") == store.norm_tokens("not more than 1500 mm") == ["not", "more", "than", "1500", "mm"]
    assert store.norm_tokens("| IA, IB | Red |") == ["ia", "ib", "red"]
    assert store.find_run(["a", "b", "c", "d"], ["b", "c"]) == 1 and store.find_run(["a", "b"], ["c"]) == -1


def test_resolve_accepts_the_usual_spellings_and_suggests_for_the_rest():
    g = synthetic()
    assert g.resolve("5.1") == g.resolve("5.1.") == g.resolve("paragraph 5.1") == g.resolve("UN R150 5.1") == 1
    assert g.resolve("annex 1  1") == g.resolve("Annex 1 1") == 6 and g.resolve("5.9") is None
    assert "5.1" in g.suggest("5.11") and g.resolve(None) is None


def test_subtree_outline_and_toc_show_sizes_and_structure():
    g = synthetic()
    assert g.subtree(0) == [0, 1, 2, 3, 4] and g.subtree(3) == [3, 4] and g.contained(0, 4) and not g.contained(3, 2)
    outline = g.outline().splitlines()
    assert outline[0].startswith("5 | Specifications | p3-4 | 5 nodes") and any(row.startswith("Annex 1 [annex]") for row in outline)
    assert "5.1.1" not in g.outline()  # a leaf is not an outline entry
    assert g.toc(0, 1).count("\n") == 1 and "5.1.1" in g.toc(0, 2)


def test_render_gives_id_page_and_parent_and_search_finds_by_breadcrumb():
    g = synthetic()
    assert g.render([2]).startswith('<node id="5.1.1" page="3" parent="5.1">')
    assert g.search("marking legible indelible")[0][0] == 4


def test_locate_finds_a_verbatim_quote_moves_a_misplaced_one_and_refuses_an_invented_one():
    g = synthetic()
    quote = "marking shall be clearly legible and indelible, also after 1500 hours"
    assert g.locate(quote, 4, range(7)) == (4, 1.0)
    assert g.locate(quote, 2, range(7)) == (4, 1.0)  # named the wrong node: found in the right one
    assert g.locate("The lamp shall glow purple at midnight", 4, range(7)) is None
    assert g.locate("shall be", 4, range(7)) is None  # two tokens prove nothing
    near = g.locate("the marking shall be clearly legible and indelible also after 1,500 hour of exposure", 4, [])
    assert near is not None and near[1] >= store.FUZZY_QUOTE


def test_page_of_gives_the_page_of_the_line_where_the_quote_starts():
    n = node("5.5", "5.5. First line of a long paragraph", 7)
    n.text += ["that continues on the next page"]
    n.pages += [8]
    n.page_end = 8
    g = store.RegGraph("UN R150", doc=ParsedDocument(Path("s.pdf"), 9, [n]))
    assert g.page_of(0, "that continues on the next page") == 8 and g.page_of(0, "First line of a long") == 7
    assert g.page_of(0, "not in the text at all") == 7  # falls back to the first page of the node


def test_edges_resolve_paragraph_references_and_name_cited_regulations():
    g = synthetic()
    assert g.references(g.resolve("Annex 1 1"))["refers_to"] == [3]  # "as in paragraph 5.2"
    assert store.cited_regulations("approved according to UN Regulation No. 7, or to Regulations Nos. 13 and 13-H; the 00 series of R48") == [
        "UN R7", "UN R13", "UN R13H"]


# ------------------------------------------------------------------------------------------------------------ tools
def test_select_sections_rejects_unknown_labels_and_bad_excludes_then_accepts():
    g = synthetic()
    box = tools.WalkerTools(g)
    bad = box.handle("select_sections", {"selections": [{"node": "9.9", "category": "function", "reason": "r"},
                                                          {"node": "5.1", "category": "function", "reason": "r", "exclude": ["5.2"]},
                                                          {"node": "5.2", "category": "nonsense", "reason": "r"}]})
    assert bad.is_error and not box.done and "9.9" in bad.text and "not below" in bad.text and "category" in bad.text
    ok = box.handle("select_sections", {"selections": [{"node": "5", "category": "general", "reason": "r", "exclude": ["5.1"]}]})
    assert not ok.is_error and box.done and "Accepted" in ok.text
    assert tools.expand(g, box.selections) == [0, 3, 4]  # 5.1 and its child are excluded


def test_read_and_search_tools_answer_with_nodes_and_errors():
    box = tools.WalkerTools(synthetic())
    assert "5.1.1" in box.handle("read_node", {"node": "5.1", "subtree": True}).text
    assert box.handle("read_node", {"node": "7.7"}).is_error
    assert "5.2.1" in box.handle("search", {"query": "indelible"}).text
    assert "(exact label)" in box.handle("search", {"query": "5.2"}).text
    assert "Cites" in box.handle("follow_refs", {"node": "Annex 1 1"}).text or "Refers to" in box.handle("follow_refs", {"node": "Annex 1 1"}).text
    assert box.handle("nope", {}).is_error


# --------------------------------------------------------------------------------------------------------- obligations
def test_ground_accepts_reassigns_and_rejects():
    g = synthetic()
    chunk = obligations.Chunk("UN R150", 1, [3, 4], [], 100)
    good = obligations.ground(g, chunk, {"node": "5.2.1", "quote": "marking shall be clearly legible and indelible", "text": "The marking shall be legible.",
                                         "modality": "obligation", "addressee": "product", "kind": "marking", "applies": "certain", "why": ""})
    assert good["node"] == "5.2.1" and good["paragraph"] == "5.2.1" and good["page"] == 4 and good["reassigned"] is False and good["status"] == ""
    moved = obligations.ground(g, chunk, {"node": "5.2", "quote": "marking shall be clearly legible and indelible", "text": "t",
                                          "modality": "obligation", "addressee": "product", "kind": "marking", "applies": "certain", "why": ""})
    assert moved["node"] == "5.2.1" and moved["reassigned"] is True
    gone = obligations.ground(g, chunk, {"node": "5.2.1", "quote": "the lamp shall glow purple at midnight", "text": "t", "modality": "obligation",
                                         "addressee": "product", "kind": "design", "applies": "certain", "why": ""})
    assert gone["status"] == "rejected:quote" and gone["node"] is None
    outside = obligations.ground(g, chunk, {"node": "5.1.1", "quote": "reflecting surface shall be not less than 20 cm2", "text": "t",
                                            "modality": "obligation", "addressee": "product", "kind": "design", "applies": "certain", "why": ""})
    assert outside["status"] == "rejected:quote"  # real text, but of a node that is not in this chunk: not groundable here


def test_plan_chunks_partitions_in_document_order_and_names_the_context():
    g = synthetic()
    one = obligations.plan_chunks(g, list(range(7)), 10_000)
    assert len(one) == 1 and one[0].nodes == list(range(7))
    small = obligations.plan_chunks(g, list(range(7)), 120)
    flat = [i for c in small for i in c.nodes]
    assert flat == list(range(7)) and len(small) > 1
    deep = obligations.plan_chunks(g, [4], 10_000)  # a leaf selected alone: its context is the titles above it
    assert deep[0].context == ["5.2"] or deep[0].context == [g.nodes[3].path]


def test_extraction_prompt_has_the_profile_cached_first_and_the_chunk_after():
    g = synthetic()
    chunk = obligations.plan_chunks(g, list(range(7)), 10_000)[0]
    content = obligations.chunk_content(g, chunk, "Product: lamp")
    assert content[0]["cache_control"] == {"type": "ephemeral"} and content[0]["text"].startswith("Product profile:")
    assert '<node id="5.2.1"' in content[1]["text"] and "cache_control" not in content[1]
    assert "Give an entry for each of the 7 nodes" in content[1]["text"]


def _item(quote, text, **kw):
    return {"quote": quote, "text": text, "modality": "obligation", "addressee": "product", "kind": "design", "applies": "certain", "why": "w", **kw}


def test_extract_chunk_hands_skipped_nodes_back_once_and_marks_where_each_candidate_came_from():
    g = synthetic()
    chunk = obligations.plan_chunks(g, list(range(7)), 10_000)[0]
    seen_repair = []

    def script(stage, label, system, messages, tools_, schema):
        body = messages[0]["content"][1]["text"]
        if "left out of your answer" in body:
            ids = re.findall(r'<node id="([^"]+)"', body)
            seen_repair.append(ids)
            return text_reply({"nodes": [{"node": i, "obligations": [_item("The marking shall be clearly legible", "The marking shall be legible.")]
                                          if i == "5.2.1" else []} for i in ids]}), "end_turn"
        return text_reply({"nodes": [{"node": "5", "obligations": []},
                                     {"node": "5.1", "obligations": [_item("The retro-reflector shall emit red light", "The retro-reflector shall emit red light.")]},
                                     {"node": "5.1.1", "obligations": []},  # says "shall" but lists nothing
                                     {"node": "5.2", "obligations": []}]}), "end_turn"  # 5.2.1, the annex and its paragraph are missing

    candidates, stats = obligations.extract_chunk(Scripted(script), g, chunk, "profile")
    assert stats["missing"] == 3 and stats["silent_shall"] == 2 and stats["repaired_nodes"] == 5 and stats["repaired_obligations"] == 1
    assert sorted(seen_repair[0]) == sorted(["5.1.1", "5.2", "5.2.1", "Annex 1", "Annex 1 1"]) and len(seen_repair) == 1
    assert [(c["paragraph"], c["source"]) for c in candidates] == [("5.1", "answer"), ("5.2.1", "repair")]


def test_extract_chunk_makes_no_second_call_when_every_node_is_covered():
    g = synthetic()
    chunk = obligations.plan_chunks(g, list(range(7)), 10_000)[0]
    calls = []

    quotes = {1: "retro-reflector shall emit red light", 2: "shall be not less than 20 cm2", 3: "The lamp shall glow purple", 4: "shall be clearly legible and indelible"}

    def script(stage, label, system, messages, tools_, schema):
        calls.append(label)  # every node has an entry; the nodes that say "shall" have an obligation, the rest an empty list
        return text_reply({"nodes": [{"node": g.ids[i], "obligations": [_item(quotes[i], "t")] if i in quotes else []} for i in chunk.nodes]}), "end_turn"

    candidates, stats = obligations.extract_chunk(Scripted(script), g, chunk, "p")
    assert len(calls) == 1 and stats["missing"] == 0 and stats["silent_shall"] == 0 and stats["repaired_nodes"] == 0
    assert [c["status"] for c in candidates].count("rejected:quote") == 1 and len(candidates) == 4  # the invented quote under 5.2 is the one rejected


def test_the_system_prompt_names_every_label_the_schema_allows():
    for value in obligations.MODALITY + obligations.ADDRESSEE + obligations.KIND + obligations.APPLIES:
        assert value in obligations.SYSTEM, value
    item = obligations.SCHEMA["properties"]["nodes"]["items"]["properties"]["obligations"]["items"]
    assert item["properties"]["applies"]["enum"] == obligations.APPLIES and set(item["required"]) == set(item["properties"])


def test_corpus_the_examples_in_the_prompt_are_the_experts_own_words():
    """The few-shot examples are copied from UN R175 and subgoal/dev/requirements_old.json: a typo would teach the model our words, not theirs."""
    from regcomp import corpus
    path = ROOT / "subgoal" / "dev" / "requirements_old.json"
    if not path.is_file() or corpus.pdf_path(corpus.entry_for("UN R175"), "base") is None:
        raise Skip("subgoal/dev or the R175 PDF is missing")
    squash = lambda s: " ".join(s.split())
    prompt = squash(obligations.EXAMPLES)
    data = json.loads(path.read_text(encoding="utf-8"))
    experts = [r for r in (data["requirements"] if isinstance(data, dict) else data) if store.label_key(r["source"]["paragraph"]) in
               {store.label_key(p) for p in obligations.EXAMPLE_PARAGRAPHS}]
    assert len(experts) >= 10
    for r in experts:
        assert squash(r["text"]) in prompt, r["id"]
    g = store.RegGraph("UN R175", grids=False)
    for label in obligations.EXAMPLE_PARAGRAPHS:
        text = squash(re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", g.nodes[g.resolve(label)].body))
        assert text in prompt, label


# ------------------------------------------------------------------------------------------------------------ emit
def cand(**kw):
    base = {"regulation": "UN R150", "version": "1.2.1", "node": "5.2.1", "node_idx": 4, "paragraph": "5.2.1", "page": 4, "text": "The marking shall be legible.",
            "quote": "q", "modality": "obligation", "addressee": "product", "kind": "marking", "applies": "certain", "why": "", "status": "", "ordinal": 0}
    return {**base, **kw}


def test_policy_keeps_obligations_on_the_product_and_records_why_the_rest_is_dropped():
    cs = [cand(), cand(modality="permission", text="a"), cand(addressee="manufacturer_process", text="b"), cand(addressee="product_via_test", text="c"),
          cand(applies="unlikely", text="d"), cand(applies="possible", text="e"), cand(status="rejected:quote", text="f"), cand()]
    emit.apply_policy(cs)
    assert [c["status"] for c in cs] == ["emitted", "dropped:modality=permission", "dropped:addressee=manufacturer_process", "emitted",
                                         "dropped:applies=unlikely", "emitted", "rejected:quote", "dropped:duplicate"]


def test_submission_cites_from_the_node_orders_by_regulation_and_numbers_the_ids():
    cs = [cand(regulation="UN R10", version="7.2.0", node_idx=2, paragraph="6.1", text="x shall y"), cand(node_idx=9, paragraph="5.9", text="m shall n"),
          cand(node_idx=3, paragraph="5.2", text="p shall q")]
    emit.apply_policy(cs)
    sub, trace = emit.build_submission(cs, ["UN R150", "UN R10"], "case-x", "team-9")
    assert [r["source"]["paragraph"] for r in sub["requirements"]] == ["5.2", "5.9", "6.1"]
    assert [r["id"] for r in sub["requirements"]] == ["R-001", "R-002", "R-003"] and sub["team_id"] == "team-9" and sub["case_id"] == "case-x"
    assert sub["requirements"][2]["source"] == {"regulation": "UN R10", "version": "7.2.0", "page": 4, "paragraph": "6.1"}
    assert len(trace) == 3 and trace[0]["id"] == "R-001"


def test_text_longer_than_the_platform_allows_is_cut_at_a_sentence_end():
    long = ("The device shall do a thing. " * 100).strip()
    cut = emit.fit(long)
    assert len(cut) <= 2000 and cut.endswith("thing.") and emit.fit("short") == "short"


def test_corpus_submission_validates_with_the_platforms_own_check():
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        raise Skip("jsonschema is not installed")
    sub = {"team_id": "t", "case_id": "c", "requirements": [{"id": "R-001", "text": "x shall y", "source": {"regulation": "UN R150", "version": "1.2.1",
                                                                                                           "page": 7, "paragraph": "3.3.1.1"}}]}
    assert emit.validate_submission(sub) == []
    sub["requirements"][0]["source"]["version"] = "9.9.9"
    sub["requirements"][0]["extra"] = 1
    problems = emit.validate_submission(sub)
    assert any("not a version of UN R150" in p for p in problems) and any("Not part of the format" in p for p in problems)


# --------------------------------------------------------------------------------------------------------- hygiene
def test_the_agent_never_opens_the_expected_answer():
    """The expected file is the benchmark's: no string in the agent's code (docstrings aside) may name it."""
    offenders = []
    for path in sorted((ROOT / "src" / "ai_agent").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                      and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings and "expected" in n.value.lower():
                offenders.append(f"{path.name}:{n.lineno}: {n.value[:50]!r}")
    assert not offenders, offenders


# ----------------------------------------------------------------------------------------------------------- corpus
def test_corpus_cards_read_supersession_and_categories_from_the_pdfs():
    from ai_agent import catalog
    from regcomp import corpus
    if corpus.pdf_path(corpus.entry_for("UN R148"), "base") is None:
        raise Skip("regulations/data has no PDFs")
    card = catalog.build_card("UN R148")
    assert {"UN R7", "UN R23", "UN R6", "UN R38"} <= set(card["supersedes"]) and card["version"] == "1.6.0"
    assert catalog.build_card("UN R48")["categories"] == ["M", "N", "O"] and "Rear position lamp" in catalog.build_card("UN R48")["toc"]
    cat = catalog.Catalog(cache_dir=None)
    cat.names, cat.cards = ["UN R7", "UN R148"], {"UN R148": card, "UN R7": {**card, "supersedes": []}}
    assert cat.successor("UN R7") == "UN R148" and cat.successor("UN R148") == "UN R148"


def test_corpus_chunks_cover_the_selected_nodes_once_and_stay_under_the_limit():
    from regcomp import corpus
    if corpus.pdf_path(corpus.entry_for("UN R48"), "base") is None:
        raise Skip("regulations/data has no PDFs")
    g = store.RegGraph("UN R48", grids=False)
    picked = sorted(set(g.subtree(g.resolve("5")) + g.subtree(g.resolve("6.10")) + g.subtree(g.resolve("Annex 3"))))
    chunks = obligations.plan_chunks(g, picked, 12_000)
    flat = [i for c in chunks for i in c.nodes]
    assert flat == picked and len(chunks) > 3
    assert all(c.chars <= 12_000 or len(c.nodes) == 1 for c in chunks)
    mid = next(c for c in chunks if g.parent[c.nodes[0]] not in c.nodes and g.parent[c.nodes[0]] >= 0)
    assert mid.context and all("›" in x or x for x in mid.context)


def test_corpus_the_whole_chain_runs_on_a_scripted_model_and_writes_a_valid_submission():
    from ai_agent import catalog as catalog_module
    from ai_agent.pipeline import run_case
    from regcomp import corpus
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        raise Skip("jsonschema is not installed")
    if corpus.pdf_path(corpus.entry_for("UN R150"), "base") is None:
        raise Skip("regulations/data has no PDFs")
    real = store.RegGraph("UN R150", grids=False)
    section = max(((n.label, real.sub_content[i]) for i, n in enumerate(real.nodes) if n.kind == "para" and not n.scope and len(n.num) == 2
                   and n.num[0] >= 3), key=lambda item: item[1])[0]  # the largest depth-2 section of the body
    profile = {"product": "test lamp", "summary": "s", "vehicle_categories": ["M1"], "functions": [{"key": "F1", "name": "f", "detail": ""}],
               "parts": [{"key": "P1", "name": "p", "role": "r", "materials": ["PMMA"]}], "technologies": [{"key": "T1", "name": "t", "regulatory_concepts": ["c"]}],
               "attributes": [{"name": "colour", "value": "red", "source": "inferred"}], "regulatory_concepts": ["rc"], "not_present": ["np"]}

    def script(stage, label, system, messages, tools_, schema):
        if stage == "profile":
            return text_reply(profile), "end_turn"
        if stage == "regulations" and label == "select":  # R3 is superseded by R150: the redirect must merge the two
            pick = lambda reg: {"regulation": reg, "level": "device", "confidence": "high", "covers": ["P1"], "reason": "r"}
            return text_reply({"selected": [pick("UN R3"), pick("UN R150")], "close_calls": []}), "end_turn"
        if stage == "regulations":
            return text_reply({"add": [], "skip": []}), "end_turn"
        if stage == "sections":
            if len(messages) == 1:
                return [tool_use("t1", "get_toc", {"node": section, "depth": 1})], "tool_use"
            return [tool_use("t2", "select_sections", {"selections": [{"node": section, "category": "function", "reason": "r"}]})], "tool_use"
        if stage == "obligations":
            body = messages[0]["content"][1]["text"]
            found = re.findall(r'<node id="([^"]+)"[^>]*>\n(.*?)\n</node>', body, re.S)
            repair = "left out of your answer" in body
            entries = []
            for k, (nid, txt) in enumerate(found):
                if k % 7 == 6 and not repair:
                    continue  # skipped: the repair pass has to ask for it
                items = []
                if len(txt.split()) > 8:
                    items = [{"quote": " ".join(txt.split()[1:7]), "text": f"The device shall satisfy {nid}.", "modality": "obligation",
                              "addressee": "product", "kind": "design", "applies": ("certain", "likely", "possible", "unlikely")[k % 4], "why": "w"}]
                entries.append({"node": nid, "obligations": items})
            return text_reply({"nodes": entries}), "end_turn"
        raise AssertionError(stage)

    cat = catalog_module.Catalog(cache_dir=None)
    cat.names = ["UN R3", "UN R150"]
    cat.cards = {r: catalog_module.build_card(r) for r in cat.names}
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "case-x"
        case.mkdir()
        (case / "spec.md").write_text("# spec\n", encoding="utf-8")
        model = Scripted(script)
        result = run_case(case, SETTINGS, Path(tmp) / "run", log=lambda m: None, llm=model, catalog=cat)
        assert result.regulations == ["UN R150"] and result.problems == [] and not result.failures, (result.regulations, result.problems, result.failures)
        reqs = result.submission["requirements"]
        assert reqs, ([(c["status"], c.get("paragraph"), c["quote"][:40]) for c in result.candidates[:5]], len(result.candidates), result.failures)
        assert all(r["source"]["regulation"] == "UN R150" and r["source"]["version"] == "1.2.1" for r in reqs)
        by_label = {n.label: n for n in real.nodes}
        for r in reqs:
            n = by_label[r["source"]["paragraph"]]
            assert n.page_start <= r["source"]["page"] <= n.page_end
        statuses = {c["status"] for c in result.candidates}
        assert "emitted" in statuses and "dropped:applies=unlikely" in statuses
        for name in ("profile.json", "regulations.json", "sections.json", "citation_hop.json", "candidates.json", "submission.json", "trace.json",
                     "usage.json", "run.json", "chunks.json"):
            assert (Path(tmp) / "run" / name).is_file(), name
        regs = json.loads((Path(tmp) / "run" / "regulations.json").read_text(encoding="utf-8"))
        assert regs["redirects"] == {"UN R3": "UN R150"} and [s["regulation"] for s in regs["selected"]] == ["UN R150"]


def main(argv: list[str] | None = None) -> int:
    return run_tests(globals(), sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
