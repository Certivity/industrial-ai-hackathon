# Team DeepFry: the AI side of our solution (agent and parser)

This document explains the AI half of our solution: the agent that finds requirements, and the parser that turns regulation PDFs into a graph the agent can read. It is written for judges and teammates who have not seen our code. Every number comes from our own findings files (`spec/finding/`); where a number comes from DeepSeek-written test cases rather than the expert answer, we say so.

**Short glossary.**
- **UN Regulation**: a technical rule for vehicles and vehicle parts (for example UN R148, signalling lamps). We have 56, each as a PDF.
- **Paragraph**: a numbered unit of a regulation, such as "5.2.1". A requirement cites its paragraph and its page.
- **Node, graph**: a node is one paragraph, annex, appendix or table. Nodes form a tree (a paragraph sits under its section). With the cross-references, that is a graph.
- **Precision / recall / F2**: precision is the share of our answers that are right. Recall is the share of the right answers we found. F2 combines them and counts recall twice as much as precision: F2 = 5PR / (4P + R). Missing a requirement is worse than listing an extra one.
- **Strict / lenient**: our local judge (a model) matches our requirements to the expert ones. Strict counts only the same obligation. Lenient also counts partial overlaps. The platform's own judge sits somewhere in between. Strict scores carry about +-0.05 of sampling noise.

## 1. The problem

**Main goal.** Input: a product specification (text) and, optionally, an exploded view (a drawing). Output: the engineering requirements the product must meet. Each requirement gives the regulation, version, page, paragraph and a text. Our file also keeps the verbatim quote in an audit trail.

**Sub-goal.** Input: the requirements derived from one version of a regulation, plus a later version. Output: which requirements are `modified`, `removed` or `added`, and what in the regulation caused it.

*Why it is hard.* The dev case has a rear lamp and 56 possible regulations. Four apply. The expert answer has 190 requirements. The agent must pick the right regulations, the right sections inside them, and then write one checkable obligation per requirement.

## 2. The end-to-end flow

```
spec.md ----------------------------------------+
exploded_view.png --(vision, 2 calls)--> facts -+--> PRODUCT PROFILE
                                                      (parts, functions, materials,
                                                       regulatory concepts, what is absent)
                                                            |
                      56 regulation cards --> REGULATION SELECTION (one call, strict)
                                                            |
                      for each chosen regulation:  SECTION WALK (tools over the outline)
                                                            |
                      CITATION HOP: other regulations cited by the chosen text
                                    are vetted, then walked too
                                                            |
                      OBLIGATION EXTRACTION (chunks of ~24K characters, one entry per node)
                                                            |
                      EMISSION POLICY (filters on labels) --> citation written by code
                                                            |
                      validate --> submission.json
```

Drift pipeline (sub-goal):

```
old PDF + new PDF --parse--> two graphs --align (hash, Hungarian)--> SAME / RENUMBERED /
                                          MODIFIED / REMOVED / ADDED
   model judges only MODIFIED/REMOVED paragraphs that carry requirements;
   ADDED paragraphs go to extraction; code writes the reasons --> changes.json
```

*Why this shape.* Each stage has a small, checkable output. Every stage writes its result to disk, so we can replay a run and find which stage failed.

**Worked example (dev rear lamp).** The spec lists a rear position lamp, stop lamp, reversing lamp, outer lens and retro-reflector. The profile turns these into regulatory concepts. The selection picks R148 (signalling lamps), R150 (retro-reflectors), R48 (installation of lighting) and R10 (electromagnetic compatibility). The walk of R148 selects sections 5.2, 5.5 and 5.8. Extraction then finds R148 paragraph 5.2.1 on page 17: "The light emitted by each of the two samples supplied shall meet the requirements in Table 4; however, a luminous intensity of 6.0*10^1 cd shall be permitted for rear position lamps reciprocally incorporated with stop lamps ..." The expert requirement for the same paragraph and page has the same content.

## 3. Which model, where, and why effort matters

One model does all the AI work in the submission path: **Claude Sonnet 5.5** (`claude-sonnet-5-5`, `config.DEFAULT_MODEL`). It cannot switch thinking off, so *effort* is the only dial. We set it per stage (`config.DEFAULT_EFFORT`):

| Stage | Effort | Why |
|---|---|---|
| vision (read the drawing) | high | small print |
| profile | medium | short answer |
| regulations (choose among 56) | high | one call reads all 56 cards (about 43K tokens) |
| sections (the walk) | medium | the walks reached every expected paragraph at medium |
| verify (opt-in, selection v3) | medium | short yes/no |
| obligations (extraction) | high | see below |
| component map, judge | medium | demo artifact, local scoring |

**Effort matters most in extraction.** On UN R175 (94 expert requirements, independent of the dev case) the same prompt gave 18 obligations at `medium` and 167 at `high`. At `medium`, a chunk of 110 nodes returned one obligation. Recall against the experts went from 1% to 71%. On the dev case, strict F2 went from 0.35 to 0.60 for the same reason, mostly.

**Replay cache.** `llm.py` stores every request and reply on disk (`runs/_llm_cache`). An identical request replays for free. We can change a late stage (the emission policy, for example) and re-run only that stage. This is why most of our tuning cost $0.

**Where DeepSeek appears.** We checked the code. Nothing in `src/ai_agent/` calls DeepSeek. It is used in three places only:
1. generating test cases (`eval/xprovider.py`, 50 cases);
2. the regulation audit (`eval/audit_regs.py`);
3. the parser's model fallback (`regcomp/marker_outline.py`), which runs only if the marker parser (the default) finds its confidence below 0.55 for a document. It has never triggered on the corpus (0 of 92 PDFs). The submission used the marker parser and the fallback did not trigger, so it made no DeepSeek call.

## 4. How the regulation graph is built

```
PDF --PyMuPDF--> text lines (text, font, size, bold, position, page)
    --drop footers/headers--> candidate markers ("5.1.4.", "Annex 4", "(a)")
    --stack parse--> tree of nodes --> text hash per node, cross-reference edges
```

1. **Lines.** Each line keeps its font, size, bold flag, position and page. A footer such as "UN R150, version 1.2.1 | page 7 of 54" gives the physical page number that experts cite.
2. **Markers.** A line start such as `5.1.4.`, `Annex 2A` or `(b)` is a candidate marker. A marker is accepted only if it follows the numbering: 5.1, then 5.1.1 or 5.2. Table cells and wrapped references that look like numbers are rejected. The marker parser searches for the best whole path with a beam of 12 states, not greedily. Greedy loses 11 points of recall.
3. **Nodes.** Each node has a label, kind (`para`, `table`, `annex`, `appendix`, `part`), scope, pages, text, a parent and a text hash. The hash ignores footnote numbers, line breaks and list layout.
4. **Edges.** Parent and child come from the tree. References come from the text: "paragraph 5.8.1", "Annex 4", "UN Regulation No. 7". They are found by patterns when the graph loads.

Small example (R148):

```
5 Specifications                      [section, pp. 15-31]
  5.2 Rear position lamps             [section]
    5.2.1 The light emitted ... Table 4 [para, p. 17]   --refers_to--> Table 4
    5.2.2 ...
  5.5 Stop lamps
Annex 4 Conformity of production      [annex]
  Annex 4 1.1 ...                     [para]  (paragraph numbering restarts inside an annex)
```

The graph lives in memory (`ai_agent/store.py: RegGraph`), built from the PDF when a run starts (median parse 0.44 s). The proposal mentions SQLite and NetworkX for storage. That is not implemented; the code has no such dependency.

## 5. What the agent can read from the graph

The section walker has five tools. Each is bound to one regulation:

| Tool | Returns |
|---|---|
| `get_toc(node, depth)` | the sub-sections of a node, 1-3 levels, with page range and size |
| `read_node(node, subtree)` | the node's text; with `subtree` the node and all below it, cut at 14,000 characters |
| `search(query, top_k, within)` | BM25 keyword hits (provision, title path, page, snippet), optionally inside one node |
| `follow_refs(node)` | what the node points to, what points to it, and other regulations it cites |
| `select_sections(selections)` | ends the walk: node, category, one-line reason, optional excludes |

The first message already holds the **outline**: every section with page range and size. The agent names nodes by label. A label that does not exist is answered with the closest real ones, and `select_sections` refuses it. Tables arrive as one grid row per line.

## 6. How the agent traverses

1. **Per regulation, one walk.** An agent reads the outline and the product profile, optionally looks inside, and selects sections (with category: function, general, marking, conformity, test). "Function" sections are named after a product part. "General" sections apply to every device of the class.
2. **Citation hop.** Code finds the regulations cited by the *selected* text. One call vets them against the profile. Approved ones are walked too.
3. **Chunked extraction.** The selected nodes are cut into chunks of about 24,000 characters. The model returns one entry per node, with obligations, a verbatim quote, a standalone rewrite and four labels (modality, addressee, kind, how well it applies). A node the model skipped is handed back once.

**Measured fact:** the walkers mostly choose straight from the outline. On the dev case, three of five submitted on turn one, and two read one node first. Outlines are small (median 2.2K tokens, largest R49 19.7K), so the choice is a single structured decision. Even so, the selected sections held all 190 expected requirements. The tools still matter when an outline is too long to show or a title says nothing; they were just not needed here.

## 7. Why a deterministic parser, not an LLM parser

| Reason | What it means for us |
|---|---|
| Length | A regulation runs to hundreds of pages. R49 alone has 2,361 nodes. One call cannot reliably hold and reproduce that much text. |
| Hallucination | A requirement's quote must exist verbatim at the cited page and paragraph. Our grounding checks rely on it. A model-written parse could invent text that is then "found". |
| Reproducibility | The same PDF gives the same nodes and hashes. Drift alignment compares hashes between versions. A sampled parse would differ per run. |
| Cost and speed | All 92 PDFs parse in about a minute, for free. |
| Auditability | Every node traces to lines and pages of the PDF. |

*Flip side, honestly.* The rule-crafted parser (`regcomp/parse.py`) needed someone to explore the PDFs first. Its rules (scope keywords, bold-and-size tests, footer pattern) came from that exploration. A regulation outside the corpus could break them. Section 8 is our answer.

## 8. How the parser scales

**Option A: per-document induction** (`marker_induce.py`, the default parser; `REGCOMP_PARSER=rules` selects the hand rules). The parser learns the numbering scheme, keywords and nesting from each document itself. No UNECE vocabulary is built in. It finds families of markers whose instances form sequences (1,2,3 / a,b,c / 5.1 then 5.1.1). It treats a word such as "Annex" as a scope keyword if the numbering restarts after it. It finds headers and footers as lines that repeat in the margins.

| Check (92 PDFs unless noted) | Hand rules | Induced marker |
|---|---|---|
| Expert anchors (label and page) | 254/259 | 258/259 |
| Fidelity checks | 382/401 | 393/401 |
| Label agreement with the hand rules (micro F1) | 1 | 0.905 |
| DeepSeek-grounded requirements whose quote is in one node on the right page (6,064) | 1.000 | 1.000 |
| Total parse time | 37 s | 61 s |
| Dev case: strict / lenient F2, hand vs induced | 0.63 / 0.72 | 0.630 / 0.717 |

**Option B: model fallback** (`marker_outline.py`). If the induced parse looks wrong (confidence under 0.55), a model (DeepSeek) reads the pages in windows and returns *only an outline*: label, page, first words, level. Code then checks each heading's first words at a line start on that page in the text layer, drops any it cannot find, and cuts the text itself. Nothing the model writes becomes regulation text. Replies are cached per PDF. Forced on three small PDFs, it matched the fixed marker parse with label precision 0.81-1.00 and recall 0.87-0.90, at a few cents per PDF.

**Trade-offs.** Induction loses scope naming where a heading names two scopes at once (label agreement 0.7-0.9 on R100, R92, R107; the paragraph numbers still agree). A scope keyword needs two instances. 0 of 92 PDFs needed Option B (lowest confidence 0.81).

**Not covered yet.** Scanned PDFs (we need a text layer). Inline markers inside a paragraph. Numbering that restarts or repeats a scope id (R13H Annex 4 Part B, R164, R3). A true out-of-corpus test was blocked: unece.org answered every request with a Cloudflare challenge. Our best substitute was 24 PDFs of 13 regulations nobody inspected. There both parsers got text coverage 0.99 and 40/40 spot-checked paragraphs. These 24 PDFs were still in the 92 that the weights were set on, so this is "never inspected", not "never seen".

## 9. If the parser is this good, why an agent?

The parser knows **where** text is and how it is structured. It does not know **what applies to this product**. Three decisions need language understanding:
- which of the 56 regulations apply (on the dev case, R10 (electromagnetic compatibility) is needed, while R128 was a wrong extra in some runs);
- which sections concern this product's parts and functions;
- turning legal prose into atomic, checkable requirements at the experts' granularity (about 1.6 per paragraph).

Deterministic code still does everything it can do reliably:

| Done by code | Where |
|---|---|
| Quote must be in its node (else rejected) | `obligations.py`, `store.RegGraph.locate` |
| Page, paragraph, regulation, version written from the node | `emit.py` |
| Labels the model names must exist | `tools.py` |
| Emission filters (listed below) | `emit.py` |
| Scope-text quote check for the optional verifier | `verify.py` |
| Drift alignment and the written reasons | `drift.py` |
| Superseded regulation redirected to its successor | `catalog.py` |

The split is deliberate: **models decide, code verifies.** The model never writes a location.

## 10. The drift agent (sub-goal)

1. Parse both versions. Align nodes: same label and same text hash means SAME; a one-to-one Hungarian assignment on token similarity pairs the rest into MODIFIED or RENUMBERED. What is left is REMOVED or ADDED.
2. Map each old requirement to an old node (by its paragraph label, then by BM25 search).
3. Only a changed node that carries requirements reaches the model (one call, medium effort). Renumbering and page shifts never reach it. Wording-only differences (case, punctuation) are gated out in code.
4. Added paragraphs go to one extraction call per 20K characters, with the old requirements as examples.
5. Reasons are written by code from the word diff, in the experts' format.

**Appended-sentence convention.** When a sentence is appended to an existing paragraph, we report one `added` item for the new sentence, not a `modified` requirement. The user confirmed this convention. Alternatives (`modified`, `both`) exist but are not used.

**Why it is cheap.** Alignment is free and only changed requirement-bearing paragraphs reach the model. A single run of one case costs $0.00 to $0.08. The held-out R171 case cost $0.42 and 77 s.

## 11. Image input (the exploded view)

Two passes (`vision.py`), then a map (`components.py`):
- **Read:** the whole drawing is sent at the size the API accepts, plus overlapping tiles cut from the original pixels (small print survives). The model only transcribes text blocks.
- **Map:** a second call decides what each text points at (leader line, balloon plus legend, or proximity) and with what confidence.
- The facts join the profile as "callouts" and are printed verbatim by code. Afterwards a **component map** links each requirement to the part it concerns, for example "Reflector: rear position lamp 4 to 17 cd on axis" maps to R148 5.2.1 Table 4.

On the dev drawing, 14 of 14 text blocks were read exactly and 7 of 7 callouts tied to the right part. It cost $0.07. The image barely moves the score here (strict F2 0.60 text, 0.62 text and image; inside the noise), because the spec already names the lamp functions. Its value is the component map and image-only input. One real risk showed up: the first profile built with the image lost "electromagnetic compatibility", so R10 was not chosen. A prompt rule fixed it. Only one image has been tested.

## 12. Results, honestly

**Expert case (dev rear lamp, 190 expert requirements).** Our submitted file (marker parser, text and image, precision-v2) has 334 requirements. The requirement-level rows are from the earlier hand-rule-parser file (317 requirements); the judge was not rerun on the final file:

| Level | P / R | F2 | Source |
|---|---|---|---|
| Regulation | 0.80 / 1.00 | 0.95 | `tools/score_local.py` |
| Page | 0.758 / 0.925 | 0.89 | `tools/score_local.py` |
| Requirement, strict | 0.429 / 0.716 | 0.63 | local model judge |
| Requirement, lenient | | 0.72 | local model judge |

The judge is ours (same model family), so treat strict and lenient as a range. On the first run, every one of the 190 expected requirements was inside the selected sections; the loss is in wording and in extra applicable paragraphs the experts did not cite.

**DeepSeek test cases (noisy gold).** 26 cases in `testing/ts-*`, plus 24 older ones. The gold is one model's opinion. Two examples:
- It put R10 in all 20 new golds, including a windscreen and a spare wheel.
- It used superseded R23 and R38.

So we built an **audited reference**: three DeepSeek votes per candidate regulation, reading the verbatim scope text, with majority rule. It rejects 27 of 89 gold pairs (30%). It accepts 4 of 52 distractors, so it also has errors. Regulation selection, default settings (macro mean over cases, P / R / F1 / F2):

| Split | vs the DeepSeek gold | vs the audited reference |
|---|---|---|
| tune (10 cases) | 0.80 / 0.71 / 0.73 / 0.71 | 0.98 / 0.93 / 0.95 / 0.94 |
| held-out (16 cases) | 0.86 / 0.63 / 0.66 / 0.63 | 0.93 / 0.86 / 0.86 / 0.86 |

On the six older synthetic cases the full pipeline's requirement-level strict F2 was 0.34 and 0.51 on the two judged ones; the other four were not judged. Most of the error there is regulation choice, not extraction.

**Drift.**
- Dev (UN R175, expert gold): 7 of 7 modified or removed requirements flagged, 5 false flags among 87 unchanged ones, 15 of 17 added items matched (overall F2 0.85).
- Ten DeepSeek cases (noisy gold): flagged recall 0.80, precision 0.88, 5 false flags in 556 unchanged requirements, overall F2 0.82.
- All drift work cost $1.08 in total.

**Held-out cases (released Sunday).** Front bumper: 206 requirements across R148 (75), R48 (47), R10 (37), R26 (23), R42 (14) and R127 (10), valid under `validate --strict`, $2.01 spent and $1.45 replayed. Drift R171 (1.1.0 to 2.0.0): 115 changes (17 modified, 5 removed, 93 added), valid. **We cannot score either locally**: there is no expected file.

**Cost.** A full main-goal run is about $3.5 to $4 and 7 minutes; about 90% of it is extraction. The cheap stages (profile, regulations, sections, citation vetting) cost about $0.2 to $0.4.

## 13. Precision and recall controls

The emission policy (`emit.py`, `precision-v2`, the default) is a set of filters on the model's labels. Every dropped candidate keeps the rule that dropped it (`candidates.json`).

| Rule | Drops |
|---|---|
| modality | anything but an obligation (permissions, exemptions, definitions, scope) |
| addressee | test set-up, paperwork, authority actions |
| applies | candidates graded `unlikely` |
| kind | conformity-of-production |
| sparse `possible` pages | a page whose emitted candidates are all `possible` and at most three |

Measured on the dev case: page precision rose from 0.59 to 0.73 for a recall cost of 0.96 to 0.91, and strict F2 from 0.60 to 0.62.

**What we tried and rejected:**
- *precision-v1's regulation check* ("drop a regulation with no `certain` candidate"). It lifted dev regulation precision to 1.00 by removing R128. But it rested on one fact of one case. On the text-and-image run it dropped the correct R10 and cost strict F2 0.62 to 0.53. We call it a fitted trick and turned it off.
- *Selection v2 and v3* (a recall-oriented shortlist, then verification against the scope text). Neither beat the default out of sample. v3 gained 0.04 recall but lost 0.08 precision on held-out. Seven extra regulations were never audited, so the table is not conclusive either way.
- *A cap of three per node.* It lowered F2 on held-out cases and on dev.

**Discipline.** Tune on a split (10 cases), report held-out (16 cases) once, and use the expert dev case as a separate check. No rule was fitted to the eval data after seeing it. Differences under about 0.1 macro are noise (std 0.25-0.33 over cases).

## 14. Limits and next steps

- Regulation choice is the weakest stage (held-out regulation recall 0.63 against the DeepSeek gold). A bad profile costs a whole regulation.
- One expert case; strict scores move +-0.05 between samples.
- The platform's judge is unknown; one upload calibrates it.
- The submission (2026-10-25) used the marker parser with per-document induction, now the default (`REGCOMP_PARSER=rules` keeps the hand rules). On dev it gave regulation P 0.80 / R 1.00 and page P 0.758 / R 0.925 against 1.00 / 1.00 and 0.731 / 0.906 with the hand rules; the extra regulation is UN R128.
- Drawings: one image tested; balloon-and-legend sheets are untested.
- Next: sample twice and vote on drift flags; a third parser relation for restarting numbering; test on real out-of-corpus PDFs.

## 15. How to run

```
python src/ai_agent/run.py cases/dev-rear-lamp                 # about 7 min, $4; needs AI_AGENT_KEY in .env
python tools/validate.py runs/dev-rear-lamp/<run id>/submission.json --strict
python src/ai_agent/run_drift.py subgoal/dev --out runs/drift/subgoal-dev --case-id subgoal-dev
REGCOMP_PARSER=rules python src/ai_agent/run.py cases/dev-rear-lamp    # hand-rule parser (default is the induced marker parser)
python eval/test_ai_agent.py                                   # offline tests, no API calls
```
