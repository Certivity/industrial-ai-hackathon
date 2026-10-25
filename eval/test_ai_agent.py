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


def test_policy_drops_conformity_of_production_and_the_baseline_policy_keeps_it():
    cs = [cand(kind="conformity-of-production"), cand(text="b", kind="design")]
    emit.apply_policy(cs)
    assert [c["status"] for c in cs] == ["dropped:kind=conformity-of-production", "emitted"]
    cs = [cand(kind="conformity-of-production")]
    emit.apply_policy(cs, emit.BASELINE_POLICY)
    assert cs[0]["status"] == "emitted" and emit.policy_summary(emit.BASELINE_POLICY)["name"] == "baseline-v1"


def test_policy_drops_a_regulation_without_certain_unless_it_was_picked_at_high_confidence():
    def make():
        return [cand(regulation="UN R48", text="a", page=5), cand(regulation="UN R48", text="b", page=5, applies="likely"),
                cand(regulation="UN R128", text="c", page=3, applies="likely"), cand(regulation="UN R128", text="d", page=3, applies="likely"),
                cand(regulation="UN R10", text="e", page=9, applies="likely"), cand(regulation="UN R10", text="f", page=9, applies="likely")]
    v1 = emit.PRECISION_V1
    cs = make()
    emit.apply_policy(cs, v1, confidence={"UN R48": "high", "UN R128": "medium", "UN R10": "high"})
    assert [c["status"] for c in cs] == ["emitted", "emitted", "dropped:regulation=no_certain", "dropped:regulation=no_certain", "emitted", "emitted"]
    cs = make()
    emit.apply_policy(cs, v1)  # no confidences: the check is skipped
    assert all(c["status"] == "emitted" for c in cs)
    cs = [c for c in make() if c["regulation"] != "UN R48"]  # every regulation weak: keep them all
    emit.apply_policy(cs, v1, confidence={"UN R128": "low", "UN R10": "medium"})
    assert all(c["status"] == "emitted" for c in cs)
    cs = make()  # the default policy leaves the check off: a correct regulation with few `certain` grades must not be lost
    emit.apply_policy(cs, confidence={"UN R48": "high", "UN R128": "medium", "UN R10": "medium"})
    assert all(c["status"] == "emitted" for c in cs) and emit.DEFAULT_POLICY.name == "precision-v2"


def test_policy_drops_a_page_that_carries_only_a_few_possible_candidates():
    cs = [cand(text="a", page=4, applies="possible"), cand(text="b", page=4, applies="possible"), cand(text="c", page=5, applies="possible"),
          cand(text="d", page=5, applies="likely"), cand(text="e", page=6, applies="possible"), cand(text="f", page=6, applies="possible"),
          cand(text="g", page=6, applies="possible"), cand(text="h", page=6, applies="possible")]
    emit.apply_policy(cs)
    assert [c["status"] for c in cs] == ["dropped:page=only_possible"] * 2 + ["emitted"] * 6
    cs = [cand(text="a", page=4, applies="possible")]
    emit.apply_policy(cs, emit.BASELINE_POLICY)
    assert cs[0]["status"] == "emitted"


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


# --------------------------------------------------------------------------------------------------------- inputs, vision, component map
def _strict(schema) -> bool:
    if isinstance(schema, dict):
        if schema.get("type") == "object" and (schema.get("additionalProperties") is not False or set(schema.get("required", [])) != set(schema["properties"])):
            return False
        return all(_strict(v) for v in schema.values())
    if isinstance(schema, list):
        return all(_strict(v) for v in schema)
    return True


def _png(path: Path, size=(3000, 1800)) -> Path:
    from PIL import Image
    Image.new("RGB", size, "white").save(path)
    return path


FACTS = {"image": "d.png", "info": {}, "drawing_kind": "exploded_view", "title": "", "text_blocks": [], "unlabelled_parts": [{"description": "clip", "region": {}}],
         "legend": [], "notes": [], "components": [
             {"key": "C1", "name": "Outer lens", "callout_text": "Outer lens red, within the chromaticity limits", "text_ids": ["T1"], "function_hint": "colour",
              "values": [{"quantity": "colour", "value": "red", "unit": "", "raw": "red"}], "linked_by": "leader_line", "region": {}, "confidence": "high"},
             {"key": "C2", "name": "Reflector", "callout_text": "Reflector rear position lamp: 4 to 17 cd on axis", "text_ids": ["T2"],
              "function_hint": "rear position lamp intensity", "values": [{"quantity": "luminous intensity", "value": "4 to 17", "unit": "cd", "raw": "4 to 17 cd"}],
              "linked_by": "leader_line", "region": {}, "confidence": "medium"}]}
PROFILE = {"product": "lamp", "summary": "s", "vehicle_categories": ["M1"], "functions": [{"key": "F1", "name": "f", "detail": ""}],
           "parts": [{"key": "P1", "name": "Outer lens", "role": "r", "materials": ["PMMA"], "source": "both"},
                     {"key": "P2", "name": "Reflector surface", "role": "", "materials": [], "source": "spec"}],
           "technologies": [], "attributes": [{"name": "intensity", "value": "4 to 17 cd", "source": "image"}], "regulatory_concepts": ["rc"], "not_present": []}


def test_inputs_are_found_by_name_or_by_the_only_candidate_and_text_or_image_alone_is_enough():
    from ai_agent.inputs import NoInput, find_inputs
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name in ("spec.md", "technical_spec.md", "README.md"):
            (d / name).write_text("x", encoding="utf-8")
        found = find_inputs(d)
        assert found.text_path.name == "spec.md" and found.image_path is None
        (d / "spec.md").unlink()
        assert find_inputs(d).text_path.name == "technical_spec.md"
        (d / "technical_spec.md").unlink()
        try:
            find_inputs(d)
            raise AssertionError("a README alone is no input")
        except NoInput as error:
            assert "no input" in str(error)
        (d / "view.JPG").write_bytes(b"x")
        only_image = find_inputs(d)
        assert only_image.text_path is None and only_image.image_path.name == "view.JPG" and only_image.read_text() is None
        (d / "exploded_view.png").write_bytes(b"x")
        (d / "spec.md").write_text("t", encoding="utf-8")
        both = find_inputs(d)
        assert both.image_path.name == "exploded_view.png" and both.read_text() == "t"
        assert find_inputs(d, use_image=False).image_path is None
        assert find_inputs(d, image="view.JPG").image_path.name == "view.JPG"
        try:
            find_inputs(d, use_text=False, use_image=False)
            raise AssertionError("neither text nor image must be an error")
        except NoInput:
            pass


def test_vision_prepare_sends_the_whole_image_within_the_api_limits_and_tiles_a_big_one_from_the_original_pixels():
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise Skip("PIL is not installed")
    import base64
    import io
    from PIL import Image
    from ai_agent import vision
    with tempfile.TemporaryDirectory() as tmp:
        big = vision.prepare(_png(Path(tmp) / "big.png"))
        small = vision.prepare(_png(Path(tmp) / "small.png", (900, 600)))
    w, h = big["info"]["sent_whole"]
    assert max(w, h) <= vision.MAX_EDGE and w * h <= vision.MAX_PIXELS, (w, h)
    assert len(big["tiles"]) == 4 and small["tiles"] == []
    boxes = [box for _, box in big["tiles"]]
    assert min(b[0] for b in boxes) == 0 and max(b[2] for b in boxes) >= 0.999 and min(b[1] for b in boxes) == 0 and max(b[3] for b in boxes) >= 0.999
    assert boxes[0][2] > boxes[1][0], "neighbouring tiles overlap"
    tile = Image.open(io.BytesIO(base64.b64decode(big["tiles"][0][0]["source"]["data"])))
    assert tile.size[0] <= 1700, tile.size  # native pixels, not shrunk
    assert big["whole"]["source"]["media_type"] == "image/png" and big["whole"]["type"] == "image"


def test_read_drawing_sends_images_then_the_transcription_and_returns_the_facts():
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise Skip("PIL is not installed")
    from ai_agent import vision
    seen = []
    read = {"drawing_kind": "exploded_view", "title": "", "text_blocks": [{"id": "T1", "text": "Outer lens", "role": "component_label",
                                                                          "box": {"x0": 0.7, "y0": 0.1, "x1": 0.8, "y1": 0.2}}]}
    mapped = {"components": FACTS["components"][:1], "unlabelled_parts": [], "legend": [], "notes": []}

    def script(stage, label, system, messages, tools_, schema):
        seen.append((stage, label, messages[0]["content"], schema))
        return text_reply(read if label == "read" else mapped), "end_turn"
    with tempfile.TemporaryDirectory() as tmp:
        facts = vision.read_drawing(Scripted(script), _png(Path(tmp) / "d.png"), SETTINGS, None, lambda m: None)
    assert [s[1] for s in seen] == ["read", "map"] and all(s[0] == "vision" for s in seen)
    assert sum(b["type"] == "image" for b in seen[0][2]) == 5  # the whole picture and four tiles
    map_blocks = seen[1][2]
    assert sum(b["type"] == "image" for b in map_blocks) == 1 and "T1 [component_label]" in map_blocks[-1]["text"]
    assert facts["components"][0]["name"] == "Outer lens" and facts["text_blocks"][0]["id"] == "T1" and facts["info"]["size"] == [3000, 1800]
    assert _strict(vision.READ_SCHEMA) and _strict(vision.MAP_SCHEMA)
    assert "vision" in config.DEFAULT_EFFORT and "components" in config.DEFAULT_EFFORT


def test_text_only_profile_request_is_the_one_it_always_was_and_a_drawing_changes_prompt_and_schema():
    from ai_agent import profile
    seen = []

    def script(stage, label, system, messages, tools_, schema):
        seen.append((system, messages[0]["content"], schema))
        return text_reply(PROFILE), "end_turn"
    model = Scripted(script)
    profile.build_profile(model, "# spec\nabc\n")
    system, user, schema = seen[-1]
    assert system == profile.SYSTEM and schema is profile.SCHEMA and "drawing" not in user.lower()
    assert user == "Specification (markdown):\n\n<spec>\n# spec\nabc\n</spec>\n\nWrite the profile."
    profile.build_profile(model, "# spec\nabc\n", FACTS)
    system, user, schema = seen[-1]
    assert system.endswith(profile.IMAGE_RULES) and "<drawing>" in user and "Reflector" in user
    assert schema is profile.IMAGE_SCHEMA and _strict(schema) and _strict(profile.SCHEMA)
    assert schema["properties"]["parts"]["items"]["properties"]["source"]["enum"] == ["spec", "image", "both"]
    profile.build_profile(model, None, FACTS)
    assert "no written specification" in seen[-1][1]
    try:
        profile.build_profile(model, None, None)
        raise AssertionError("no input")
    except ValueError:
        pass


def test_profile_text_adds_the_drawing_callouts_only_when_there_are_facts():
    from ai_agent.profile import profile_text
    plain = profile_text(PROFILE)
    assert "Annotated requirements" not in plain
    with_image = profile_text(PROFILE, FACTS)
    assert with_image.startswith("Product: lamp")
    line = [l for l in with_image.splitlines() if l.startswith("Annotated requirements from the drawing")]
    assert len(line) == 1 and "4 to 17 cd on axis" in line[0] and "red, within the chromaticity limits" in line[0]
    assert with_image.replace(line[0] + "\n", "") == plain


def test_component_map_groups_assigns_and_matches_callouts_to_the_requirements():
    from ai_agent.components import build_component_map
    reqs = [{"id": f"R-{k}", "text": f"text {k}", "source": {"regulation": "UN R148", "version": "1", "page": 3, "paragraph": f"5.{k}"}} for k in (1, 2, 3)]
    trace = [{"id": r["id"], "regulation": "UN R148", "paragraph": r["source"]["paragraph"]} for r in reqs]

    def script(stage, label, system, messages, tools_, schema):
        assert stage == "components"
        if label == "group":
            return text_reply({"components": [{"id": "K1", "name": "Outer lens", "keys": ["P1", "C1"]},
                                               {"id": "K2", "name": "Reflector surface", "keys": ["P2", "C2"]}]}), "end_turn"
        if label.startswith("assign"):
            return text_reply({"assignments": [{"requirement": "R-1", "components": ["K1"]}, {"requirement": "R-2", "components": ["K2", "K9"]},
                                               {"requirement": "R-3", "components": []}]}), "end_turn"
        m = [{"requirement": "R-3", "relation": "same_quantity", "why": "intensity"}, {"requirement": "R-404", "relation": "same_topic", "why": "x"}]
        return text_reply({"callouts": [{"callout": "Q2", "matches": m}, {"callout": "Q9", "matches": []}]}), "end_turn"
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp)
        for name, data in (("profile.json", PROFILE), ("submission.json", {"case_id": "c", "requirements": reqs}), ("trace.json", trace), ("vision.json", FACTS)):
            (run / name).write_text(json.dumps(data), encoding="utf-8")
        result = build_component_map(Scripted(script), run, log=lambda m: None)
        assert json.loads((run / "component_map.json").read_text(encoding="utf-8")) == result
    by_id = {c["id"]: c for c in result["components"]}
    assert by_id["K1"]["requirement_ids"] == ["R-1"] and by_id["K1"]["sources"] == ["image", "spec"]
    assert by_id["K2"]["requirement_ids"] == ["R-2", "R-3"] and by_id["K2"]["via_callout"] == ["R-3"]  # unknown component K9 and unknown R-404 are ignored
    assert by_id["K2"]["regulations"]["UN R148"]["sections"] == ["5.2", "5.3"]
    assert result["whole_product_requirement_ids"] == ["R-3"] and len(result["callouts"]) == 1
    assert result["callouts"][0]["component"] == "K2" and result["callouts"][0]["matches"][0]["paragraph"] == "5.3"


# ------------------------------------------------------------------------------------------------------------ drift agent
def _version(rows, label="1.0", pages=None):
    from ai_agent import drift
    nodes = [node(lab, text, page) for lab, text, page in rows]
    return drift.Version(ParsedDocument(Path("synthetic.pdf"), 9, nodes), "UN R150", label)


DRIFT_OLD = [("5.1", "5.1. The lamp shall emit red light.", 3),
             ("5.2", "5.2. The lamp shall be marked with the trade name.", 3),
             ("5.3", "5.3. The marking shall be indelible and legible for 1,500 hours.", 4),
             ("5.4", "5.4. A sample of the lamp shall be submitted to the service.", 4),
             ("5.5", "5.5. The luminous intensity shall not be less than 40 cd at point A.", 5)]
DRIFT_NEW = [("5.1", "5.1. The lamp shall emit red light.", 4),  # the page shifts, the text does not
             ("5.2", "5.2. The lamp shall be marked with the trade name and the approval mark.", 4),
             ("5.3", "5.3. The lamp shall bear a date code.", 4),  # added; the old 5.3 becomes 5.4
             ("5.4", "5.4. The marking shall be indelible and legible for 1,500 hours.", 5),
             ("5.6", "5.6. The luminous intensity shall not be less than 40 cd at point A.", 5)]


def test_drift_align_tells_same_renumbered_modified_removed_and_added_apart():
    from ai_agent import drift
    old, new = _version(DRIFT_OLD), _version(DRIFT_NEW, "1.1")
    kinds = {(old.ids[m.old] if m.old is not None else None, new.ids[m.new] if m.new is not None else None): m for m in drift.align(old, new)}
    assert kinds[("5.1", "5.1")].kind == "SAME"  # a page shift is not a change
    assert kinds[("5.2", "5.2")].kind == "MODIFIED" and not kinds[("5.2", "5.2")].renumbered and kinds[("5.2", "5.2")].sim > 0.6
    assert kinds[("5.3", "5.4")].kind == "RENUMBERED" and kinds[("5.5", "5.6")].kind == "RENUMBERED"  # same text under another number
    assert kinds[("5.4", None)].kind == "REMOVED" and kinds[(None, "5.3")].kind == "ADDED"
    assert drift.counts(drift.align(old, new)) == {"SAME": 1, "RENUMBERED": 2, "MODIFIED": 1, "REMOVED": 1, "ADDED": 1}


def test_drift_a_moved_footnote_mark_and_a_reflowed_layout_are_not_changes():
    from ai_agent import drift
    one = Node("para", "5.1", "", (5, 1), 3, 3, ["5.1. The lamp¹ shall emit red light.", "1This provision does not apply to tail lamps."], [3, 3],
               note=[0, 1], parent=-1, path="5.1")
    two = Node("para", "5.1", "", (5, 1), 4, 4, ["5.1. The lamp² shall emit", "red light.", "2This provision does not apply to tail lamps."], [4, 4, 4],
               note=[0, 0, 1], parent=-1, path="5.1")
    old = drift.Version(ParsedDocument(Path("a.pdf"), 5, [one]), "UN R150", "1")
    new = drift.Version(ParsedDocument(Path("b.pdf"), 5, [two]), "UN R150", "2")
    assert [m.kind for m in drift.align(old, new)] == ["SAME"]


def test_drift_word_edits_group_nearby_changes_and_the_reason_has_the_example_format():
    from ai_agent import drift
    edits = drift.word_edits("The ACPE shall control acceleration from standstill.",
                             "The ACPE shall control acceleration both from standstill and, as relevant, while creeping.")
    assert [(e.op, e.old, e.new) for e in edits] == [("replace", "from standstill.", "both from standstill and, as relevant, while creeping.")]
    assert [(e.op, e.old, e.new) for e in drift.word_edits("The part is relevant", "The part is relevant if fitted")] == [("insert", "", "if fitted")]
    assert drift.modified_reason("UN R175", "1.0.0", "6.6", "6.5", "A shall pass", "A shall pass if relevant.") == \
        "Paragraph 6.6 (formerly 6.5) of UN R175 was amended in version 1.0.0: 'if relevant.' was added."
    assert drift.modified_reason("UN R175", "1.0.0", "5.1.2", None, "Speed of 5 km/h.", "Speed of 7 km/h.") == \
        "Paragraph 5.1.2 of UN R175 was amended in version 1.0.0: '5' became '7'."
    assert drift.removed_reason("UN R175", "1.0.0", "6.5", "Before any test the vehicle may be driven.").startswith(
        "Paragraph 6.5 of UN R175 was amended in version 1.0.0; the provision 'Before any test")
    assert drift.added_reason("UN R175", "1.0.0", "6.5.3", "x" * 300).endswith("…'.") and "is new in version 1.0.0" in drift.added_reason(
        "UN R175", "1.0.0", "6.5.3", "x")


class DriftModel:
    """A scripted LLM for the drift agent: records every call, answers the judge by the paragraph it is shown and the extraction by the nodes."""

    def __init__(self):
        self.s, self.ledger, self.calls = SETTINGS, Ledger("claude-sonnet-5-5", 5.0), []

    def complete_json(self, *, stage, label, system, user, schema, effort=None, max_tokens=0):
        self.calls.append((stage, label, effort))
        if stage == "drift_judge":
            ids = re.findall(r"^(R-\d+):", user, re.M)
            if label == "5.2":
                return {"requirements": [{"id": i, "verdict": "modified", "new_text": "The lamp shall be marked with the trade name and the approval mark.",
                                          "new_paragraph": "5.2", "note": "mark added"} for i in ids], "new_obligations": []}
            return {"requirements": [{"id": i, "verdict": "removed", "new_text": "", "new_paragraph": "", "note": "gone"} for i in ids], "new_obligations": []}
        return {"nodes": [{"node": "5.3", "requirements": [{"quote": "The lamp shall bear a date code.", "text": "The lamp shall bear a date code."},
                                                           {"quote": "invented words nowhere in the node", "text": "The lamp shall glow."}]}]}


def test_drift_agent_flags_only_what_changed_builds_the_reasons_and_writes_a_valid_file():
    from ai_agent import drift
    old, new = _version(DRIFT_OLD), _version(DRIFT_NEW, "1.1")
    reqs = [{"id": f"R-00{k}", "text": text.split(". ", 1)[1], "source": {"regulation": "UN R150", "page": page, "paragraph": lab}}
            for k, (lab, text, page) in enumerate(DRIFT_OLD, 1)]
    model = DriftModel()
    result = drift.run_drift(old, new, reqs, SETTINGS, "case-d", "UN R150", llm=model)
    flagged = {c["requirement_id"]: c for c in result.changes["changes"] if c["requirement_id"]}
    assert set(flagged) == {"R-002", "R-004"}, flagged  # SAME and RENUMBERED paragraphs are never flagged
    assert flagged["R-002"]["change"] == "modified" and flagged["R-002"]["source"] == {"page": 4, "paragraph": "5.2"}
    assert flagged["R-002"]["reason"] == "Paragraph 5.2 of UN R150 was amended in version 1.1: 'name.' became 'name and the approval mark.'."
    assert flagged["R-004"]["change"] == "removed" and "no longer appears" in flagged["R-004"]["reason"]
    added = [c for c in result.changes["changes"] if c["change"] == "added"]
    assert [(c["new_text"], c["source"]) for c in added] == [("The lamp shall bear a date code.", {"page": 4, "paragraph": "5.3"})]  # the invented quote is dropped
    assert [c[:2] for c in model.calls if c[0] == "drift_judge"] == [("drift_judge", "5.2"), ("drift_judge", "5.4")]  # only changed nodes reach the model
    assert result.changes["team_id"] == SETTINGS.team_id and result.trace["counts"] == {"modified": 1, "removed": 1, "added": 1}
    try:
        from validate import validate
    except ImportError:
        return
    assert validate(result.changes, "subgoal", requirements_old=reqs) == []


def test_drift_requirements_map_to_their_node_by_label_or_else_by_text():
    from ai_agent import drift
    old = _version(DRIFT_OLD)
    got = drift.map_requirements(old, [{"id": "a", "text": "The lamp shall emit red light.", "source": {"paragraph": "5.1."}},
                                       {"id": "b", "text": "The marking shall be indelible and legible for 1,500 hours.", "source": {"paragraph": "9.9"}},
                                       {"id": "c", "text": "Zzzz qqqq.", "source": {"paragraph": "9.9"}}])
    assert got["a"] == {"node": 0, "by": "label"} and got["b"]["node"] == 2 and got["b"]["by"] == "text" and got["c"]["node"] is None


def test_score_drift_counts_flags_false_flags_and_one_to_one_added_matches():
    import score_drift
    reqs = [{"id": f"R-00{k}", "text": "x", "source": {"paragraph": f"5.{k}"}} for k in range(1, 6)]
    gold = {"changes": [{"change": "modified", "requirement_id": "R-001", "new_text": "a", "reason": "r", "source": {"page": 1, "paragraph": "5.1"}},
                        {"change": "removed", "requirement_id": "R-002", "reason": "r"},
                        {"change": "added", "requirement_id": None, "new_text": "The lamp shall bear a date code.", "reason": "r", "source": {"page": 2, "paragraph": "5.6"}}]}
    mine = {"changes": [{"change": "modified", "requirement_id": "R-001", "new_text": "a", "reason": "r", "source": {"page": 1, "paragraph": "5.1"}},
                        {"change": "modified", "requirement_id": "R-003", "new_text": "b", "reason": "r", "source": {"page": 1, "paragraph": "5.3"}},
                        {"change": "added", "requirement_id": None, "new_text": "The lamp shall bear a date code.", "reason": "r", "source": {"page": 2, "paragraph": "5.6."}},
                        {"change": "added", "requirement_id": None, "new_text": "The lamp shall bear a date code.", "reason": "r", "source": {"page": 2, "paragraph": "5.6"}}]}
    s = score_drift.score(mine, gold, reqs)
    f = s["flagged"]
    assert (f["tp"], f["pred"], f["gold"], f["false_flags"], f["unchanged"], f["missed"]) == (1, 2, 2, 1, 3, ["R-002"])
    assert f["recall"] == 0.5 and f["precision"] == 0.5 and f["kind_accuracy"] == 1.0
    assert (s["added"]["tp"], s["added"]["pred"], s["added"]["gold"]) == (1, 2, 1)  # one gold item matches one agent item only
    assert s["overall"]["tp"] == 2 and s["overall"]["pred"] == 4 and s["overall"]["gold"] == 3


def main(argv: list[str] | None = None) -> int:
    return run_tests(globals(), sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
