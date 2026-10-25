# ai_agent: from a product spec to requirements with grounded citations

`ai_agent` is Part A of `spec/proposal.md` as running code: it reads `spec.md` (or `technical_spec.md`) and/or an exploded-view image, chooses the UN Regulations that apply, walks their parsed structure
(`regcomp.parse`) to the parts the product has to meet, and writes the atomic requirements in the format of `cases/dev-rear-lamp/expected.json`.
Text, image, or both: `inputs.py` finds them in the case folder; a drawing is read by `vision.py` (see `spec/finding/image-input.md`).

```
python src/ai_agent/run.py cases/dev-rear-lamp                 # about 7.5 minutes and $4 at the default settings; reads spec.md and exploded_view.png
python src/ai_agent/run.py cases/dev-rear-lamp --no-image      # text only (--image PATH picks the drawing)
python src/ai_agent/run.py cases/dev-rear-lamp --no-text       # image only
python tools/validate.py runs/dev-rear-lamp/<run id>/submission.json
python eval/bench_agent.py runs/dev-rear-lamp/<run id>         # the platform's own checks, the funnel, a local judge (cents)
```

Needs `AI_AGENT_KEY` (an Anthropic key) and optionally `AI_AGENT_MODEL` (default `claude-sonnet-5-5`), from the environment or the git-ignored
`.env`; `pip install anthropic jsonschema scipy` and PyMuPDF as in `src/README.md`. The key is never printed or logged. `AI_AGENT_FALLBACKS=off` (or `--no-fallbacks`)
turns off the server-side fallback on a policy decline; `--max-cost` stops the run before a call that would start above that many dollars.

## The chain

| Stage | Module | What the model does | What code does |
|---|---|---|---|
| 0 vision (image only) | `vision.py` | reads every text of the drawing (whole picture + tiles at native resolution), then maps each callout to the component it points at | resizes, cuts tiles |
| 1 profile | `profile.py` | spec.md to parts, functions, materials, attributes, the regulatory concepts they fall under, and what is *not* present | nothing |
| 2 regulations | `regulations.py`, `catalog.py` | reads the 56 cards at once (title, categories, scope, contents, supersession), picks strictly | builds the cards from the PDFs, redirects a superseded regulation to its successor |
| 3 sections | `sections.py`, `tools.py` | one agent per regulation: reads the outline, looks inside with `get_toc` / `read_node` / `search` / `follow_refs`, submits `select_sections` | answers the tools, refuses labels that do not exist, expands a selection into nodes |
| 3b citation hop | `pipeline.py`, `regulations.py` | decides which regulations cited by the selected text also apply | finds the citations in the selected nodes |
| 4 obligations | `obligations.py` | one entry per node: atomic obligations with a verbatim quote, a standalone rewrite and four labels | chunks the nodes, checks every quote in its node, hands skipped nodes back once |
| 5 emit | `emit.py` | nothing | policy on the labels, citation from the node, ids, validation with `tools/validate.py` |

Three rules hold the design together:

- **The model never writes a location.** It names nodes by label; `store.RegGraph` resolves them, and the regulation, base version, page and
  paragraph of a requirement are filled in from the node. A quote that is not in the node (or in another node of the chunk) rejects the obligation.
- **Nothing is dropped silently.** `candidates.json` keeps every obligation with its status (`emitted`, `dropped:<rule>=<value>`, `rejected:<why>`);
  the policy in `emit.py` is three filters on the labels, and `unlikely` is the threshold to tune.
- **The expected answer is never read.** The pipeline opens `spec.md` of the case and nothing else; `eval/test_ai_agent.py` fails if a string of
  `src/ai_agent` names it.

## Files of a run (`runs/<case>/<run id>/`, git-ignored)

`profile.json` `regulations.json` (selected, close calls, redirects) `sections.json` and `walk-<reg>.json` (selections and the walk's transcript)
`vision.json` and `component_map.json` (with an image) `citation_hop.json` `chunks.json` (plan and per-chunk coverage) `candidates.json` `submission.json` `trace.json` (quote, breadcrumb-level facts per
requirement) `usage.json` `calls.jsonl` `run.json`. `runs/_llm_cache` replays an identical request for free, so a change to a late stage re-runs only
that stage; `runs/_cards` holds the regulation cards for one version of the parser.

## What the model settings are, and why

- Sonnet 5.5 cannot switch thinking off and rejects forced `tool_choice` and sampling parameters; the code sends none of them. Tools run with `auto`;
  a model that stops without submitting is nudged twice.
- Effort is set per stage (`config.DEFAULT_EFFORT`). Extraction needs `high`: on UN R175 the same prompt gave 18 obligations at `medium` (a chunk of
  110 nodes returned one) and 167 at `high`.
- The tool loop keeps `messages` append-only, as the model's preserved thinking requires, and caches the history (`cache_control`); prompts that are sent
  once are not cached, because the write costs 25% more.

## Tests

`python eval/test_ai_agent.py` (offline: a fake SDK client, a scripted model over a real regulation; `--unit` needs no PDFs).
`python eval/bench_extract.py` measures the extraction alone on UN R175 against the 94 experts' requirements of `subgoal/dev/requirements_old.json`, which
is independent of the dev case.

## Not done

Drawings that are photos or numbered-balloon sheets are untested; the obligation layer as a per-regulation batch (extraction runs per case); the sub-goal (`diff.py`); the staleness and
propagation triggers of Part B; a UI. See `spec/finding/ai-agent-baseline.md` for what the first measurements say to do next.
