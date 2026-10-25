# drift-r131-aebs-rewrite

UN R131, base 2.3.0 -> latest 2.4.0; window: sections 5.

What changed: AEBS: paragraph 5.4.5 ('the AEBS function may be suspended while ALKS is active') is replaced by a heading and three obligations (deactivate, reactivate, 5.4.4 not applicable).

Trap: same label, paragraph rewritten (alignment sees a removal and an addition).

Alignment of the window (src/ai_agent/drift.py): {'SAME': 57, 'RENUMBERED': 0, 'MODIFIED': 0, 'REMOVED': 1, 'ADDED': 4}.

Old requirements: 61; gold changes: 0 modified, 1 removed, 3 added (1 of 61 old requirements flagged).

The gold was written by DeepSeek (provider.json); the reasons are built in code from the diff. It is a noisy gold.

Changed paragraphs sent to the provider:

- 5.4.5 (REMOVED): R-052
