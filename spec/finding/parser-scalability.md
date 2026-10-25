# Findings: a generic structure parser (marker lexer + stack parse) against the hand rules

Status: results, 2026-10-25. Companion to `spec/finding/parser-weak-points.md` (why each hand rule exists) and `spec/finding/finding.md` sections 2-4. Code: `src/regcomp/parse_marker.py`, tests `eval/test_parse_marker.py`, comparison `eval/parser_compare.py`, gates `eval/anchors.py --parser marker`, `eval/fidelity.py --parser marker`, agent switch `REGCOMP_PARSER=marker` (`src/ai_agent/store.py`). `src/regcomp/parse.py` is untouched and stays the default.

## Summary

- **The generic parser reproduces the hand parser where it counts and needs no per-scheme rule.** 193/193 expert anchors, 281/284 fidelity (same 3 allowed), identical labels on R150, R148, R48 and R175 (base and latest), one label different on R10. End to end on `cases/dev-rear-lamp` its submission scores exactly like the hand parser's under the same code (page P/R 0.731/0.906, requirement F2 0.608 strict / 0.696 lenient against 0.617 / 0.696; the 2-match strict difference is judge noise on one changed chunk).
- **The four scope patches (R101, R49, R67/R89/R163, R13H) are not needed.** Each is reproduced on the real PDFs by the successor relation and the score, not by a font threshold or a regex (section 3).
- **Against the hand parser as a silver set it does not reach 1.0, and the gap is mostly the silver's own errors.** Micro label P/R/F1/F2 0.951 / 0.944 / 0.947 / 0.946 over 92 PDFs; paragraph numbers by page (scope names left out) agree at 0.988 (P 0.995). The losses are named in section 4. The parser is more specific than the hand rules where a heading names two scopes at once: 854 duplicate paragraph labels in the hand parse against 89 in this one.
- **Cost.** Structure part 17 s for 92 PDFs on cached lines (0.2 s median, 0.9 s max); the whole parse including line extraction is 49 s against 37 s for the hand rules. End to end with the cache, the whole dev run spent $0.20 (17 of 18 chunks were byte-identical to the hand-parser run and replayed), judge $0.25.
- **It is not label-policy free.** Which levels are citable (scopes, dotted numbers) and how a bare "Appendix 1" is cited are gold conventions, kept in `LABEL_POLICY`. The scoring weights were set while looking at these 92 PDFs, so every number here is in-sample except R175, R150, R148 and R48, which matched from the first run.

## 1. Design

**Lex.** Every line start is read into a marker: optional keyword (Annex, Appendix, Part), components, decoration. A component has a family: ARABIC (`5`), ARABIC with letter suffix (`2A`, `1a`), LOWER (`b`), UPPER (`B`), ROMAN (`iv`), ROMAN_UP (`IV`). The decoration is `.`, `)`, `(...)` or none. `5.1.4.` is `N.N.N.`, `(ii)` is `(r)`, `Annex 2A` is `Annex N+A`, `Annex 4 - Appendix 1` is two segments, `Annex 2B - Appendix Containers only` is two (an unnumbered keyword is the first one). `i`, `v`, `x`, `I` ... get both readings (letter and roman); the parse picks. A number with no final dot (`5.7 Title`, `1 Scope`) needs a capital after a space; `5.1.2.An immobilizer` is read; `1.20∙10³`, `2.5 mm`, `e.g.` are not markers. `Table` is not lexed: tables, footnote marks, footers, line extraction and table grids come from `parse.py` (`_raw_lines`, `_build_nodes`, `_link_tree`, `_attach_grids`), they are not structure logic.

**Two relations, one first value.** Every family starts at 1 and has a gap function (`gap(prev, cur)`, None if not a successor; `2 -> 2A -> 2B -> 3` all cost 0). Sibling: same signature, last component a successor (gaps cost 0.08 each, capped). Child: a dotted extension of an open node (`2.5` then `2.5.1`; missing levels cost 0.5 each) or any signature at its first value (`1.`, `(a)`, `A.`, `Appendix 1`). A keyword heading may also be a divider: accepted, but the stack is left alone.

**Stack parse, beam.** Candidate lines in reading order; options per line and reading: reject, or for each open level sibling (pop to the level, replace) / first child (push) / divider. Score = evidence of the line (bold, size against body, margin, what the previous line ended with, what follows the number, a keyword heading must be bold) minus structure cost (gap, skipped levels, pops, a keyword under a rank it usually does not sit under) plus a bonus when this signature nested this way before. A beam of 12 states keeps the best paths; the best final path is the structure. A line is accepted only if the whole path is better for it.

**Label policy** (`LABEL_POLICY`, the only gold-specific part). Citable: scopes (keyword frames, label `Annex 4 Appendix 1 Part 2`) and dotted numbers. List items (letters, romans, `(1)`) are in the tree but stay in the text of their paragraph. A stand-alone `Appendix 1` is cited without its annex (the hand parser's convention).

Parameters (all in `parse_marker.py`, none per regulation): beam 12; gap 0.08; skipped level 0.5; keyword first-child above its first value 1.0 per missing number; divider 0.3, 1.0 more beside an open scope of its own signature; first dotted number of a fresh scope above 1: 0.25 per missing number; popping a keyword scope 0.25; rank clash (Appendix under Part) 0.6; nest bonus 0.3; list items worth 0.6 of a paragraph.

## 2. The numbers

| | hand rules | marker parser |
|---|---|---|
| expert anchors (`eval/anchors.py`) | 193/193 | 193/193 |
| fidelity (`eval/fidelity.py`) | 281/284, 3 allowed | 281/284, 3 allowed |
| unit tests | `test_parse.py` 52 pass | `test_parse_marker.py` 28 pass (lexer, gap/succ, i/v/x, beam, R101/R49/R67/R89/R163 cases) |
| silver, micro over 92 PDFs (52k nodes) | 1 | P 0.951, R 0.944, F1 0.947, F2 0.946 |
| silver, macro (mean per PDF) | 1 | P 0.970, R 0.963, F1 0.966, F2 0.964 |
| (label, page) reproduced | 1 | 0.944 |
| (paragraph number, page), scope left out | 1 | R 0.988, P 0.995 |
| PDFs with identical label sets / F1 >= 0.95 / num+page >= 0.98 | 92 | 46 / 77 / 77 of 92 |
| anchored regulations R150, R148, R48, R175 b+l | 1 | 1.000; R10 0.999 (one line, `Annex 1 33`) |
| duplicate paragraph labels in the 92 parses | 854 | 89 |
| time, 92 PDFs, no grids | 37 s (with line extraction) | 49 s (17 s of it the parse on cached lines) |
| dev-rear-lamp, regulation P / R | 0.800 / 1.000 | 0.800 / 1.000 |
| dev-rear-lamp, page P / R (F2) | 0.731 / 0.906 (0.864) | 0.731 / 0.906 (0.864) |
| requirement, strict judge P / R / F2 | 0.418 / 0.700 / 0.617 | 0.412 / 0.689 / 0.608 |
| requirement, lenient judge P / R / F2 | 0.472 / 0.789 / 0.696 | 0.472 / 0.789 / 0.696 |

The two dev runs are the current agent code with `REGCOMP_PARSER` unset and `=marker` (`runs/dev-rear-lamp/a5-rules`, `a5-marker`). They sit below `a1-policy` (regulation P 1.00, page P 0.754) because other agents changed the emission code since then (R128 is now cited); the parser is not the cause. The regulation cards (`catalog.py`) are still built by the hand parser: `store.py` is the only switch. 1,316 candidates against 1,310. 17 of the 18 obligation chunks and the section selections of R148, R150, R48 and R128 replayed from the cache, i.e. byte-identical input; only R10 (one node differs, `Annex 1 33`) was called again ($0.20).

Beam width (matters; this is the "not greedily" claim, num+page recall of the silver, all 92 PDFs):

| beam | 1 (greedy) | 2 | 4 | 12 | 24 |
|---|---|---|---|---|---|
| num+page R | 0.877 | 0.942 | 0.964 | 0.989 | 0.992 |
| label R | 0.828 | 0.901 | 0.922 | 0.944 | 0.938 |

Greedy loses 11 points: every carry-on Part, every spurious number that blocks the real chain. Width 24 buys 0.3 points of numbers and costs a point of label agreement (it settles some scope ambiguities the other way), so 12 stays.

## 3. The hand rules it made unnecessary (checked on the real PDFs)

| Hand rule | What replaces it | Result |
|---|---|---|
| R101 Annex 7 Appendix 3, bold at body size, rescued by the restart rule | `Annex 7 - Appendix 3` is the successor of Appendix 2, bold, so it is a scope at any size | `Annex 7 Appendix 3`, `... 1`, `... 1.1`, `... 1.2` as in the hand parse |
| R49 `Appendix 3 - Item 1..15` (bold, repeats its scope's id) must not open a scope | an equal id is not a successor; the only way in is a "first child" above its first value, which costs 1.0 per missing number | no scope heading with `Item`, as in the hand parse (needed the gap cost: with 0.6 two Item lines opened a scope) |
| R67 / R89 / R163 `Part` numbering carries on, the Part is a divider | a divider costs 0.3, a scope that restarts costs 0.25 per missing first number (10 first in a new Part) and the next Part beside an open Part is clashed | Parts are dividers, paragraphs cited by their printed number, same as the hand parse (R67, R163: all labels equal; R89 latest +1 node) |
| R13H Annex 4 `A.` / `B.` | `A` is a first value, so a first child; a letter list needs nothing more | Annex 4 has the same 33 paragraph labels in both parsers, no node for A and B (list items); R13H differs in one line overall (a formula `0.01 FMnd + 0.015 FMd`) |
| no-space numbers (R162, R48), dotless headings, weak `12 RF absorber` legends, wrapped references, longest chain, footnote lead digits | lexer follow-condition; negative evidence for dotless single numbers, a reference word before the number, small type; the stack order test | R162 and R48 equal; legends rejected, `4 Test requirements` kept when `4.1.` follows (unit test) |

What it does not drop: the size gate. Bold is still used, as evidence (a keyword heading that is not bold is -2.0), and size as a smaller one (+0.5 at 1.15 x body, -1.5 under 0.9); neither is a threshold on its own.

## 4. Where it loses accuracy, and why

Against the silver. The "silver wrong" ones are cases where the hand parse is the less plausible reading; none was fixed with a special case.

| What | PDFs | Cause | Whose error |
|---|---|---|---|
| Heading that names two scopes at once with no dash or with `Part`: `Annex 8 Appendix 1 ...`, `Annex 4 - Part 1 ...`, `Annex 1 - Part 1 - Appendix 2 ...` | R49 (Annex 13, Annex 8 ...), R100, R107, R116, R127, R161, R40 latest | The hand parser reads the line as `Annex N` and labels all the appendices' paragraphs `Annex 13 1.1`, `Annex 13 1.1` ... (854 repeated labels). The marker parser labels `Annex 13 Appendix 3 1.1`. Label agreement 0.7-0.9, paragraph-number agreement 0.97-1.0 | silver, probably; which one the gold uses outside the five anchored regulations is unknown |
| Bare numbers in table cells and forms taken as paragraphs (`3.` alone in a cell, `1.1.` after `X`, `0.01 FMnd + 0.015 FMd`, communication-form fields) | R3, R19, R40 latest, R51, R83, R107, R123, R155, R156 latest | negative evidence (empty rest, previous line without a stop, off the margin) beats a first number in a fresh scope; the hand chain keeps them | silver mostly (cells), but a few (`R155 4.3.1 Threats` dotless headings inside a table of threats) are real paragraphs the marker parser misses: about 40 nodes in 92 PDFs |
| A scope id that repeats or restarts: R164 latest `Part 2 - Test data: Nth braking cycle` repeated per cycle; R3 pages 21-24, an amendment that starts `Annex 1` again after Annex 12 | R164 latest (recall 0.76), R3 (num+page recall 0.82) | a non-successor is rejected by design; the hand parser takes every heavy `Part`/`Annex` line as a scope | marker loses: a repeated scope id is a second family of structure (form pages, appended texts) the relations do not model |
| GTR 9 | GTR 9 | `I.` ... `IX.` are roman list items under the policy, not scopes (hand: `Part I` ... `Part IX`), and `II. Text of the Regulation` repeats II after IX, a non-successor, which the hand parser special-cases by its words. Numbers by page agree at 0.973, labels do not (0.49) | policy gap plus the same restart problem |
| Numbered recitals before the body (R171) | R171 | `1.`-`17.` in the preamble form a chain; the body's `1. Scope` ... compete; the beam keeps recitals and loses `1.1`, `1.2`, `2`, `2.1`, `2.2` | open: ambiguous without a rule about preambles |
| A source out of order (R40 latest `2.5` before `2.4`, R13H `5.1.4.1.3.`) | R40 latest, R13H | both parsers drop one of the two; they pick different ones | tie |

Reading of the table: of the 15 PDFs under label F1 0.95, nine are scope naming only (paragraph-number agreement 0.97 or more), three are cells and forms, three are repeated or restarting scope ids (R164 latest, R3, GTR 9), one is the recitals. Nothing above is an anchored regulation.

Structural limits worth knowing:

- Relations only look forward from open nodes. A scope id that goes backwards (restart) or sideways (repeat) is never accepted. Fixing that needs a third relation ("same signature, restarting at its first value, closing the old family"), and the evidence that distinguishes it from R49's `Appendix 3 - Item 7` is exactly the same shape.
- The evidence weights are hand-set, not learned. 92 PDFs with a silver of unknown quality are too few to fit them; the five anchored regulations are too few to tune on. With the hidden regulations the way to get labelled data is the DeepSeek cases (`eval/xprovider.py author` / `regrade`), 1,406 grounded requirements, and a regrade through the marker parser would be the next gate (the regrade script reads `parse.py` only).
- Per-scheme knowledge is not gone, it moved: the keyword list, the rank order Annex > Appendix > Part (soft, 0.6), the reference-word stoplist and the "bare Appendix drops the Annex" label rule are one place each, and no scheme needs a regex.

## 5. Storage (a paragraph, not a decision)

Now: SQLite plus NetworkX. 92 regulations, base and latest, are about 52,000 nodes and a tree; a node table (`reg, version, label, kind, scope, num, page_start, page_end, parent, text_hash, text, grid`), an edge table (`src, dst, type` with `child`, `refers_to`, `table_of`) and a version map (`old_node, new_node, relation, score`) load into NetworkX in about a second and answer every question the agent and the diff ask (subtree text, ancestors, which node holds a quote, which requirements cite a node that changed). Neo4j earns its place only when several users write at once and cross-version impact queries (product -> requirement -> node -> every version of the regulation -> changed neighbours, three to five hops) must run on the whole corpus without loading it: `(:Regulation)-[:HAS_VERSION]->(:Version)-[:HAS_NODE]->(:Node {label, kind, scope, page_start, page_end, text_hash})`, `(:Node)-[:PARENT]->(:Node)`, `(:Node)-[:REFERS_TO]->(:Node)`, `(:Node)-[:SAME_AS {score}]->(:Node)` across versions, `(:Requirement)-[:CITES]->(:Node)`, `(:Product)-[:MUST_MEET]->(:Requirement)`. The parser's output (`Node` plus `parent`) already is that graph; the choice of store changes none of it.

## 6. How to run

```
python eval/test_parse_marker.py          # 28 tests (unit; corpus tests need regulations/data)
python eval/anchors.py --parser marker    # 193/193
python eval/fidelity.py --parser marker   # 281/284
python eval/parser_compare.py --all --anchors     # the table above (about 2.5 min); --regs UN_R49 --verbose lists labels
REGCOMP_PARSER=marker python src/ai_agent/run.py cases/dev-rear-lamp --no-image
```
