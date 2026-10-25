# Submission - team DeepFry (2026-10-25)

All files have `team_id` = `DeepFry`; they are the run outputs of the default configuration (`outputs/` holds the same files with `team_id` team-00).

| File | case_id | Kind |
|---|---|---|
| `main-heldout-front-bumper.json` | heldout-front-bumper | main goal, held-out (206 requirements) |
| `subgoal-heldout.json` | subgoal-heldout | sub-goal, held-out (115 changes) |
| `dev/main-dev-rear-lamp.json` | dev-rear-lamp | main goal, dev worked example (334 requirements) |
| `dev/subgoal-dev.json` | subgoal-dev | sub-goal, dev (33 changes) |

## Configuration
- Parser: the marker parser with per-document induction (`src/regcomp/parse_marker.py`, `marker_induce.py`), the default of `src/ai_agent/store.py` (`REGCOMP_PARSER=rules` selects the hand rules). It is used for the main goal, the regulation cards and the drift pipeline. The DeepSeek outline fallback (`marker_outline.py`, low confidence only) did not trigger on any of the 92 corpus PDFs, so no DeepSeek call was made.
- Main goal: Claude Sonnet 5.5 agent, text + image input, emission policy precision-v2, selection v1.
- Sub-goal (drift): same agent, `--appended added` (convention confirmed by the user).

## Validation (`tools/validate.py --strict`; sub-goal with `--kind subgoal --requirements-old ...`)
- OK: main-heldout-front-bumper.json is valid (206 requirements).
- OK: subgoal-heldout.json is valid (115 changes).
- OK: main-dev-rear-lamp.json is valid (334 requirements).
- OK: subgoal-dev.json is valid (33 changes).

## Dev scores (offline), marker parser against the earlier hand-rule files
- Main dev: regulation P/R 0.80 / 1.00 (F2 0.95; the extra regulation is UN R128), page 0.758 / 0.925 (F2 0.89). Hand rules: 1.00 / 1.00 and 0.731 / 0.906 (F2 0.86).
- Drift dev: flagged 7/7, added 15/17, overall F2 0.85 (hand rules: 0.78).
