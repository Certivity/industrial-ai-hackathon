# testing/: six new main-goal cases, written by DeepSeek, and the agent's score on them

Six cases in the shape of the platform's input and answer: `technical_spec.md` (Product Type / Vehicle Category / Function / Main Parts / Materials) and `expected.json` (the format of `cases/dev-rear-lamp/expected.json`). Table of results: `RESULTS.md`; per-case JSON (taxonomy, funnel, judge): `results/<case>.json`; run folders: `_benched.json`; what was generated: `_generated.json`.

**Read the numbers with one caveat first.** The gold of each case is DeepSeek's opinion (`deepseek-flash`, thinking off), not an expert's. `spec/testing/report.md` 10.4 measured how far two golds of the same model differ (a lot), and the regulations a model picks for a product are its own choice: for `ts-motorcycle-silencer` it put R53 (lighting installation of L3 vehicles) and R10 (no electronics in a silencer) in the gold, and the agent's refusal of both is probably the better answer. The dev case (expert gold) is the yardstick for the level of the numbers: regulation P/R 0.80/1.00, page P/R 0.59/0.96, requirement F2 0.60 strict / 0.69 lenient.

## How the cases were made

```
python eval/xprovider.py author --id ts-<product> --brief "<product, vehicle category; no regulation named>" \
    --provider llm --send --timeout 900 --out-root testing --spec-name technical_spec.md \
    --style testing/_gold_style.json --max-regulations 4 --context 400000
```

- `--out-root` (default `spec/testing/cases`) and `--spec-name` (default `spec.md`) are new, and so is `--style`; without `--style` the prompts are byte for byte those of the 24 `ds-*` cases (`--max-regulations 3` gives the old "three at most").
- `--style testing/_gold_style.json` only switches on two blocks of generic rules in `eval/xprovider.py` (`STYLE_SPEC_RULES`, `STYLE_GOLD_RULES`), written from the style statistics A3 took from the expert gold: 3 to 5 regulations, the current regulation instead of the one it replaced, the horizontal regulation (EMC) when there is electronics, a section mix of about 25% function-named, 15% markings, 45% general/design, 12% test parameters, administrative paperwork left out, about 120-240 requirements and 1.5 per paragraph. No text of the dev case is in a prompt, and nothing from `cases/` was sent.
- DeepSeek invents the product, chooses the regulations from the 56 titles in `regulations/index.json`, reads their page text and writes requirements with page, paragraph and a verbatim quote. `ground` checks every quote against the PDF text and our parse; only `ok` and `wrong page` requirements go into `expected.json`, with page and paragraph label taken from the parser (`build_expected`). Audit files per case: `provider.json` (what the model wrote), `ground.json` (verdict per requirement), `authoring.json`, `expected.json`. The exact prompts and replies are in `regulations/data/_xprovider/author-<id>-llm/` (git-ignored).
- Briefs (one `author` call each; the first `ts-motorcycle-silencer` was dropped at 81% grounding and generated again):
  - `ts-pedestrian-front-end`: front-end structure with energy-absorbing bumper, deployable active bonnet and pedestrian protection, M1
  - `ts-lpg-conversion`: LPG conversion kit (tank, multivalve, vaporiser, gas injectors, control unit) for a petrol passenger car, M1
  - `ts-moto-antitheft`: steering lock and electronic immobiliser with alarm for a two-wheel motorcycle, L3
  - `ts-motorcycle-silencer`: replacement exhaust silencing system for a motorcycle, L3
  - `ts-ev-sound`: acoustic vehicle alerting system and exterior sound of a battery electric passenger car, M1
  - `ts-coach-m3`: intercity coach, M3, 50 seats, emergency exits, interior fittings, heating system
- Regulations of the gold, grounding and size (kept of written):

| case | regulations in the gold (requirements) | written / kept | grounding | paragraphs |
|---|---|---|---|---|
| ts-pedestrian-front-end | R127 27, R42 23, R26 29, R10 46 | 131 / 125 | 95% | 90 |
| ts-lpg-conversion | R67 257, R10 26, R83 21 | 325 / 304 | 94% | 274 |
| ts-moto-antitheft | R161 69, R162 54, R163 75, R10 34 | 247 / 232 | 94% | 184 |
| ts-motorcycle-silencer | R92 39, R40 18, R53 60, R10 37 | 169 / 154 | 91% | 114 |
| ts-ev-sound | R51 52, R10 54, R100 31, R48 75 | 215 / 212 | 99% | 166 |
| ts-coach-m3 | R107 108 (R10 and R43 chosen, nothing of them grounded) | 110 / 108 | 98% | 93 |

All six `expected.json` pass `tools/validate.py --strict`. Regulations not used by the dev case: R127, R42, R67, R83, R161-R163, R92, R40, R53, R51, R100, R107, R43; R10, R26 and R48 do occur. R10 is in four of the six golds.

## Benchmark

`python eval/bench_cases.py testing/ts-* --judge ts-moto-antitheft ts-pedestrian-front-end --benched-out testing/_benched.json` (default efforts, `--max-cost 5` per run, runs in `runs/<case>/a2-default`; `latest.txt` there makes the next call reuse them). F2 = 5PR / (4P + R), `tools/score_local.py --expected <case>/expected.json`.

| case | n gold / emitted | gold regs | agent regs | reg P / R / F1 / F2 | page P / R / F1 / F2 | judge F2 strict / lenient | agent $ |
|---|---|---|---|---|---|---|---|
| ts-pedestrian-front-end | 125 / 127 | 10, 26, 42, 127 | 10, 26, 42, 127 | 1.00 / 1.00 / 1.00 / 1.00 | 0.67 / 0.57 / 0.62 / 0.59 | 0.34 / 0.55 | 2.46 |
| ts-lpg-conversion | 304 / 987 | 10, 67, 83 | 10, 67 | 1.00 / 0.67 / 0.80 / 0.71 | 0.75 / 0.81 / 0.78 / 0.80 | - | 4.69 |
| ts-moto-antitheft | 232 / 265 | 10, 161, 162, 163 | 10, 62, 162, 163 | 0.75 / 0.75 / 0.75 / 0.75 | 0.78 / 0.71 / 0.74 / 0.72 | 0.51 / 0.67 | 2.13 |
| ts-motorcycle-silencer | 154 / 37 | 10, 40, 53, 92 | 92 | 1.00 / 0.25 / 0.40 / 0.29 | 1.00 / 0.10 / 0.18 / 0.12 | - | 0.40 |
| ts-ev-sound | 212 / 104 | 10, 48, 51, 100 | 10, 51 | 1.00 / 0.50 / 0.67 / 0.56 | 0.76 / 0.21 / 0.33 / 0.25 | - | 2.90 |
| ts-coach-m3 | 108 / 476 | 107 | 10, 43, 107 | 0.33 / 1.00 / 0.50 / 0.71 | 0.28 / 0.90 / 0.42 / 0.62 | - | 4.79 |
| mean of 6 | | | | 0.85 / 0.69 / 0.69 / 0.67 | 0.71 / 0.55 / 0.51 / 0.52 | | 17.36 |
| dev-rear-lamp (expert gold) | 190 | 10, 48, 148, 150 | (R128 as well) | 0.80 / 1.00 | 0.59 / 0.96 | 0.60 / 0.69 | |

The judge costs $0.46 and $0.27; the total Anthropic spend of this work is about $18.1. Runs were made with the emit policy as it was at the time (A1 changes it later; `_benched.json` lets A3 re-emit these cached runs).

## Errors by case

- **Wrong regulation (cited, not in the gold).** `ts-moto-antitheft`: R62 (anti-theft for motorcycles) instead of DeepSeek's R161 ("devices for protection against unauthorized use"); for an L3 steering lock R62 is the natural pick, so this is as likely a gold flaw as an agent error. `ts-coach-m3`: R10 and R43, with 71 and 51 requirements; the coach has electronics and glazing, and DeepSeek's own spec call chose them, but its gold kept no grounded requirement of them. That is the cost of a single-regulation gold: precision 0.33 at regulation level and 0.28 at page level, recall 1.00 / 0.90.
- **Missed regulation (in the gold, not chosen).** `ts-motorcycle-silencer`: R40 (vehicle emissions), R53 (lighting installation) and R10 are all rejected by the agent with a reason (no pollution device, no lamps, no electronics); the gold's 115 requirements of them are the writer's choice, and recall collapses to 0.25 / 0.10 for that reason alone. `ts-ev-sound`: R100 (31, electric power train) and R48 (75, lighting installation) not chosen, which is 106 of 212 gold requirements. `ts-lpg-conversion`: R83 (21 requirements, emission type approval).
- **Page and paragraph misses inside the right regulations.** Page recall is lowest where regulation recall is low (silencer 0.10, ev-sound 0.21, from missed regulations) and where a long regulation has many gold paragraphs the agent skipped: `ts-ev-sound` R51 cites 10 of 40 gold paragraphs (30 missed: test-method annexes and measuring conditions), `ts-pedestrian-front-end` R42 4 of 21 and R26 9 of 22 (the agent writes 10 and 11 requirements from them against 23 and 29 in the gold), R127 7 of 16. Recall in the funnel (gold requirements inside the selected sections) is 157/232, 109/125, 270/304, 92/212, 37/154, 108/108.
- **Extra paragraphs (precision).** `ts-lpg-conversion` R67 emits 921 requirements on 498 paragraphs for 257 gold on 233 (286 extra paragraphs), and R10 25 extra: page P is still 0.75 because R67 is large and the pages overlap, but at 987 emitted for 304 gold the requirement-level precision is low. `ts-coach-m3`: 171 extra paragraphs of R107. The dev case has the same pattern at smaller scale (page P 0.59).
- **Judge (two cases).** Strict / lenient F2 0.51 / 0.67 for the anti-theft case and 0.34 / 0.55 for the pedestrian case, against 0.60 / 0.69 on the dev case: the right regulations (pedestrian: 4 of 4) do not give matching requirements when the agent writes about a third of the gold's requirements for R26 and R42 from the same sections.

## What this says, and what it does not

- Regulation choice is where the agent and the DeepSeek golds differ most, and in 3 of the 6 cases (silencer, ev-sound, anti-theft) the difference is at least as much the gold's choice as the agent's. Use the regulation numbers of these cases to find over-strictness (R100 for a battery-electric sound system, R48 for an AVAS) and over-breadth (R10 and R43 on the coach), not as a score to tune on.
- Requirement-level (judge) numbers exist for two cases only; both are below the dev case.
- A second DeepSeek writer would give other numbers for the same product (report 10.4). The six golds contain 1,135 requirements, of which 1 to 9% (by case) were written by the model with a quote that is not on the page and were dropped; the kept ones are real paragraphs of the real PDFs, but their selection is not an expert's.
- `testing/` cases are plain folders (no `spec.md`): the agent reads `technical_spec.md` through `src/ai_agent/inputs.py`. `xprovider select` and `agree` still look for `spec.md`.

## Network note

On the machine these cases were made on, a request over about 1 KB to DeepSeek was dropped after 19 s (packets sent back to back are lost). `eval/xprovider.py post` now falls back, after one dropped connection, to small writes with a 30 ms pause (`SmallSegmentsConnection`; `XPROVIDER_SMALL_SEGMENTS=1` starts there, `XPROVIDER_SEGMENT_PAUSE` sets the pause). Prompts of 380 KB to 1.07 MB went through that way. About 4.3 MB of prompt text (about 1.07M tokens at 4 characters) and 430 KB of reply text (about 110K tokens) went through the successful calls for the six cases, plus the prompts of failed attempts, whose billing is unknown. No usage figures are kept by `xprovider`.
