# Drift cases

Ten real base -> latest pairs of UN Regulations for the sub-goal "which requirements derived from the old version change" (README.md section 3). Each folder has `pair.json` (regulation, versions, PDFs under regulations/data, the window of sections), `requirements_old.json` (the requirements an expert would derive from the old window, written by DeepSeek in the format of subgoal/dev), `expected.json` (the changes, subgoal schema, team_id `synthetic`), `provider.json` (the raw DeepSeek replies) and `notes.md`.

Both files were written by a model (DeepSeek, thinking off), not by experts: the decisions were checked against the deterministic alignment of the two versions (a flagged requirement on a paragraph with the same text is dropped) and the `reason` strings were built in code from the paragraph diff in the format of subgoal/dev/expected.json. The gold is noisy: use it for insight, and subgoal/dev for the number that counts.

Regenerate: `python eval/drift_cases.py build --send` (needs the LLM_* lines of .env), check: `python eval/drift_cases.py check`.

| Case | Regulation | Versions | Window | Old reqs (paragraphs) | Modified | Removed | Added | Trap |
|---|---|---|---|---|---|---|---|---|
| drift-r39-speedometer | UN R39 | 2.1.0 -> 2.2.0 | 2, 5 | 57 (28) | 5 | 0 | 4 | ADS exemptions, one-word typography fixes |
| drift-r100-battery-adsf | UN R100 | 5.0.0 -> 5.1.0 | 5 | 83 (42) | 8 | 0 | 3 | the same sentence added to many paragraphs; a cross-reference re-pointed |
| drift-r131-aebs-rewrite | UN R131 | 2.3.0 -> 2.4.0 | 5 | 61 (47) | 0 | 1 | 3 | same label, paragraph rewritten (alignment sees a removal and an addition) |
| drift-r156-ota-renumber | UN R156 | 0.1.0 -> 1.0.0 | 6, 7 | 37 (36) | 0 | 0 | 2 | renumbering only: 13 paragraphs shift by one with the text unchanged |
| drift-r149-lamp-uid-removed | UN R149 | 1.6.0 -> 1.7.0 | 3.2, 3.3 | 74 (41) | 9 | 2 | 1 | a removed section shifts the numbering below it ('formerly 3.3.4'); removal of a phrase in many paragraphs |
| drift-r10-emc-few-changes | UN R10 | 7.2.0 -> 7.3.0 | 6 | 63 (37) | 0 | 0 | 4 | almost everything unchanged; only added paragraphs (every unchanged requirement is a false-flag risk) |
| drift-r132-reagent-restructure | UN R132 | 1.0.0 -> 1.1.0 | 7, 8 | 55 (51) | 4 | 0 | 4 | a list merged into one paragraph (five removals and one addition that say the same) |
| drift-r51-noise-asep | UN R51 | 3.10.0 -> 3.11.0 | Annex 7 | 74 (22) | 3 | 1 | 7 | formulas and a new table; wording of calculations |
| drift-r174-belt-reminder | UN R174 | 1.0.1 -> 1.1.0 | 5 | 51 (39) | 2 | 0 | 1 | footnote text changes and ADS sentences; a reference fixed (6.2.4.1.1 -> 5.2.4.1.1) |
| drift-r64-tyre-terms | UN R64 | 3.1.0 -> 3.2.0 | Annex 3, Annex 4 | 46 (35) | 10 | 0 | 0 | terminology swap that changes the test trigger ('ignition' -> 'vehicle master control'), 'must' -> 'shall' |
