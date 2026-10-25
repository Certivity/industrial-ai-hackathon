#!/usr/bin/env python3
"""Offline tests of `--stop-after` (src/ai_agent/run.py, pipeline.py) and of upper_bound.json, the pseudo-submission of the cheap benchmark.

    python eval/test_stop_after.py

No model call: a scripted model stands in for the API. The corpus test needs regulations/data and PyMuPDF.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(Path(__file__).resolve().parent)]

from test_ai_agent import SETTINGS, Scripted, synthetic, text_reply, tool_use  # noqa: E402
from test_parse import Skip, run_tests  # noqa: E402

from ai_agent import pipeline  # noqa: E402
from score_local import score  # noqa: E402


def test_upper_bound_cites_every_selected_content_node_once_as_the_emitter_would():
    graph = synthetic()
    labels = {n.label: i for i, n in enumerate(graph.nodes)}
    chosen = [labels["5.2"], labels["5.2.1"], labels["Annex 1"], labels["Annex 1 1"]]  # a section heading, a paragraph, an annex heading, an annex paragraph
    walks = {"UN R150": SimpleNamespace(nodes=chosen)}
    sub = pipeline.upper_bound_submission({"UN R150": graph}, walks, ["UN R150"], "case-x", "team")
    cited = [(r["source"]["paragraph"], r["source"]["page"], r["source"]["version"]) for r in sub["requirements"]]
    content = [i for i in chosen if graph.is_content(i) and graph.nodes[i].label]
    assert cited == [(graph.nodes[i].label, graph.nodes[i].page_start, graph.version) for i in sorted(content)], cited
    assert len(set(cited)) == len(cited) and cited, cited  # once each
    assert sub["case_id"] == "case-x" and sub["team_id"] == "team" and all(r["source"]["regulation"] == "UN R150" for r in sub["requirements"])
    assert [r["id"] for r in sub["requirements"]] == [f"R-{k:05d}" for k in range(1, len(cited) + 1)]


def test_upper_bound_is_scored_by_score_local_with_exact_regulation_level_and_page_recall_ceiling():
    graph = synthetic()
    labels = {n.label: i for i, n in enumerate(graph.nodes)}
    walks = {"UN R150": SimpleNamespace(nodes=[labels["5.1.1"], labels["5.2.1"]])}
    ub = pipeline.upper_bound_submission({"UN R150": graph}, walks, ["UN R150"], "c", "t")
    gold = {"requirements": [{"id": "R-1", "text": "x", "source": {"regulation": "UN R150", "version": graph.version, "page": 3, "paragraph": "5.1.1"}},
                             {"id": "R-2", "text": "x", "source": {"regulation": "UN R10", "version": "06", "page": 1, "paragraph": "5.1"}}]}
    s = score(ub, gold)
    assert s["regulation_level"]["precision"] == 1.0 and s["regulation_level"]["recall"] == 0.5  # exact: one of two gold regulations selected
    assert s["page_level"]["precision"] == 0.5 and s["page_level"]["recall"] == 0.5  # page 3 hit, page 4 an extra; R10 not reachable


def test_stop_after_must_name_a_stage_and_the_cli_offers_only_the_three():
    for bad in ("obligations", "emit", ""):
        try:
            pipeline.run_case("nowhere", SETTINGS, stop_after=bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert pipeline.STOP_STAGES == ("profile", "regulations", "sections")
    from ai_agent import run as run_module
    try:
        run_module.main(["some-case", "--stop-after", "obligations"])
    except SystemExit as exit_:
        assert exit_.code == 2
    else:
        raise AssertionError("argparse accepted a stage after the extraction")


def test_corpus_stop_after_writes_what_exists_and_never_extracts_or_emits():
    from ai_agent import catalog as catalog_module
    from regcomp import corpus
    from ai_agent import store
    if corpus.pdf_path(corpus.entry_for("UN R150"), "base") is None:
        raise Skip("regulations/data has no PDFs")
    real = store.RegGraph("UN R150", grids=False)
    section = max(((n.label, real.sub_content[i]) for i, n in enumerate(real.nodes) if n.kind == "para" and not n.scope and len(n.num) == 2
                   and n.num[0] >= 3), key=lambda item: item[1])[0]
    profile = {"product": "test lamp", "summary": "s", "vehicle_categories": ["M1"], "functions": [{"key": "F1", "name": "f", "detail": ""}],
               "parts": [{"key": "P1", "name": "p", "role": "r", "materials": ["PMMA"]}], "technologies": [{"key": "T1", "name": "t", "regulatory_concepts": ["c"]}],
               "attributes": [{"name": "colour", "value": "red", "source": "inferred"}], "regulatory_concepts": ["rc"], "not_present": ["np"]}

    def script(stage, label, system, messages, tools_, schema):
        if stage == "profile":
            return text_reply(profile), "end_turn"
        if stage == "regulations" and label == "select":
            return text_reply({"selected": [{"regulation": "UN R150", "level": "device", "confidence": "high", "covers": ["P1"], "reason": "r"}],
                               "close_calls": []}), "end_turn"
        if stage == "regulations":
            return text_reply({"add": [], "skip": []}), "end_turn"
        if stage == "sections":
            if len(messages) == 1:
                return [tool_use("t1", "get_toc", {"node": section, "depth": 1})], "tool_use"
            return [tool_use("t2", "select_sections", {"selections": [{"node": section, "category": "function", "reason": "r"}]})], "tool_use"
        raise AssertionError(f"stage {stage} must not run")  # obligations, vision-after-stop ...

    cat = catalog_module.Catalog(cache_dir=None)
    cat.names = ["UN R150"]
    cat.cards = {r: catalog_module.build_card(r) for r in cat.names}
    expected_files = {"profile": {"profile.json"}, "regulations": {"profile.json", "regulations.json"},
                      "sections": {"profile.json", "regulations.json", "sections.json", "citation_hop.json", "upper_bound.json"}}
    never = {"candidates.json", "submission.json", "trace.json", "chunks.json"}
    for stop, files in expected_files.items():
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "case-x"
            case.mkdir()
            (case / "spec.md").write_text("# spec\n", encoding="utf-8")
            model = Scripted(script)
            result = pipeline.run_case(case, SETTINGS, Path(tmp) / "run", log=lambda m: None, llm=model, catalog=cat, stop_after=stop)
            made = {p.name for p in (Path(tmp) / "run").iterdir()}
            assert files <= made, (stop, files - made)
            assert not (never & made), (stop, never & made)
            assert {"usage.json", "run.json"} <= made, made  # the ledger is written however the run ends
            assert result.submission == {} and result.candidates == []
            assert {r["stage"] for r in model.requests}.isdisjoint({"obligations"}), stop
            if stop == "profile":
                assert not (Path(tmp) / "run" / "regulations.json").exists()
            if stop == "sections":
                ub = json.loads((Path(tmp) / "run" / "upper_bound.json").read_text(encoding="utf-8"))
                assert result.regulations == ["UN R150"] and ub["requirements"], ub
                sections = json.loads((Path(tmp) / "run" / "sections.json").read_text(encoding="utf-8"))
                n_provisions = sections["UN R150"]["provisions"]
                assert 0 < len(ub["requirements"]) <= n_provisions, (len(ub["requirements"]), n_provisions)
                by_label = {n.label: n for n in real.nodes}
                for r in ub["requirements"]:
                    n = by_label[r["source"]["paragraph"]]
                    assert r["source"]["regulation"] == "UN R150" and r["source"]["page"] == n.page_start
    from ai_agent.emit import validate_submission
    assert validate_submission(ub) == [], validate_submission(ub)[:3]


def main(argv: list[str] | None = None) -> int:
    return run_tests(globals(), sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
