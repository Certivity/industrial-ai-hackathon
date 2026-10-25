# Cheap benchmark: regulations and sections only

Every run stops after the section walks and the citation hop (`--stop-after sections`). Regulation columns are exact. Page-UB columns score `upper_bound.json` (every selected node cited once): recall is a ceiling, precision a lower bound of the real figure (`spec/finding/cheap-bench.md`). F2 = 5PR / (4P + R). Std is the sample standard deviation over cases.

Run folder `c2-v3c`, part `all`.

| case | gold regs | run regs | reg P | reg R | reg F1 | reg F2 | page-UB P | page-UB R | page-UB F1 | page-UB F2 | gold reqs in sections | selected nodes | $ spent / replayed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dev-rear-lamp | R10, R148, R150, R48 | R10, R148, R150, R48 | 1.00 | 1.00 | 1.00 | 1.00 | 0.48 | 1.00 | 0.65 | 0.82 | 190/190 (1.00) | 826 | 0.21 / 0.27 |
| **macro mean of 1** | | | 1.00 | 1.00 | 1.00 | 1.00 | 0.48 | 1.00 | 0.65 | 0.82 | 1.00 | 826 | 0.21 / 0.27 |
| **std of 1** | | | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0 |  |

New Anthropic spend of this call: $0.21.
