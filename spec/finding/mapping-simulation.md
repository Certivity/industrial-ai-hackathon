# Findings: mapping the rear-lamp spec onto a graph of ten regulations

Status: results, 2026-10-24. Companion to `spec/finding/finding.md`, `spec/precision.md` and `spec/testing/report.md`. It runs the proposal's selection steps (A4.2 regulations, A4.3 sections) on the dev case with no model in the loop and scores them against `cases/dev-rear-lamp/expected.json`. Every number of mine comes from `eval/simulate_mapping.py`; its full output is `spec/testing/mapping-sim.txt` and the per-requirement rows are `spec/testing/mapping-sim.csv` (the other seeds in section 3.1 were run with `--seed` and not saved). `spec/proposal.md` was updated from it (section 6).

## Summary

- **Parsing and anchoring are not the limit.** The prototype parser turns R150, R148, R48, R10 and six random regulations (R132, R40, R163, R19, R67, R155) into 6,304 nodes, 6,050 parent edges, 1,556 REFERS_TO edges (94% of the targets inside the regulation resolve) and 203 CITES_REG edges into the index. All 190 gold requirements land on a node with the gold's label and page: 121 distinct nodes, in 48 sections.
- **Regulation level: the right four are reachable, with four helpers and a fragile cut.** One BM25 card per regulation (title, §1, depth-2 table of contents) ranks the gold regulations R48, R148, R150, R10 at 14, 5, 12, 31 of 56 when the query is the whole spec (the setting of `eval/baseline.py`, which got 12, 2, 8, 31). The table of contents in the card, an "electronics" profile item, a vehicle-category facet read from §1 and SUPERSEDES read from the regulations' own introductions bring them to 1, 3, 5, 2. R149 is the one false positive. Among the ten regulations they rank 1-4, but a cut at 0.4 times the best score drops R150 in all four draws tried.
- **R10 cannot be found through the graph.** R48, R148 and R150 never cite it; R148 4.7.2.3 says "electromagnetic compatibility" without a number. R10 ranks 2-3 of 56 when the profile says "electrical/electronic sub-assembly (ESA), electromagnetic compatibility" and 12-21 when it says "LED module, printed circuit board". The profile step has to turn materials into regulatory concepts.
- **A wrong regulation costs more than a missing marginal one.** On the oracle section list, adding any of five of the six random regulations costs 0.08-0.23 F2 (a lexical walk drags in 172-711 nodes); dropping R10 costs 0.02-0.04, R150 0.04-0.06, R148 or R48 0.11-0.12. That supports "be strict" in A4.2.
- **Section level is where a selector without a model fails.** Only 26% of the gold requirements sit in sections named after a part or function of the product. Markings hold 17%, general and EMC specifications 44%, annex test methods 12%. A heading walk finds 7 of the 8 function-named sections and 25% of the gold nodes; heading plus text finds 57% at 8% precision. Behind the regulation step, the same walk reaches 75 of the 190 requirements (node precision 8%, F2 0.22). One walk per profile item, as A4.3 has it, can only find the first class.
- **Whole annexes are the wrong unit.** The 11 gold-touched annex scopes hold 204 nodes and 17 cited ones (8%), below the F2/5 bar of about 12%. Markings, general sections and function-named sections have match rates of 37%, 28% and 25%.
- **Requirement level: the text is in the node.** 187 of 190 gold requirements have at least 80% of their content words in their anchor node plus its parent and children (a random node of the same regulation: median 5%). BM25 with the gold text as the query ranks the anchor first for 164. A plain sentence extractor on the 121 anchor nodes matches 158 of 190 at lexical cosine 0.6 (precision 56%); the misses are one sentence split into several requirements, and table rows. This is a lexical proxy, not the platform's judge.
- **Read the numbers as a floor.** No model was called, there is one dev case, and the gold was in my context when I wrote the rules, so I did not make the model's choices by hand. `--selection` scores picks made blind.

## 1. What was run

| Item | Setting |
|---|---|
| Parser | `src/regcomp/parse.py` as it was (sha256 starting 2765567f, 294 lines), unchanged during the run. PyMuPDF was not installed in the Python environments I checked (base Anaconda and `hackathon`); I used 2.0, installed outside the repo, and `python eval/anchors.py` gave 178/178 with it first |
| Regulations | R150, R148, R48, R10 (the gold's) and six drawn by `random.Random(20261024).sample(pool, 6)`, the pool being the 52 other regulations in `regulations/index.json` order: R132, R40, R163, R19, R67, R155. `testing/report.md` uses the same seed over a different pool, so its draw differs. Seeds 1, 2 and 3 were also run |
| Profile | read from `spec.md`: 5 functions and 5 parts, plus one derived item (section 3). `exploded_view.png` is an unlabelled line drawing (lens, three rows of LED reflectors, a retro-reflector window) and adds nothing |
| Selectors | BM25 with a small stemmer. Settings fixed before scoring: a regulation is kept at 0.4 times the best score; per profile item, the best 3 sections and only those at 0.5 times the item's best |
| Gold | used to score, never to select. A "section" is a depth-2 body section or a whole annex, appendix or part scope, as in `spec/precision.md` |

What is not simulated is every step that needs a model. Choosing by hand would have been an oracle in disguise, so the lexical selectors give a floor, the oracle rows a ceiling, and `--selection` scores any picks made elsewhere.

## 2. The graph

| Regulation | Version | Pages | Nodes (paragraph, table, scope) | Orphans | REFERS_TO resolved | CITES_REG, regulations in the index |
|---|---|---|---|---|---|---|
| R148 | 1.6.0 | 48 | 414 (386, 16, 12) | 0 | 92% | 4 |
| R48 | 9.3.0 | 122 | 1,205 (1,181, 0, 24) | 0 | 96% | 17 |
| R150 | 1.2.1 | 54 | 540 (502, 11, 27) | 0 | 89% | 2 |
| R10 | 7.2.0 | 148 | 864 (782, 33, 49) | 0 | 99% | 2 |
| R132 | 1.0.0 | 50 | 586 (573, 1, 12) | 0 | 99% | 2 |
| R40 | 1.1.0 | 31 | 363 (353, 0, 10) | 5 | 98% | 0 |
| R163 | 0.3.0 | 26 | 333 (319, 1, 13) | 0 | 84% | 4 |
| R19 | 4.10.0 | 48 | 449 (433, 0, 16) | 0 | 97% | 3 |
| R67 | 4.2.0 | 123 | 1,370 (1,333, 4, 33) | 0 | 87% | 2 |
| R155 | 0.2.0 | 24 | 180 (159, 12, 9) | 0 | 100% | 0 |

A node's parent is the nearest earlier node in its scope whose number is a prefix of its own; a table hangs under the paragraph that names it. REFERS_TO and CITES_REG use the regexes of `finding.md`, extended to "paragraph 3 of Part 1 of Annex 4" and to lists ("Nos. 13 and 13-H"); a number with a leading zero ("00 series") is not a regulation. SUPERSEDES comes from the PDFs (section 3).

Between the ten: R48 cites R148, R150, R163 and R19; R148, R150 and R19 cite R48; R163 cites R10, R155 and R48; R67 cites R10. R10, R155, R132 and R40 cite none of the others.

The six random regulations have no gold, so the checks are structural. Nodes hold 98.1-99.9% of the characters that are not footers (the remainder is mostly front matter). Four things to know:

- **R40** has no section `2`: its heading line reads `1 2. DEFINITIONS`, a single span with a stray leading `1`, so the number is not at the line start and 2.1-2.5 are orphans. An orphan count is a cheap health flag; `eval/health.py` has one now (`orphans`, added in `spec/testing/report.md` section 9).
- **R132 and R155** have stray spaces inside heading words (`Marki n gs and labels`, `Co n formity of production`), which would defeat a heading match.
- **R67 and R163** are laid out in Parts: R67 has two numbered body sections and its paragraphs sit in Part I (148), Part II (203) and annexes, with labels like `Part I 3.1`. Whether the experts cite them that way is unknown.
- **R163 (84%) and R67 (87%)** resolve fewer references than the four dev regulations (89-99%).

## 3. Regulation level

### 3.1 The ladder

Ranks of the gold regulations, with one card per regulation (title, §1 scope, depth-2 table of contents) and the IDF of all 56 cards. The "10" columns are the same ranking restricted to the ten parsed regulations.

| Card and query | R48 | R148 | R150 | R10 | R48 (10) | R148 (10) | R150 (10) | R10 (10) |
|---|---|---|---|---|---|---|---|---|
| whole `spec.md`, title + §1 (the setting of `eval/baseline.py`) | 14 | 5 | 12 | 31 | 4 | 2 | 3 | 7 |
| profile items, title only | 8 | 9 | 7 | 21 | 2 | 3 | 1 | 5 |
| profile items, title + §1 | 14 | 2 | 8 | 34 | 4 | 1 | 3 | 8 |
| profile items, title + §1 + table of contents | 1 | 3 | 11 | 25 | 1 | 2 | 4 | 5 |
| + a derived electronics item | 1 | 4 | 19 | 3 | 1 | 3 | 5 | 2 |
| + vehicle-category facet from §1 | 1 | 3 | 18 | 2 | 1 | 3 | 5 | 2 |
| + SUPERSEDES from the introductions | 1 | 3 | 5 | 2 | 1 | 3 | 4 | 2 |

Two implementations written separately agree where they can be compared: R10 is 31st of 56 in both the first row and `testing/report.md`, and the other three differ by 2-4 places.

What each step does:

- **The table of contents** lifts R48 from 14th to 1st: its card now lists the 28 device sections ("Reversing lamp", "Stop lamp", "Rear position lamp"). It costs R150, whose card is short, three places.
- **The derived item** ("electrical electronic sub-assembly ESA electromagnetic compatibility") is what lifts R10 from 25th to 3rd. Section 3.2.
- **The category facet** reads the vehicle categories named in §1 and drops regulations that do not name the spec's letter (M). It drops R53, R62, R40, R102 and R92. R53, the installation regulation for L3 vehicles, was second before it.
- **SUPERSEDES** moves R150 from 18th to 5th, because it inherits the score of R3. Before it, R7 is 5th, R3 7th, R23 9th and R19 10th, against R148 4th and R150 19th. R149 (road illumination) scores 22.0 by itself, 6th, and stays: R19 and R123 redirect to it, and it does not apply to a rear lamp either. SUPERSEDES is a redirect, not a relevance signal.

The set kept at 0.4 times the best score is, among 56: R48, R10, R148, R149, R150 (P 0.80, R 1.00, F2 0.95). The cut is fragile. At 0.5 R150 drops (P 0.75, R 0.75); at 0.3 R13H comes in (P 0.67, R 1.00); at 0.6 only R48 and R10 are left. Among the ten, R150 scores 10.3 against 42.0 for R48 and 9.4 for R163, the best wrong one after SUPERSEDES, so no relative threshold separates it, although the four gold regulations are exactly the top four. At 0.4 the ten give R48, R10, R148 (P 1.00, R 0.75). In seeds 1, 2 and 3 the kept set is the same and R150 ranks 4th, 6th and 4th (in seed 2 R13H outranks it).

The random six are mostly easy negatives: R19 is the only lamp regulation, R163 and R155 are electronics-adjacent, R132, R40 and R67 are about emissions and LPG. The 56-regulation columns are the real test, since they hold every older lamp regulation.

### 3.2 R10 depends on the wording of the profile

R10's rank among 56, before and after the facet and SUPERSEDES steps, for different wordings of the extra profile item:

| Derived item | Lexical | After facet and SUPERSEDES |
|---|---|---|
| none | 25 | 16 |
| "electromagnetic compatibility" | 10 | 5 |
| "electrical electronic sub-assembly ESA" | 4 | 3 |
| "LED module printed circuit board electronics" (the spec's own words) | 21 | 12 |
| both regulation concepts (the item used above) | 3 | 2 |

The item in the ladder uses R10's own vocabulary, so the ladder shows what a profile step that knows "LED on a PCB means ESA, and ESA means R10" reaches, not what lexical matching reaches. The graph does not help: among the ten parsed regulations R10 is cited only by R163 (4 times) and R67 (3 times), and in the three lighting regulations the only node that mentions electromagnetic compatibility is R148 4.7.2.3, in a footnote with no regulation number. A title-phrase edge ("electromagnetic compatibility" is R10's title) would connect it; it is not in the proposal.

### 3.3 Citations lead to device regulations, with the older ones

The whole of R48 cites 17 regulations of the index. A heading walk (20 sections) reaches 6 of them. The four function-named lamp sections (6.4, 6.7, 6.10, 6.14) cite R148 three times, R150 once, and the older R23, R7 (twice) and R3 (once), which SUPERSEDES turns into R148 and R150, plus R13H once (the braking signal of the stop lamp, a false positive). So following CITES_REG from the chosen sections finds R148 and R150, as the proposal says, with one wrong regulation; following it from the whole of R48 brings in R149 (18 mentions), R104, R37, R128, R6, R19, R116, R162, R163 and more.

### 3.4 What a regulation-level error costs

The base is the oracle section list of the four regulations (568 nodes, precision 21%, F2 0.575). A wrong regulation brings in the nodes a lexical walk ("heading + text") picks in it. "By requirements" weighs recall by the share of gold requirements still reachable, which matters for R10 (32 requirements on 15 nodes).

| Scenario | Nodes removed or added | Node F2 | Change | Change, by requirements |
|---|---|---|---|---|
| drop R148 | -168 | 0.458 | -0.117 | -0.117 |
| drop R48 | -123 | 0.463 | -0.112 | -0.114 |
| drop R150 | -186 | 0.520 | -0.055 | -0.036 |
| drop R10 | -91 | 0.552 | -0.024 | -0.038 |
| add R155 | +16 | 0.566 | -0.009 | -0.009 |
| add R163 | +172 | 0.494 | -0.081 | -0.081 |
| add R40 | +193 | 0.486 | -0.089 | -0.089 |
| add R19 | +209 | 0.480 | -0.095 | -0.095 |
| add R132 | +286 | 0.452 | -0.123 | -0.123 |
| add R67 | +711 | 0.343 | -0.232 | -0.232 |

Missing R10 costs less than adding any of the five random regulations whose walk picks 170 nodes or more. Two things pull the other way and the table does not settle their size: an applicability filter would remove most of what a wrong regulation drags in, and a base with higher precision than 21% would make the same extra nodes cost more. Read the table as an order of magnitude. It points where A4.2 already does: strict on regulations.

## 4. Section, node and page level

### 4.1 Where the gold sits

The gold-touched sections of the four regulations, by kind (the kind is read from the heading: F a short heading that contains every word of a part's name, M a marking heading, T an annex scope, G the rest of the body):

| Kind | Sections | Requirements | Cited / listed nodes | Match rate | Which |
|---|---|---|---|---|---|
| F function-named | 8 | 50 (26%) | 31 / 125 | 25% | R48 6.4, 6.7, 6.10, 6.14; R148 5.2, 5.5, 5.8; R150 5.1 |
| M markings | 3 | 33 (17%) | 25 / 68 | 37% | R148 3.3, R150 3.3, R10 5.2 |
| G other body sections | 26 | 84 (44%) | 48 / 171 | 28% | R48 §5 (10 of its subsections); R148 4.3, 4.5-4.9, 6.1; R150 4.1, 4.2; R10 6.1, 6.5-6.10 |
| T annex scopes | 11 | 23 (12%) | 17 / 204 | 8% | R150 Annex 2, 4 Part 1, 5, 6 Parts 1, 2, 4, 6; R148 Annex 3, 8; R10 Annex 9, 10 |

- **Three quarters of the gold is not found by naming a function.** The spec says nothing about markings, general specifications, electromagnetic immunity or weathering tests; they apply to the product as a device, an electronic assembly and a plastic part.
- **A heading must not decide.** R148's top-level section 3 is titled "Administrative provisions" and holds 25 gold requirements on 17 nodes (its subsection 3.3 is the approval marking); R150's section 3 holds 7. Dropping "admin" sections wholesale loses 32 of the 190 requirements (17%). The printed table of gold requirements by top-level section is in `spec/testing/mapping-sim.txt`.
- **Whole annex scopes lose.** The T kind has a match rate of 8%, below the F2/5 bar (the oracle list's F2 is 0.575, so the bar is 11.5%). The other three kinds are at 25-37%.

### 4.2 Selectors

Regulation set: the four gold regulations, except in the last two rows. "Reachable" is the number of gold requirements whose anchor node is in the list. Page P/R is `tools/score_local.py`, one entry per listed node.

| Selector | Sections (of gold) | Nodes | Cited nodes | Node P | Node R | F2 | Reachable | Page P / R |
|---|---|---|---|---|---|---|---|---|
| every node of the four regulations | 357 (48) | 2,911 | 121 | 4% | 100% | 0.18 | 190 | 18% / 100% |
| heading walk | 47 (12) | 341 | 30 | 9% | 25% | 0.18 | 46 | 40% / 43% |
| heading + text walk | 67 (19) | 890 | 69 | 8% | 57% | 0.25 | 97 | 29% / 68% |
| oracle: F only | 8 (8) | 125 | 31 | 25% | 26% | 0.25 | 50 | 89% / 30% |
| oracle: F + M | 11 (11) | 193 | 56 | 29% | 46% | 0.41 | 83 | 88% / 43% |
| oracle: F + M + G | 37 (37) | 364 | 104 | 29% | 86% | 0.61 | 167 | 90% / 81% |
| oracle: every gold-touched section | 48 (48) | 568 | 121 | 21% | 100% | 0.58 | 190 | 65% / 100% |
| regulation step (R48, R10, R148), then heading + text walk | 52 (14) | 661 | 50 | 8% | 41% | 0.22 | 75 | 30% / 53% |
| regulation step, then oracle sections | 37 (37) | 382 | 90 | 24% | 74% | 0.52 | 151 | 75% / 77% |

The walk is "per profile item, the best 3 sections". It finds, of the gold sections, function-named 7 of 8 (heading) and 5 of 8 (heading + text), markings 1 and 2 of 3, other body sections 3 and 8 of 26, annexes 1 and 4 of 11. In R48 the heading walk picks 20 sections, 6 of them with a gold node (6.4, 6.7, 6.10, 6.14, 5.11, 5.18) and 14 wrong (definitions 2, 2.2 and 2.8; other §5 items; the device sections 6.15, 6.16, 6.23, 6.25 and 6.28; an annex part). Inside R10 it finds 1 of 10: its ESA specifications (§6.5-6.10) all apply, which a top-3 cap cannot express.

- **The best list without a filter leaves the annexes out.** F + M + G has F2 0.61 against 0.58 for every gold-touched section, because the annex scopes add 17 cited nodes for 204 listed.
- **Page level is lenient.** The oracle list has node precision 21% and page precision 65%; every node of the four regulations has 4% and 18%. A page is a coarse unit (`testing/report.md` 5.1 says the same).
- **Each step loses recall.** Losing R150 at the regulation step takes the oracle list from 190 reachable requirements to 151; the lexical walk behind it takes 151 down to 75.

### 4.3 Search as a safety net

BM25 on each node's own text, per profile item the top N, over the four regulations:

| N per item | Nodes | Gold nodes | Gold sections touched |
|---|---|---|---|
| 5 | 47 | 4 | 12 of 48 |
| 10 | 90 | 7 | 17 |
| 20 | 161 | 15 | 24 |
| 40 | 293 | 21 | 31 |

Search nominates sections far better than it finds paragraphs: at 293 nodes it touches two thirds of the gold sections but holds 17% of the gold nodes. It is a way to show the model sections it did not open, not a way to emit requirements.

## 5. Requirement level

Without the platform's judge, three lexical measures:

- **Containment.** The share of a gold requirement's content words (stemmed, numbers kept) found in its anchor node. Own text: median 1.00; 182 of 190 reach 0.8, 8 are between 0.5 and 0.8, none is below 0.5. With the parent and the children: 187 reach 0.8. A random node of the same regulation: median 0.05, and only one of the 190 is above 0.5. Five of the eight below 0.8 are declarative items in R48 and R148 where the gold supplies the subject from the section heading: R148 5.2.7 "Colour: The colour of light emitted shall be red" becomes "The light emitted by the rear position lamp shall be red"; R48 6.4.4.3 "In length: at the rear of the vehicle" becomes "The reversing lamps shall be at the rear of the vehicle in length". The other three are a lead-in stem (R48 5.18) and two R150 items. So the unit of extraction is the node plus its breadcrumb.
- **Round trip.** With the gold text as the query, BM25 over the nodes of its regulation ranks the anchor first for 164 requirements, within the top 3 for 182 and within the top 10 for 189. A produced requirement can be traced back to its node by its text.
- **Extractive floor.** Every sentence of the listed nodes is a candidate, matched one to one with the gold by TF-IDF cosine, best pairs first. Rewriting counts as a miss and so does paraphrase the judge would accept, so this is a proxy.

| Candidates | Sentences | Matched at 0.6 | P | R | F2 |
|---|---|---|---|---|---|
| the 121 anchor nodes | 280 | 158 | 56% | 83% | 0.76 |
| every gold-touched section | 935 | 162 | 17% | 85% | 0.48 |
| heading + text walk | 1,477 | 98 | 7% | 52% | 0.22 |
| every node of the four regulations | 4,656 | 170 | 4% | 89% | 0.16 |

At 0.5 and 0.7 the anchor-node row matches 170 and 147. By regulation (anchor nodes, 0.6): R148 55 of 63, R48 45 of 56, R150 34 of 39, R10 24 of 32. The 32 misses are mostly one node that the gold splits into several requirements (R10 6.9.1 alone accounts for 7: one per voltage system and per pulse; R48 5.1 and 5.3 are split too; R150 Table 3 gives a table row and a note) plus the declarative items above. Extraction has to split and rewrite, not only cut, which is what A3 already says.

## 6. Where this changes the proposal

| Proposal says | Measured | Change made |
|---|---|---|
| A2: SUPERSEDES is a hand-written table (R148: R6, R7, R23, R38; R149: R19, R123; R150: R3, R104) | Each of the three regulations states it in its "Introduction (for information)": R148 "Nos. 4, 6, 7, 23, 38, 50, 77, 87 and 91", R149 "19, 98, 112, 113, 119 and 123", R150 "3, 27, 69, 70 and 104". The part in the index equals the table | read it from the PDFs; the former table is the check, and they agree; it is a redirect, not a relevance signal |
| A2, A4.2: follow CITES_REG from installation to device regulations | True from the chosen sections (R148, R150), but the whole of R48 cites 17 regulations; its lamp sections also cite R23, R7, R3 and R13H | follow it from the chosen sections, then apply SUPERSEDES, and expect a false positive |
| A4.2: a card has the title, §1 and a short table of contents | 0.7K-4.9K tokens, median 1.6K; all 56 cards about 106K; the table of contents lifts R48 from 14th to 1st | all cards fit in one prompt; keep the table of contents; a category facet from §1 and SUPERSEDES run first |
| A4.1 and A4.2: LED/PCB means ESA | No lighting regulation cites R10; its rank among 56 goes from 2 to 25 with the wording of the profile | the profile carries regulatory concepts, and the wording is tested |
| A4.2: be strict, a wrong regulation drags in dozens of false requirements | 172-711 nodes under a lexical walk for five of six; F2 -0.08 to -0.23; dropping R10 -0.02 to -0.04 | strict stays; the figure is hundreds, not dozens |
| A4.3: one walk per profile item | function-named sections hold 26% of the requirements | three walks: per item, once per regulation (markings, general and EMC specifications, conformity of production), by materials and technology (test annexes) |
| A4.3: search hits are a safety net | 21 of 121 gold nodes in the top 40 per item, 31 of 48 gold sections touched | search nominates sections, never emits |
| A4.3, A4.5: list the chosen subtrees, keep above F2/5 | annex scopes as units have a match rate of 8% | choose the Part or paragraph inside an annex; never drop a section by its heading ("Administrative provisions" holds 25 gold requirements) |
| Risks: the supersession table must be checked | checked on R148, R149, R150 | reworded; a risk added: the dev numbers are in-sample for the design |
| Verification: stage-wise recall | `eval/simulate_mapping.py` gives the funnel without a model | listed; picks of a model are scored with `--selection` |

## 7. Not measured, and risks

- **No model.** The regulation and section steps are BM25. What a model reading the cards and the table of contents reaches is the missing measurement. Because the gold was in my context, only a blind run counts: give a model the spec and the cards, save its picks as `[{"regulation": "UN R48", "root": "6.10"}, ...]`, and score them with `python eval/simulate_mapping.py --selection picks.json`.
- **In-sample design.** The derived item, the category facet and the F/M/G/T kinds were chosen knowing the dev gold. The thresholds (0.4; best 3 per item; 0.5) were fixed before scoring and not tuned, but with one dev case that is a weak guarantee. Ranks in 3.1 do not depend on a threshold; they do depend on the card and on the derived item.
- **Fragile cut.** A relative threshold decides R150's fate in every draw; ranks are the more robust statistic.
- **Node level is a proxy.** F2 at node level ignores granularity (`precision.md` 4.6). The requirement-level figures are lexical.
- **Cost of errors is an order of magnitude.** It uses the oracle list (21% precision) as the base and a lexical walk to drag in nodes. A filter would shrink what a wrong regulation drags in; a more precise base would make the same nodes cost more (3.4).
- **The random draw is easy.** Only R19 is a lamp regulation. The 56-regulation ranking is the test.
- **PyMuPDF 2.0** is not necessarily the version used for the other findings; the anchor gate reproduced 178/178 with it, and the node counts agree with `parse-health.csv`.
- **The kinds F/M/G/T** are read from headings by a rule in the script, not labelled by hand; the printed lists show every assignment.

## 8. Reproduce

```
python eval/simulate_mapping.py                                        # about 45 s; PyMuPDF and the base PDFs are needed
python eval/simulate_mapping.py --seed 3 --csv spec/testing/mapping-sim.csv
python eval/simulate_mapping.py --selection picks.json                 # score picks made elsewhere, e.g. by a model
```
