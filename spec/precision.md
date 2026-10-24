# Precision: where it is lost, what fixes it, how we measure the rest

Status: analysis and plan, 2026-10-24. Companion to `spec/proposal.md` and `spec/finding/finding.md`. It replaces the proposal's "when in doubt, keep it, because F2 rewards recall" (A4 step 5, A6).

## Summary

- **The problem.** Listing every node in the gold-touched subtrees gives node precision **21% at recall 100%** on the dev case (568 nodes, 121 cited). The 26-49% in `finding.md` §2.8 is the same list behind a shall/must gate, which costs R48 a third of its recall. Both use the *oracle* subtrees; the real pipeline also has to choose regulations and sections, so its precision will be lower.
- **F2 does not mean "keep everything".** Recall is the better lever only while P > R/2. At P = 0.21 and R = 1, one point of precision is worth about 5.5 points of recall. A candidate is worth emitting only if its chance of matching the gold is above **F2/5**, about 12-16% at the F2 values we can reach.
- **Rules fix part of it.** Dropping heading-only nodes (96 uncited, 0 cited) and lab-setup nodes (51 uncited, 3 cited) takes node precision from 21% to 29% at 96% recall (F2 0.575 to 0.657). Keyword rules for "admin" and "other variant" fail: together they hit 27 cited nodes carrying 53 gold requirements.
- **The applicability judge fixes more.** If it classified the admin, variant and permission buckets perfectly, node precision would be 44% at 96% recall (F2 0.774). That is the ceiling for filtering inside the right sections.
- **The rest cannot be fixed from the text.** 149 uncited and 84 cited nodes look alike (36% match rate): which of them the experts chose is a judgment the regulation does not encode. Under F2 the right move is to keep them and show the cost: funnel, error taxonomy, precision-recall curve, platform ablation uploads (section 5).

## 1. The numbers

Measured with the prototype parser on the four base PDFs of the dev case. A subtree is a depth-2 body section or an annex/part scope that holds at least one gold-cited node, as in `finding.md` §2.8. A node counts as cited when the gold cites its label (compared with `tools/score_local.py::_paragraph_key`).

| | R150 | R148 | R48 | R10 | all |
|---|---|---|---|---|---|
| nodes in the regulation | 513 | 402 | 1,181 | 815 | 2,911 |
| nodes in gold subtrees | 186 | 168 | 123 | 91 | 568 |
| cited | 31 | 40 | 35 | 15 | 121 |
| precision, every node | 17% | 24% | 28% | 16% | 21% |
| precision / recall, shall/must only (`finding.md` §2.8) | 26% / 94% | 44% / 92% | 49% / 63% | 27% / 93% | |
| precision / recall, after the rules in 4.1-4.3 | 22% / 97% | 29% / 95% | 40% / 97% | 30% / 93% | 29% / 96% |

These are node-level proxies, not the score. The gold has 190 requirements on 121 nodes, the platform matches requirements one to one, and section choice (the gold subtrees leave out 58-90% of each regulation's nodes) is not measured here.

## 2. The F2 arithmetic

F2 = 5PR / (4P + R), the brief's ranking metric (p.2).

- **Which lever is worth more.** ∂F2/∂P ÷ ∂F2/∂R = (R / 2P)². The two are worth the same at the margin when P = R/2. Below that line precision is the cheaper gain: at P = 0.21, R = 1 the ratio is about 5.5.
- **When to emit one more candidate.** Write Fβ = (1+β²)·TP / (β²·G + S), with G the number of gold requirements and S the number submitted. A candidate with match probability p adds p to TP and 1 to S, and the score goes up exactly when p > TP / (β²·G + S) = Fβ / (1+β²). For β = 2 the bar is **p > F2/5**.
- **So the decision is per bucket.** Measure each bucket's match rate on the dev case; drop a bucket below the bar, keep one above it, even when it is noisy. At F2 between 0.6 and 0.78 the bar is 12-16%.

| Bucket | match rate | against a bar of 12-16% |
|---|---|---|
| A regulation that does not apply | about 0 | never "to be safe": regulation choice is strict |
| Heading-only nodes | 0% | drop |
| Lab setup | 6% | drop |
| Lead-in stems ending in ":" | 11% | at the bar: fold into the children, do not drop (4.2) |
| Rest (uncited and cited look alike) | 36% | keep |

Under F2, about 40% precision at high recall can be the best achievable, and the pitch should say so with this arithmetic rather than hide it. How the platform combines the regulation, page and requirement levels into one ranking number is not stated; this assumes the requirement level dominates.

## 3. Where the false positives are

Each uncited node in the gold subtrees was put in the first bucket whose rule matched, in this order. The rules are deliberately crude: they measure how big each bucket is; except for heading-only and lead-in, they are not the proposed filter.

| Bucket | Rule used to measure it | uncited | cited (gold reqs) | match rate | Verdict |
|---|---|---|---|---|---|
| Heading only | under 60 characters, no verb, no digit | 96 | 0 (0) | 0% | parser drops it (4.1) |
| Lead-in stem | text ends with ":" | 17 | 2 (2) | 11% | one extraction unit with its children (4.2) |
| Lab setup | photometer, apparatus, stray light, harness, ground plane, ISO 11452 set-up, "shall be measured" | 51 | 3 (7) | 6% | drop; keep conditions that define a product limit (4.3) |
| Admin (keywords) | applicant, Technical Service, sampling, report, inspector | 39 | 14 (33) | 26% | keywords fail; decide by addressee (4.3) |
| Other variant (keywords) | trailer, triangle, plate, direction indicator, DRL, fog, REESS, HV, trolleybus | 87 | 13 (20) | 13% | keywords too blunt; match conditions against the profile (4.4) |
| Permission / meta (keywords) | "need not", "may comply", "shall be deemed" | 8 | 5 (6) | 38% | keywords useless |
| Rest | | 149 | 84 (122) | 36% | the judge's job; keep under F2 |
| **Total** | | **447** | **121 (190)** | **21%** | |

What is in the uncited buckets:

- **Heading only:** R150 3.3 "Approval marking and other markings", 4.2 "Colorimetric test conditions", 5.1.4.4 "Class IA and Class IB".
- **Lab setup:** R150 Annex 4 Part 1 3.8.1 (photometer head correction), R10 Annex 9 4.1.2.1.x (harness lengths and heights above the ground plane).
- **Admin:** R150 5.1.2 "The applicant shall submit ten samples", R10 6.1.2 (Technical Service test plan), R148 6.1.2 (sampling by an inspector).
- **Other variant:** R150 Annex 5 (trailer triangles, rear marking plates, SMV plates, advance warning triangles); R148 direction indicators, daytime running lamps, front position lamps with infrared generators; R10 REESS charging mode, HV harnesses, trolleybuses.
- **Rest:** R48 5.5.1 (lamps of a pair fitted symmetrically) is not cited while 5.5.4 and 5.5.5 are; R150 4.1.3 (attachment of marking material). Nothing in the text separates these from what was cited.

What the gold keeps that keyword rules would drop, which is why the LLM has to decide:

- **"Admin" words in product obligations:** R150 3.3.4.1 "shall bear the trade name or mark of the applicant"; R148 5.2.1, 5.5.1, 5.8.1 and 4.8.3.1 "the light emitted by each of the two samples supplied shall…".
- **Test text that fixes a product condition:** R150 Annex 6 Part 4 4.1 (no excessive corrosion after the salt-spray test), Annex 6 Part 6 3 with Table A6-1 (weathering exposure), R10 Annex 9 3.1 (20 to 6,000 MHz), R148 4.9 (colour measured inside the light-distribution field).
- **Variant words in applicable text:** 13 cited nodes name another variant in passing. R48 6.7.2, 6.7.4.1 and 6.7.5 (stop lamps) set S1/S2 and S3/S4 rules side by side; R48 6.10.8 ties the tell-tale to the front position lamps; R150 Table 3 lists every class, including the red Class IA/IB row the gold keeps.
- **Lead-in stems the gold cites:** R48 5.18 "may be installed on movable components only:" (its children are conditions on the stem) and R150 Annex 6 Part 6 3 (the stem owns Table A6-1).

## 4. Fixes, in order of value per hour

**4.1 Heading-only nodes are structure, not candidates.** The parser marks them; they stay in the breadcrumb and the table of contents and never reach the extractor. 96 false positives fewer, no gold lost.

**4.2 A lead-in stem and its children are one extraction unit.** A node ending in ":" never yields a requirement on its own. The extractor sees the stem with its children and decides where the obligation sits:

- in a child, with the stem as context (R150 3.3.2 "The approval marking shall consist of:", gold cites 3.3.2.2; R48 5.5, gold cites 5.5.4);
- in the stem, when the children are its conditions (R48 5.18);
- in the stem plus its table (R150 Annex 6 Part 6 3 with Table A6-1).

**4.3 Two more fields at extraction** (proposal A3, `finding.md` 4.6):

- `addressee`: product, manufacturer, test-lab or authority. It is set by **what is constrained, not by who is named**: "the two samples supplied shall meet Table 4" constrains the product.
- `modality`: obligation, permission, exemption or scope.
- Drop authority, permission, exemption and scope. Keep test-lab text only when it fixes a condition or pass criterion the product is judged by (a frequency range, an exposure, a limit after the test); drop instrument and fixture set-up.

**4.4 Match conditions against the profile with tri-state facets.**

- Extraction adds `applies_if` to each obligation: device function, class or category, colour, light-source technology (LED module, replaceable source, filament), mounting (inside or outside the vehicle, movable component), vehicle category, optional features (variable intensity control, interdependent lamp system, infrared generator).
- The profile answers yes, no or unknown for each facet value from a **closed list** built from the regulations' own vocabulary: R48 §6's 28 device sections, R148 lamp categories, R150 classes. "No direction indicator" is then an explicit answer, not a silence.
- A contradiction drops the obligation and records the reason; unknown keeps it. This is aimed at the 87-node variant bucket.

**4.5 Calibrated threshold.** The applicability judge returns a bin (certain, likely, possible, unlikely). On the dev case, measure each bin's match rate and emit the bins above F2/5; recompute F2 and repeat until it stops moving (two or three rounds). Check that the bins hold under leave-one-regulation-out; a bin whose rate crosses the bar between folds is reported as unstable.

**4.6 Granularity.** Under one-to-one matching an extra split is a false positive and a merge is a false negative. The gold has 1.26 requirements per cited node in R150, 1.58 in R148, 1.60 in R48 and 2.13 in R10. Track our ratio per regulation and per node kind (paragraph or table), and look at every node where we emit more than the gold.

**4.7 Strict regulation choice.** A card per regulation with the reason it was chosen or rejected; SUPERSEDES and CITES_REG as in proposal A2/A4. A wrong regulation brings dozens of candidates with p close to 0.

**4.8 Two tiers in the UI.** The submitted file holds the emitted tier. The UI also lists the dropped candidates with their reason ("applies to direction indicators; the profile has none"), and the engineer can restore one in a click. The score stays lean and nothing is hidden, which is the brief's own argument (p.2: an engineer can discard an extra requirement but cannot act on a missing one, and every extra one has to be read).

**Expected effect, node level, oracle subtrees:**

| Step | nodes | cited | P | R | F2 |
|---|---|---|---|---|---|
| Every node in the subtrees | 568 | 121 | 21% | 100% | 0.575 |
| Drop heading-only (4.1) | 472 | 121 | 26% | 100% | 0.633 |
| Lead-in stems, worst case dropped (4.2) | 453 | 119 | 26% | 98% | 0.635 |
| Drop lab setup, keyword rule (4.3) | 399 | 116 | 29% | 96% | 0.657 |
| Perfect judge on admin, variant, permission (4.3-4.4) | 265 | 116 | 44% | 96% | 0.774 |

The last row is a ceiling, not a forecast.

## 5. Measuring the rest, and what the pitch shows

**M1. Local judge, `eval/judge.py`.** An LLM scores each (ours, gold) pair as the same obligation or not; the Hungarian algorithm makes the matching one to one; output is requirement-level P, R and F2 offline. This is the number every other measurement uses.

**M2. Platform ablation uploads** (5 valid uploads per hour on the dev case).

- Upload the full output, then the output minus one bucket. The platform shows P and the file size S, so matched = P × S, and the difference between the two uploads is the platform's own count of matches in that bucket.
- One upload with obligations merged pairwise, or split further, shows how strictly the platform judges granularity.
- The same pairs calibrate M1: the local and platform differences should agree.
- Do not upload the gold or a near copy: the dev leaderboard shows the best upload, and a perfect dev score would look like gaming.

**M3. Funnel, no oracle.** Regulations → sections → nodes → obligations → after filters → emitted. At each stage report P, R, F2 and the recall ceiling (the share of gold still reachable). It extends the stage-wise recall in the proposal's Verification section.

**M4. Error taxonomy.**

- Each false positive is tagged: wrong regulation, wrong section, variant mismatch, admin, lab setup, lead-in, over-split, duplicate or judge error.
- Each false negative is tagged: regulation missed, section missed, not extracted, filtered wrongly or merged.
- A stacked bar per regulation is the pitch's "where it is weak" slide.

**M5. Precision-recall curve** over the judge's bins, with F2 iso-lines, the chosen point and the F2/5 bar. It shows the trade-off as a measured choice rather than a default.

**M6. Generalisation.** Leave-one-regulation-out over the four dev regulations: tune the bins on three, measure on the fourth, and report the spread. State plainly that the dev set is one product and four regulations.

**M7. Held-out forecast.** Before uploading, predict P and R from the dev bucket rates times the held-out bucket counts; after uploading, compare with the platform's headline numbers. A close forecast is the strongest proof that we know where we are weak.

**The slide.** Three panels (the M3 funnel, the M4 bars, the M5 curve) and one sentence per panel with a number, for example: "Most of our false positives are paragraphs the experts left out of sections we got right; we keep them because their match rate (36%) is above the F2 bar (15%)."

**Build items:**

- `eval/precision_buckets.py`: reproduces the table in section 3 once `src/regcomp/parse.py` exists. The prototype used here lives in a temporary scratchpad.
- `eval/judge.py` (M1).
- The funnel and taxonomy report (M3, M4), as one command over a run directory.
- An upload log: file hash, variant, P, R and F2 as shown by the platform.

## 6. Not measured, and risks

- **Oracle subtrees.** Section choice was not measured, so real precision and recall are lower than everything above.
- **Node level is not requirement level.** 190 requirements sit on 121 nodes, and granularity errors (4.6) do not show at node level.
- **Crude bucket rules.** They size the buckets. The proposed filters are the addressee, modality and facet fields, which have not been built or measured.
- **One dev case.** The held-out front bumper uses other regulations; bucket rates may move. M6 gives the spread, not a guarantee.
- **The rest bucket may be partly gold incompleteness.** The proposal notes 44 gaps in the gold ids. We cannot tell a paragraph the experts rejected from one they skipped.
- **Ranking formula.** How the platform combines the three levels into one score is not stated.
