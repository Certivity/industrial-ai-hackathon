# Findings: the exploded view as an input (text, image, or both)

Status: results, 2026-10-25. Companion to `spec/finding/ai-agent-baseline.md` and `spec/proposal.md` A4.1. Code: `src/ai_agent/inputs.py`, `vision.py`, `profile.py`, `components.py`; tests in `eval/test_ai_agent.py` (46 pass, offline). The dev image is `cases/dev-rear-lamp/exploded_view.png` (3000x1817): it is labelled, seven callouts of the form "Part / statement", each tied to its part by a leader line to a dot. (Older notes call it unlabelled; that is stale.) The model is `claude-sonnet-5-5`. The agent never opens `expected.json`; the numbers come from `tools/score_local.py` and `eval/bench_agent.py`.

## Summary

- **Input is detected, not assumed.** `inputs.find_inputs`: text is `spec.md`, else `technical_spec.md`, else the one `*.md` that is not a README; image is `exploded_view.png`, else the first `*.png|jpg|jpeg|webp`. Text only, image only, both; neither is an error that names what to give. Flags: `--no-image`, `--no-text`, `--image PATH`. Text-only requests are byte-identical to before (a replay of the old run cost $0.00 and gave the same 363 requirements).
- **The vision pass read the dev drawing without a single error.** 14 of 14 text blocks verbatim (checked against the image by eye), 7 of 7 callouts tied to the right part, all 7 part regions correct, two links rated medium (Reflector, Housing; both right), no invented text. It costs $0.07 for both calls and about 20 s.
- **Mapped to regulations:** `component_map.json` lists, per component, regulations, sections and requirement ids, and per callout the requirements that constrain the same quantity: "Reflector: rear position lamp 4 to 17 cd on axis" gets UN R148 5.2.1 Table 4; "LED modules on PCB: stop lamp 60 to 185 cd" gets R148 5.5.1 Table 7; "Housing: reversing lamp visible to 45 deg outboard" gets UN R48 6.4.5.1; "Retro-reflector: reflectivity at 5 deg" gets UN R150 5.1.4.4.1 Table 3 and Annex 6; "Seal: no water ingress after the spray test" gets UN R150 Annex 6 Part 2. Cost $0.16-0.21 for five small calls.
- **On this case the image barely moves the score.** The spec already names the lamp functions, so the walks already reach the sections the callouts point at (R148 5.2.1 and 5.5.1, R48 6.4.5, R150 5.1.4.4.1 are in the text-only submission too). Same policy, strict judge F2 0.60 (text) vs 0.62 (text + image): inside the +-0.05 noise. The image's value here is the component map, and image-only input (below).
- **The one real effect was negative, and it was the profile, not the image.** The first text + image profile lost the concept "electromagnetic compatibility" (the callouts crowded the horizontal concepts out of 5-15 slots), so UN R10 was not chosen: regulation recall 0.75. A rule in the profile prompt ("callouts add to the concepts, they do not replace them") and a 25-slot limit brought R10 back (verified for $0.15 before the full run). Sampling noise in a `medium` profile can do the same to a text-only run; it is the single most expensive stage to get wrong.
- **A1's new `regulation_check` is brittle here.** It dropped all 52 R10 candidates of the fixed text + image run because none of them was `certain` (text-only had 11 `certain` candidates, this run 1, itself dropped for another reason). With it, regulation recall is 0.75 and strict F2 0.53; with `baseline-v1` it is 1.00 and 0.62. One candidate's label decides 28 expected requirements. Worth a look by whoever owns the policy.

## 1. Design

```
case folder --find_inputs--> text and/or image
image --vision.read--> text blocks (id, verbatim text, role, normalised box)        [call 1, effort high]
      --vision.map --> components, callouts, values, legend, unlabelled parts       [call 2, effort high]
text + facts --profile--> profile.json / profile.md      (profile.md gains "Annotated requirements from the drawing")
... unchanged chain ...
after emit: components.build_component_map --> component_map.json                  [group, assign x N, callouts; effort medium]
```

- **Reading a big drawing.** The API reads at most 2576 px on the long edge and 3.75 MP (about 4,800 image tokens); a 3000x1817 picture would be shrunk by the server anyway, so `vision.prepare` does it and sends the whole drawing at 2488x1507. Because shrinking costs small print, the same picture is also cut into overlapping tiles from the original pixels (grid of about 1500 px tiles with 12% overlap: 2x2 here, 3x3 at most) and sent in call 1, each with its position. Call 1 sees 5 images (14K tokens). A small image gets no tiles. PNG is kept unless it exceeds 4.5 MB (then JPEG q92). PIL is optional: without it the file goes as it is.
- **Call 1 is transcription only** (role per block: title, component_label, value_note, legend_entry, balloon_number, dimension). **Call 2** gets the whole drawing and the transcription and decides what each text is about: leader line, arrow, numbered balloon plus legend table, or proximity (`linked_by`), with a confidence. Nothing in the prompts is about lamps; numbered-balloon sheets with a BOM table are covered by the schema (`legend`) but not tested (no such image in the repository).
- **Merging into the profile.** `build_profile(llm, spec_text, facts)`: with facts the system prompt gets `IMAGE_RULES` and the schema `IMAGE_SCHEMA` (strict; parts carry `source` spec/image/both, attributes `stated/inferred/image`). The spec wins on a conflict. Text-only keeps the old prompt and schema untouched, which keeps the replay cache valid. `profile.md` adds the callout texts verbatim, written by code from the facts, not by the model, so they reach every later prompt exactly as printed.
- **Image only.** The profile is built from the drawing; unstated things (materials, M1) are `inferred` or `unspecified`. On the dev image: 7 parts, 7 callout attributes, regulatory concepts for every callout, vehicle category "unspecified".
- **Component map without touching the extraction.** Call "group" merges spec parts and drawing components that are one physical thing (Outer lens = P4 + C1; Reflector surface = Reflector; Light source = LED modules on PCB; it did not merge the lamp functions with parts); "assign" links every emitted requirement to the components it is about (batches of 130; none means the product as a whole); "callouts" matches each callout to requirements on the same quantity (`same_quantity`), the test that checks it (`related_test`) or the same topic. Requirements matched through a callout are added to the component (`via_callout`).

## 2. What the vision pass read (dev image, checked by eye)

| | Result |
|---|---|
| Text blocks | 14 / 14 exact (7 titles, 7 statements); degree signs intact |
| Callouts mapped to a part | 7 / 7 (leader lines to the lens, retro-reflector, seal frame, reflector panel, PCB, housing, screws) |
| Part regions (box) | 7 / 7 on the right part |
| Link confidence | 5 high, 2 medium (Reflector, Housing) |
| Unlabelled parts reported | 0 (none are drawn without a callout; the dashed alignment lines are not parts) |
| Weak spot | `unit` is sometimes a phrase ("after the spray test") and the Reflector callout is rated medium because the line ends on the reflector panel inside the housing |

## 3. Numbers on the dev case

Policy `precision-v1` is A1's current default, `baseline-v1` the earlier three-filter policy (the one of `ai-agent-baseline.md`, run 2). A replay under another policy is free, and the judge answers repeated pairs from the cache, so the rows are comparable.

| Run | Submitted | Regulation P / R (cited) | Page P / R | Paragraph P / R | Requirement strict P / R / F2 | Lenient F2 | $ |
|---|---|---|---|---|---|---|---|
| Text only, `baseline-v1` (run 2) | 363 | 0.80 / 1.00 (R128 extra) | 0.59 / 0.96 | 0.41 / 0.89 | 0.37 / 0.71 / **0.60** | 0.69 | 3.95 |
| Text only, `precision-v1` | 306 | 1.00 / 1.00 | 0.75 / 0.91 | 0.48 / 0.86 | 0.44 / 0.70 / **0.62** | 0.70 | replay |
| Text + image, first profile, `precision-v1` | 279 | 1.00 / 0.75 (R10 not chosen) | 0.76 / 0.77 | not judged | not judged | | 3.96 |
| Text + image, fixed profile, `baseline-v1` | 358 | 1.00 / 1.00 | 0.63 / 0.96 | 0.44 / 0.88 | 0.39 / 0.73 / **0.62** | 0.71 | 3.61 |
| Text + image, fixed profile, `precision-v1` | 265 | 1.00 / 0.75 (R10 dropped by the policy) | 0.79 / 0.77 | 0.50 / 0.74 | 0.41 / 0.57 / **0.53** | 0.61 | replay |
| Image only (stopped before extraction, `--max-cost 0.75`) | n/a | 1.00 / 0.75 chosen (R148, R150, R48) | n/a | n/a | n/a | n/a | 0.76 |

F2 = 5PR / (4P + R). Strict and lenient are the local judge (`eval/judge.py`), noise about +-0.05; the platform's own judge is not available offline. `tools/validate.py --strict` passes on all submissions. Regulation and page level are `tools/score_local.py`.

What changed in the choice (fixed text + image against text only): R128 is no longer chosen (it was the one extra regulation, picked at medium confidence in text-only runs; with the callouts in the profile the model has no reason to look at light-source regulations beyond the device ones); R10, R148, R150, R48 are chosen; selected provisions 826 against 975, every one of the 190 expected requirements and 121 expected paragraphs still inside. The sections of the callouts were already selected without the image.

Image only: the profile and regulation choice are sound (R148, R150, R48 chosen at high confidence, all the callout topics in the concepts) but R10 is missed, as in the first text + image run: a drawing says nothing about electronics beyond "LED modules on PCB", and the profile has "electronic components and wiring" but not "electromagnetic compatibility". A full image-only run (about $4) was not done within the $10 budget; the command is below. Expect its requirement-level score to sit at or below the first text + image row until the profile asks for the horizontal concepts a drawing cannot show.

## 4. Cost

| | $ |
|---|---|
| Vision (2 calls, replayed afterwards) | 0.07 |
| Component map (5 calls) | 0.16 (265 requirements), 0.21 (363) |
| Profile + regulations check of the fix | 0.15 |
| Text + image, first profile, full run | 3.96 |
| Text + image, fixed profile, full run | 3.61 (+0.43 judge) |
| Image-only partial | 0.76 |
| Total | about 9.2 |

A new profile changes every later prompt, so any change to the drawing or the profile prompt is a fresh $3.5-4 run; the vision pass itself is cheap and cached by image bytes.

## 5. Limits

- Tested on one image. A balloon-and-legend sheet, a photo with labels, a dense multi-view drawing or rotated text are covered by the prompt and schema but not measured. Handwriting and very low resolution are likely to fail silently (the pass reports what it read, not what it missed; tiles are the only recourse).
- The pass reads text; it does not judge geometry (a part drawn but never named is reported in `unlabelled_parts` at best). A drawing with no text gives almost nothing.
- Callout values are passed on verbatim, not checked against a regulation; `component_map.json` shows the match, a person judges it.
- The profile is the fragile stage: sampling in a `medium` call can drop a horizontal concept (EMC) and with it a whole regulation. Cheap to fix in the prompt, but the underlying noise is the same in the text-only path.
- `component_map` uses model calls; it is a demo artifact and its failure is logged, not fatal.

## 6. How to run

```
python src/ai_agent/run.py cases/dev-rear-lamp --max-cost 6                  # text + image (the folder's exploded_view.png), about $4
python src/ai_agent/run.py cases/dev-rear-lamp --no-image                    # text only (replays free if cached)
python src/ai_agent/run.py cases/dev-rear-lamp --no-text --max-cost 6        # image only, about $4
python src/ai_agent/run.py <case> --image path/to/drawing.png                # an explicit image
python src/ai_agent/components.py runs/<case>/<run id> [max USD]             # component_map.json for an existing run
python tools/validate.py runs/<case>/<run id>/submission.json --strict
python tools/score_local.py runs/<case>/<run id>/submission.json --expected cases/dev-rear-lamp/expected.json
python eval/bench_agent.py runs/<case>/<run id> --expected cases/dev-rear-lamp/expected.json
```

Files of a run with an image: `vision.json` (text blocks, components, callouts, notes) and `component_map.json`. Deliverables of this experiment: `outputs/dev-rear-lamp-image/` (`submission.json` under `precision-v1`, `submission-baseline-policy.json`, `component_map.json`, `vision.json`, `profile.md`, `bench.json`). Run folders: `runs/dev-rear-lamp/a4-textonly2`, `a4-textimage`, `a4-textimage2`, `a4-textimage2-base`, `a4-imageonly`, `a4-vision`.

## Addendum (2026-10-25): text + image under `precision-v2`

The default policy no longer has the regulation check (`spec/finding/precision-tuning.md`, addendum), so R10 survives. The same text-and-image run, replayed: 317 requirements, regulation P/R 1.00/1.00, page P/R 0.731/0.906, strict P/R/F2 0.429/0.716/**0.631**, lenient F2 0.715 (`runs/dev-rear-lamp/lead-textimage-v2`; $0.09, the component map). This is now `outputs/dev-rear-lamp-image/submission.json`; the precision-v1 file is kept as `submission-precision-v1.json`.
