# Proposal: grounded regulation index and versioned requirement mapping

Status: proposal, 2026-10-24. Updated with `spec/finding/mapping-simulation.md` (regulation and section choice, supersession, cost of errors) and `spec/finding/parser-weak-points.md` (A1, the build order, verification and risks now carry the parser rules of `spec/finding/finding.md` section 3 and the weak points of the parser). Those weak points were fixed the same day, and A1, the code layout, the build order, verification and risks say what is built now (`spec/finding/parser-weak-points.md` section 6, `spec/testing/report.md` section 11). The rest of `finding.md` section 3 (REFERS_TO grammar, B1 matching order, sub-goal) and `spec/testing/report.md` section 6 are not merged here yet.

## Context

The brief (`artifact/certivity-challenge-brief.pdf`) asks for an agent that takes a product spec and/or exploded view and returns atomic engineering requirements. Each requirement must cite a UN Regulation from `regulations/index.json`, with its **base** version label and the page. The paragraph is optional, and a citation counts if either the page or the paragraph is right. Scoring uses F2, which weights recall above precision. The optional sub-goal: given requirements derived from an old version of a regulation and a newer version, flag which requirements are modified, removed or added, and say why.

This design addresses two problems:

1. **Indexing the regulations** so the agent finds the right paragraph and where it sits in the document. Citations must be correct, and when nothing applies the system must say so instead of inventing a citation.
2. **Handling change.** When a regulation gets a new version, a spec is re-parsed, or a new regulation is added, the requirement↔spec mappings must be updated, marked stale or removed, and new material must be mapped.

## What the data tells us

- **The gold set is tree-shaped.** The rear-lamp gold has 190 requirements from only 4 regulations: R148 (63), R48 (56), R150 (39) and R10 (32). They sit in contiguous sections: R48 §5.x general, §6.4 reversing, §6.7 stop, §6.10 rear position, §6.14 retro-reflector; R150 §3.3 markings, §4–5, Annexes 2/4/5/6. The right approach is to pick the relevant subtree and extract every obligation in it, not to retrieve top-k chunks. But only 26% of the requirements (50 of 190) sit in sections named after a part or function of the product (R48 §6.4/6.7/6.10/6.14, R148 §5.2/5.5/5.8, R150 §5.1). The rest are in markings (17%), general and EMC specifications (44%) and annex test methods (12%), which no function name points to (`spec/finding/mapping-simulation.md` §4.1).
- **Picking regulations by title gives false positives.** The spec mentions a reversing lamp, position/stop lamps and a retro-reflector, but the gold does **not** cite R23, R7 or R3. It cites the newer consolidated **R148/R150** instead. R48 itself says "type-approved to R7 *or* R148" (G-0087), so cross-regulation references help find candidates, but the final choice needs a supersession rule. R10 (electromagnetic compatibility) is in the gold because "LED modules on PCB" makes the lamp an electronic sub-assembly (ESA). Materials and electronics can pull in whole regulations. Measured on the 56 regulation cards: a lexical ranking puts the older R7, R3 and R23 in the top 10 and R53 (installation for L3 vehicles) second; R10 is not cited by R48, R148 or R150, and ranks 2-3 of 56 when the profile says "electrical/electronic sub-assembly, electromagnetic compatibility" but 12-21 when it says "LED module, printed circuit board" (`spec/finding/mapping-simulation.md` §3).
- **One obligation per requirement.** A single paragraph can yield up to 10 requirements: R10 §6.9.1 is split into one per table row (pulse 1/2a/2b/3a/3b). The text is rewritten as a standalone "X shall Y [while/when/where Z]". The gold IDs have 44 gaps, which suggests rows that don't apply were dropped. For example, only the **red** row of R150 Table 3 appears, because the lens is red. So applicability is decided down to the table row.
- **Paragraph labels have a fixed format.** Examples: `5.1.4.4.1. Table 3`, `Annex 4 Part 1 1.2`, `Annex 6 Part 6 3. Table A6-1`. `tools/score_local.py::_paragraph_key` normalizes them. The platform scores pages against each gold paragraph's **full page range**.
- **The main goal leaves out admin obligations.** In the dev gold, R150 requirements start at §3.3 (markings). Approval-application paperwork is left out; test-procedure parameters (saline mist, ISO 4892 exposure) are kept.
- **The sub-goal is a paragraph diff.** `subgoal/dev` is UN R175: `old.pdf` and `new.pdf` have the same sha256 as R175 base and latest. Of 94 old requirements, 6 are modified, 1 is removed, and 17 requirements are added. The reasons read like a word diff ("'standstill.' became '…while creeping.'; 'both' was added"). Paragraphs get renumbered ("6.5.2 (formerly 6.5)"). Added items are counted per obligation: §6.6.2.2 alone gives 5 added requirements. The main risk is wrongly flagging the 87 unchanged requirements.

## Core idea

- **A structural graph, not an LLM-extracted knowledge graph.** Build a deterministic, versioned graph for each regulation version from the document's own structure.
  - Nodes are sections, paragraphs and table rows. Each has an exact page range, a breadcrumb path and a content hash.
  - Edges are parent/child, cross-references, citations of other regulations, definitions and supersession.
  - An LLM-extracted knowledge graph would be harder to keep exact, harder to update, and adds nothing here.
- **The LLM never writes a location.** It selects and rewrites, but never produces a page or paragraph number. Every output requirement points to an `obligation_id` that exists in the store, and the citation is filled in from there.
- **Updates work like a build system.** Every derived row (obligation, mapping) records a hash of its inputs. When an input hash changes, the output is marked stale and only that output is recomputed.

---

## Part A: index and grounded retrieval

### A1. Parse each PDF into a node tree

Built in `src/regcomp/parse.py` with PyMuPDF (text plus font and position). The rules and their reasons are in `spec/finding/finding.md` sections 2-4; the weak points of the current parser are in `spec/finding/parser-weak-points.md`.

- **Detect structure.**
  - **Footer:** one regex, `UN R.., version .. | page N of M`. N is the physical page, which is the page the gold cites. There are no running headers to strip.
  - **Scope headings** (`Annex 4`, `Annex 2A`, `Annex 4 - Appendix 1`, `Appendix 1`, `Part 1 - …`, `Part A:`; a top-level `Part I` or a GTR's roman part): bold and at least 1.15 times the document's dominant font size, case-insensitive. The renderer scales pages, so never hard-code a size. Numbering restarts inside every scope. **Built:** the size test was a single point of failure (R101 Annex 7 Appendix 3 is bold at body size and was labelled `Annex 7 Appendix 2`), so a bold, short, titled, regex-matching line at body size or above that fails it also opens a scope when the numbering restarts after it or its id follows the scope it sits in, never when it repeats that id (R49's `Appendix 3 - Item N` labels). A top-level `Part I` whose numbers carry on from the paragraphs before it (R67, R89, R163) is a divider and opens no scope: its paragraphs are cited as printed (`21.1.2.1`, not `Part III 21.1.2.1`); one that starts the numbering over is a scope.
  - **Paragraph starts:** dotted `^\d+(\.\d+)*\.\s` (the space may be missing: `5.1.2.An immobilizer`, R162 and R48), and dotless headings (`5.7 Title`, `1 Scope`) when nested or styled. Per scope, keep the **longest strictly increasing chain** of numbers, not a successor check, which cascades on a gap (R148 4 of 40, R48 23 of 35). A numbered line after "…paragraph" is a wrapped reference. Left-out lines are logged.
  - **Keep list items** such as (a) and (i) inside their paragraph. **Built:** `Node.structured` keeps their line breaks, and those of footnotes, for the extractor.
- **What each node stores.**
  - *Built:* `label` in the gold format (`<scope> <number>`, `<owner>. Table N`), `kind`, `scope`, `num`, `page_start..page_end`, the node's own lines with the page of each (`page_of(quote)` resolves a quoted span to its page), `grid`, `figure_refs`.
  - *Built since (moved in from the eval scripts, which now read them):* `parent` and `children` (indexes; the store's `parent_id` is made from them), `heading`, a `path` breadcrumb such as `6 Specifications › 6.10 Rear position lamps › 6.10.4.2` (inside an annex the scope's heading comes first; the regulation id is the caller's to put in front), `structured` (line breaks before list items and footnotes), `model_text` (the lines outside the ruled tables, then each table once as its grid), `note` (which lines are footnote text) and `text_hash`. The hash is of the body without its number, footnote text included because it is binding; the footnote's number and the raised mark that cites it are ignored because they renumber between versions, an exponent is kept (`10²` stays); line breaks and whether a list is set inline or one item to a line do not count (a layout change must not become a "modified" flag).
- **Tables** are not one node per row. A table node (caption `Table N`, label `<owner>. Table N`, the caption page) carries a markdown grid built from the cell rectangles of `find_tables()` and the spans inside them (`Table.extract()` loses spaces, exponents and signs; `use_layout=False` keeps the result machine-independent). The grid goes to the node whose text lies inside the table, so an uncaptioned table (R10 6.9.1) is found too. Splitting a table into requirements is the extractor's job. Only ruled tables are found; `eval/health.py` counts captioned tables against gridded ones per PDF and flags a PDF only when fewer than half have a grid. A fallback for the 2% without one was tried and dropped: `find_tables(strategy="text")` on R171 Table 1 returns a grid of the whole page (83 rows by 12 columns), and the other five captioned tables of the base versions without a grid are a caption with nothing under it (drawn as images, or text the parser keeps in another node). `Node.model_text` shows a gridded table once instead of twice.
- **Parser health.** `eval/health.py` reports, per PDF: nodes per page, left-out lines that carry a sentence, orphan paragraphs, footer mismatches, captioned tables against gridded ones, and two signals for what the style gate cannot see: `scope-rej` (a bold line that reads as an Annex or Appendix heading, is short, titled and at body size or above, and shows neither a restart nor a successor id) and `restart` (a left-out `1.` with a sentence after it, once the chain had passed 1: numbering started over under a heading the parser does not know, as in R13H Annex 4's plain `A.` and `B.`).
- **Test against ground truth.**
  - *Labels and pages:* `eval/anchors.py`, 193 distinct anchors (121 gold paragraphs of the dev case, 57 paragraphs behind the 94 R175 `requirements_old` entries, 15 new-version `source` (page, paragraph) pairs of `subgoal/dev/expected.json`, checked against R175's latest version), found when a node has the same label under `_paragraph_key` and the gold page lies inside its range. Required: 193 of 193 after every parser change.
  - *Text:* `eval/fidelity.py` (the numbers of the expert requirements are in their node's text, its family or its grids).
  - *Beyond the five regulations with anchors:* the gate says nothing about the other 51. `eval/health.py` and the model-authored cases are the checks there: `eval/xprovider.py author` writes a case, `ground` triages it, `regrade` grounds the saved cases again with the current parser and shows which verdicts moved. 24 DeepSeek cases cover 32 regulations, 28 of them without anchors; they found one real defect that passed every other gate (R101 Annex 7 Appendix 3, which the probes of `parser-weak-points.md` had also found), one source quirk (R162 and R48 print `5.1.2.An` with no space after the number, so the paragraph was inside its neighbour) and one label convention that no gold settles (the `Part` prefix of R67, R89 and R163, dropped because their numbering carries on and the model and the printed number both cite without it). What they still list is the triage list for the next parse of an unanchored regulation. Treat the first parse of any regulation without anchors as unverified.

### A2. Edges

- `REFERS_TO`: regex on "paragraph 5.8.1", "Annex 4, Part 1, paragraph 1.1".
- `CITES_REG`: "UN Regulation No. 48", and lists such as "Nos. 13 and 13-H". A number with a leading zero is a series ("00 series"), not a regulation. Follow it from the chosen sections only: the whole of R48 cites 17 regulations of the index; its four lamp sections cite R148, R150, the older R23, R7 and R3, and R13H (a false positive: the braking signal of the stop lamp).
- `DEFINES`: from the §2 definitions to the term.
- `SUPERSEDES`: read from the "Introduction (for information)" of each regulation ("combines the provisions of individual UN Regulations Nos. …"), not typed in. For the regulations in the index it gives:
  - R148 replaces R6, R7, R23, R38 (and Nos. 4, 50, 77, 87, 91, which are not in the index);
  - R149 replaces R19, R123;
  - R150 replaces R3, R104;
  - it is a redirect, not a relevance signal: R19 and R123 redirect to R149, which does not apply to a rear lamp either.
- Each section node also gets a one-line LLM summary, used when walking the table of contents.

### A3. Obligation layer

Obligations don't depend on the product, so they are computed once per regulation version.

- **Extraction.** For each paragraph or table row, the LLM splits the text into atomic obligations in the gold style.
- **Fields:** `text`, `quote` (the verbatim source span), `condition`, `subject`, and `kind`, one of {design, performance, marking, installation, test-procedure, conformity-of-production, admin}. Also `addressee` (product, manufacturer, test-lab, authority; set by what is constrained, not who is named), `modality` (obligation, permission, exemption, scope) and `applies_if` facets for matching against the profile (`spec/precision.md` 4.3-4.4).
- **Check in code.** `quote` must be a fuzzy (≥0.95) substring of the node text, otherwise the obligation is rejected and retried. `page` comes from the quote's character offset.
- **When to run it.** Run it over all base versions on Saturday with the Batch API, so on Sunday the held-out case only needs selection, not extraction.

### A4. Pipeline for one spec

This is a workflow with fixed steps. The LLM makes the decisions inside each step.

1. **Profile.** spec.md plus a vision pass over the exploded view → parts, functions, vehicle category, colours, materials and electronics (LED/PCB → ESA). Each item gets a stable key.
2. **Pick regulations.** The LLM reads a card per regulation (title, §1 scope, depth-2 table of contents) against the profile. A card is 0.7K-4.9K tokens (median 1.6K) and all 56 together are about 106K, so one prompt can hold every card.
   - A deterministic pre-filter orders the cards and drops what cannot apply: a vehicle-category facet read from §1 (an M1 spec drops R53, R62, R40, R102 and R92) and `SUPERSEDES`.
   - It follows `CITES_REG` from the chosen sections of an installation regulation to device regulations (R48 → R148, R150).
   - The profile has to carry the regulatory concept, not only the spec's words: "LED modules on PCB" must become "electrical/electronic sub-assembly (ESA), electromagnetic compatibility" to reach R10, because no lighting regulation cites it.
   - Be **strict** here. On the oracle section list, one wrong regulation costs 0.08-0.23 F2 (a lexical walk drags in 170-710 nodes), while dropping R10 costs 0.02-0.04.
3. **Pick sections.** The LLM walks down the table of contents, using the section summaries, and is **inclusive**: a missed section loses all of its gold, and step 5 removes what does not apply. One walk per profile item only finds the sections named after a part or function (26% of the dev requirements), so there are three walks and a search:
   - **per item:** the sections named after a part or function (R48 §6.x, R148 §5.x, R150 §5.1);
   - **once per chosen regulation:** the sections that apply to every device of the class: markings (R148 and R150 §3.3, 17% of the requirements), general and EMC specifications (44%), conformity of production. Do not drop a section by its heading: R148 §3 is titled "Administrative provisions" and holds 25 gold requirements;
   - **by materials and technology:** test methods in the annexes (12%). Choose the Part or the paragraph, not the annex: whole annex scopes have a match rate of 8%, below the F2/5 bar, against 25-37% for the other three kinds;
   - **search:** a hybrid search per item (BM25 via FTS5 plus embeddings) is a safety net for sections, not for emission. Its top 40 hits per item (293 nodes) touch 31 of the 48 gold sections but hold only 21 of the 121 gold nodes. Hits outside the chosen sections are shown to the LLM so it can add them.
4. **List** every obligation in the chosen subtrees. This step is deterministic and uses no LLM.
5. **Check applicability** of each obligation against the profile.
   - Run in batches, with the profile and instructions cached.
   - Drop obligations addressed to the authority, permissions, exemptions and scope text, and drop table rows for other colours or vehicle categories. Decide `admin` by addressee, not by keyword: the gold keeps "the two samples supplied shall…".
   - Keep an obligation only when its estimated match probability is above F2/5 (about 12-16%), measured per confidence bin on the dev case. Doubt alone is not a reason to keep it (`spec/precision.md` §2).
6. **Verify and emit.** Fill in regulation, version (base), page and label from the store, then validate with `tools/validate.py`.

### A5. If a free-form agent is preferred

Give the agent tools instead of the raw graph:

- `list_regulations`
- `get_toc(reg, path, depth)`
- `read_node(id)`
- `search(q, reg?)`
- `follow_refs(id)`
- `get_obligations(id)`
- `submit(obligation_id, rationale)`, which rejects unknown IDs

The agent still walks the graph, but it cannot invent a location.

### A6. Three kinds of error, three policies

- **A wrong or made-up citation** cannot happen by construction: outputs are IDs only, and every quote is verified.
- **A real obligation that doesn't apply** costs precision. F2 favours recall only while precision is above half of recall, and listing whole subtrees gives about 21% node precision, so keep an obligation only when its match probability is above F2/5. Dropped candidates stay visible in the UI with their reason (`spec/precision.md` §2, 4.8).
- **No coverage.** The demo shows a coverage table with every profile item. Items with no match above the threshold show "no applicable provision found in indexed regulations (searched: …)", and nothing is emitted for them.

## Part B: versioning and change propagation

### B1. Never edit nodes in place

A new regulation version is a new set of nodes. Alignment edges link the two versions:

| Edge | Meaning |
|---|---|
| `SAME` | same hash |
| `RENUMBERED` | same hash, new label |
| `MODIFIED` | same label (or a similarity match above the threshold), different hash |
| `REMOVED` | old node has no match |
| `ADDED` | new node has no match |

Matching order: label and hash both equal; then hash only; then label only; then best match by embedding plus token Jaccard, assigned with the Hungarian algorithm. The last step catches cases like "6.5.2 (formerly 6.5)".

### B2. Provenance

- An `obligation` stores `node_text_hash` and `extractor_version`.
- A `mapping` (obligation ↔ spec item) stores `inputs_hash`, a hash of the obligation text, the spec item text and the prompt/model version.
- A mapping's status is `active`, `stale`, `superseded` or `removed`. Nothing is hard-deleted.
- A mapping is stale when its stored hash differs from the current one.

This gives an audit trail of what changed and why, which is also the strongest impact argument for Certivity.

### B3. Trigger: a regulation gets a new version (this is the sub-goal)

1. Parse the new version and align its nodes (B1).
2. **`SAME` and `RENUMBERED` nodes:** carry the obligations over and update only the citation. A page shift is **not** a change, which avoids false "modified" flags.
3. **`MODIFIED` nodes:** re-extract obligations and match old to new within the paragraph. An LLM judge decides whether the meaning changed, using the word diff as evidence: modified, unchanged or removed. New obligations with no match are added.
4. **`REMOVED` and `ADDED` nodes:** their obligations are removed or added. Only count additions inside sections the old requirement set covered.
5. **Reason text.** Build `reason` from a deterministic token diff in the gold format ("Paragraph X (formerly Y) … 'a' became 'b'; 'c' was added"). `new_text` is the old requirement rewritten with the change.
6. **Propagate to specs.** For every spec mapped to this regulation:
   - mappings on removed obligations become `removed`;
   - mappings on modified obligations are re-checked for applicability;
   - added obligations go through step 5 of A4 against the spec profile.
7. **Indirect changes.** If a paragraph or definition that an obligation refers to changes, mark its mappings `stale (review)` without changing them automatically. If the §1 scope changes, re-run regulation selection.

### B4. Trigger: a spec is re-parsed

1. Re-run the profile and match items to their previous keys: by normalized name, with LLM help for renamed parts.
2. Diff the items:
   - **unchanged items** keep their mappings;
   - **changed items** re-run applicability. A red→amber lens or LED→filament change swaps the matching colour or light-source rows;
   - **removed items** lose their mappings, unless another item still supports them;
   - **added items** run A4 for that item only.
3. A change to a global attribute such as vehicle category re-runs everything.

### B5. Trigger: a new regulation is added to the database

1. Index it (A1–A3).
2. Run the regulation-level check against every stored profile. This is cheap: one call per spec.
3. If it applies, run sections → obligations → mappings, with status "added (new regulation)".
4. If it `SUPERSEDES` a regulation that is already mapped, mark the old mappings `superseded`.

## Storage

One SQLite file, loaded into NetworkX for traversal and for the demo's graph views. Neo4j is not worth it at this scale (about 55 regulations × 2 versions).

| Table | Columns |
|---|---|
| `doc` | reg, version, role, sha256 |
| `node` | id, reg, version, kind, label, path, heading, text, text_hash, parent_id, ord, page_start, page_end, char_start, char_end, summary |
| `edge` | src, dst, kind |
| `node_fts` | FTS5 over node text; embeddings stored alongside (numpy or sqlite-vec) |
| `obligation` | id, node_id, ordinal, text, quote, page, kind, condition, node_text_hash, extractor_version |
| `align` / `obl_align` | old, new, kind, sim |
| `spec` | id, case_id, rev, profile_json |
| `spec_item` | id, spec_id, key, kind, text, text_hash |
| `mapping` | id, spec_item_id, obligation_id, status, rationale, inputs_hash, run_id |

## LLM usage (Claude API, Python SDK)

- **Model.** `claude-opus-5-5` by default, with `effort` set explicitly.
- **Bulk extraction (A3)** goes through the Message Batches API, which is 50% cheaper and runs asynchronously. Measure tokens on a sample with `count_tokens` first. Sonnet 5.5 or Haiku 5.5 are options for bulk extraction if quality holds on the anchor tests.
- **Structured outputs** for obligations, selections and diffs. The schema includes `quote`, which is verified in code.
- **Citations API (alternative).** Claude's native Citations feature can return the exact paragraph cited, if each paragraph is passed as its own content block. That fits the demo's explanation text. It can't be combined with structured outputs, so it is not the main path.
- **Prompt caching** for the shared system prompt and the product profile across the many applicability calls.
- **Vision input** for `exploded_view.png`.

## Code layout

New code:

```
src/regcomp/
  corpus.py       # where regulations/index.json and the fetched PDFs are
  parse.py        # A1  PDF → nodes, tree (parent, path), hash and table grids (PyMuPDF); built
  graph.py        # A2  edges, supersession table, SQLite/NetworkX
  obligations.py  # A3  extraction + quote verification (batch)
  profile.py      # A4.1 spec + vision → profile
  pipeline.py     # A4.2–6 selection, filtering, emit main-goal JSON
  diff.py         # B1/B3 version alignment, obligation diff, reason text → sub-goal JSON
  propagate.py    # B2–B5 provenance, staleness, triggers
  app.py          # Streamlit demo: spec → requirements (breadcrumb, PDF page link/highlight), coverage table, change view
eval/
  anchors.py      # parser gate: labels and pages vs gold, requirements_old and the new-version sources of the sub-goal (193/193)
  fidelity.py     # parser gate: numbers of the expert requirements are in the parsed text
  health.py       # parser health over every fetched PDF (no gold needed; flags scope-rej and restart for what the style gate cannot see)
  xprovider.py    # second-provider benchmark: select / author / agree / ground / regrade (DeepSeek through --provider llm); 24 cases in spec/testing/cases/ds-*
  simulate_mapping.py  # graph of 10 regulations, lexical selectors and oracle ceilings vs the gold; --selection scores a model's picks
  judge.py        # local LLM 1:1 requirement matcher (approximates the platform), stage-wise recall, F2
```

Reused from the package:

- `tools/fetch_regulations.py` downloads the PDFs to `regulations/pdf/<reg>/<role>/`.
- `tools/validate.py` checks output files.
- `tools/score_local.py` provides `score()` for regulation- and page-level scores, and `_paragraph_key` for normalizing labels when matching anchors.

## Build order

The held-out cases are released Sunday at 08:00, uploads close at 13:00, and the platform accepts 5 uploads per hour.

1. **Fetch the PDFs and inspect them:** done for all 92 (`spec/finding/finding.md` section 2). The gold `page` is the physical PDF page, confirmed by the footer on every page.
2. **Parser and anchor test (A1):** done, 193 of 193 anchors and all 92 PDFs parse. The weak points of `spec/finding/parser-weak-points.md` section 4 are fixed (section 6 there): scope headings on restart evidence, top-level parts that carry the numbering on, the two health signals, the new-version anchors in the gate, the tree and the hash in `parse.py`; the table fallback was tried and dropped. Open: a label convention for the appendices of an annex that are headed `Appendix N` alone (R131, R157, R171), and R13H Annex 4's plain `A.`/`B.` headings.
3. **Obligation extraction (A3)** for all base versions plus R175 latest, via batch. Check extraction recall against the 94 R175 `requirements_old` entries, which are an independent, expert-written requirement set.
4. **Main pipeline (A4)** on dev-rear-lamp, iterating on the stage-wise metrics below. Upload one dev file to the platform to calibrate the local judge.
5. **Diff and sub-goal (B1/B3)** on `subgoal/dev`.
6. **Propagation triggers (B4/B5) and the demo UI.** Do a dry run on a hand-written front-bumper spec. Likely regulations: R42, R127/GTR 9 and R26, plus R48/R148/R149/R150 and R10 if the bumper carries lamps, reflectors or sensors.

## Verification

- **Parser:** `python eval/anchors.py` must stay at 193 of 193 (a node with the gold's label exists and the gold page is inside its range); `python eval/fidelity.py` for the text; `python eval/health.py --baseline spec/testing/parse-health.csv` after every change, to see what it did to the other 91 PDFs. A label diff over the 92 parses against the committed parser is the acceptance test for any rule that opens or closes a scope (the restart rule changed R101 and no other PDF). Outside the five regulations with anchors these are signals, not proof: R101 passed all three and had a mislabelled appendix. `python eval/xprovider.py regrade` re-grounds the saved DeepSeek cases with the parser as it is and prints which verdicts moved; it needs no model call.
- **Stage-wise recall on the dev case.** This shows where the pipeline is weak, which the brief asks teams to present in the pitch.
  - Regulation level: `python tools/score_local.py out.json`.
  - Section recall: the share of gold paragraphs inside the chosen subtrees.
  - Without a model: `python eval/simulate_mapping.py` gives the funnel (regulations, sections, nodes, reachable requirements, page level) for lexical selectors and oracle ceilings. A model's picks, made without the gold in its context, are scored with `--selection picks.json`.
  - Obligation ceiling: the share of gold requirements matched by any extracted obligation in those subtrees.
  - Final requirement-level precision, recall and F2 from `eval/judge.py`.
- **Where precision is lost** (`spec/precision.md` §5): the funnel with P, R and F2 at every stage, a cause tag on every false positive and false negative, the precision-recall curve over the judge's bins, and platform ablation uploads (output minus one bucket) to check the local numbers.
- **Grounding audit:** 100% of emitted requirements pass quote verification, and 20 random page links are opened and checked by hand.
- **Sub-goal:** compare with `subgoal/dev/expected.json`. Measure recall of flagged IDs, accuracy of the change type, and false flags among the 87 unchanged requirements.
- **Propagation tests:**
  - change the lens from red to amber in a copy of the spec; only the R150 colour rows should swap;
  - delete "Reversing lamp"; its R48 §6.4 mappings should become `removed`;
  - swap R175 base for latest under a stored mapping set; the result should equal the sub-goal answer.
- **Before every upload,** run `python tools/validate.py` on the output file.

## Risks and assumptions

- **Parser accuracy is verified by expert anchors on 5 of 56 regulations, and by a second model's cases on 28 more.** Four of the five are in-sample (the rules were generalised after R148 and R48 failed), R175 is the one hold-out, and the held-out main case has no anchors. The one confirmed defect that passed every gate (R101 Annex 7 Appendix 3, labelled as Appendix 2 because scope headings were recognised by font size and bold alone) is fixed; 96.2% of the 1,461 requirements DeepSeek wrote for 32 regulations now ground in a node with the label it gave, against 84.3% before the fixes, and the rest is a model's own labels, quotes it did not copy, and the open cases above. That is a second writer's opinion of what the labels should be, not the platform's gold: labels no gold settles (the `Part` prefix, appendices of an annex) stay unverified.
- **Tables:** only ruled tables get a grid (8 of 426 captioned tables have none); the unit of a requirement differs per table and the gold's table labels are inconsistent, so the caption page is a hedge, not a certainty.
- **Overfitting.** There is only one dev case, so selection rules could overfit to the rear lamp. Keep them generic: supersession, dropping admin obligations, filtering table rows by colour or vehicle category.
- **Supersession** is read from the introductions of R148, R149 and R150 and agrees with the former hand-written table for the regulations in the index. A regulation without such an introduction is not covered.
- **The dev numbers are in-sample for the design.** The derived electronics item, the category facet and the section kinds were chosen knowing the dev gold, and the regulation and section steps have only been run with BM25 (`spec/finding/mapping-simulation.md` §7). A model's picks have to be scored without the gold in its context.
- **Stack.** This assumes Python and the Claude API; both are easy to swap.
