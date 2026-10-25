# Team DeepFry: 2-minute pitch (AI side)

**[0:00-0:20] The problem**
A company builds a vehicle part. Its engineers must know every requirement the part has to meet under the UN Regulations. We read the product spec and the drawing. We return those requirements, each with the regulation, the page, the paragraph and the exact quote. For the sub-goal, we also show what changes between two versions of a regulation.

**[0:20-1:30] What we built**

1. **Models decide, code verifies.** Claude Sonnet 5.5 makes the judgement calls. Code checks every quote against the regulation text. The model never writes a page or a paragraph, so a citation cannot be invented.
2. **A deterministic regulation graph.** Our parser turns each PDF into a tree of paragraphs, annexes and tables. The same PDF always gives the same nodes. The submission uses the version that learns each document's structure (the marker parser with induction, the default); it scores about the same as the hand-rule version on the dev case. A model outline is only a verified fallback, and it did not trigger on any of the 92 corpus PDFs.
3. **An agent that works like an engineer.** It profiles the product, picks regulations, walks each regulation's outline, follows citations to other regulations, and then writes one checkable requirement per obligation.
4. **Drawing understanding.** It reads every label on the exploded view, ties each to its part, and maps parts to requirements.
5. **A cheap drift agent.** Code aligns old and new paragraphs by hash. The model sees only changed paragraphs that carry requirements. The held-out case cost $0.42.
6. **Honest evaluation.** We tune on one split and report on held-out cases. We rejected a rule that fit the dev case and failed elsewhere.

**[1:30-1:50] The numbers**
On the expert rear-lamp case, we found all four regulations with no extras. Page precision is 0.73 and recall 0.91. At requirement level, our local judge gives F2 0.63 strict and 0.72 lenient. A full run costs about $4.

**[1:50-2:00] Close**
The model reads the law. The code keeps it honest.
