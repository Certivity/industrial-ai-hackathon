# Cheap benchmark: regulations and sections only

Every run stops after the section walks and the citation hop (`--stop-after sections`). Regulation columns are exact. Page-UB columns score `upper_bound.json` (every selected node cited once): recall is a ceiling, precision a lower bound of the real figure (`spec/finding/cheap-bench.md`). F2 = 5PR / (4P + R). Std is the sample standard deviation over cases.

Run folder `c2-vet2`, part `all`.

| case | gold regs | run regs | reg P | reg R | reg F1 | reg F2 | page-UB P | page-UB R | page-UB F1 | page-UB F2 | gold reqs in sections | selected nodes | $ spent / replayed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dev-rear-lamp | R10, R148, R150, R48 | R10, R128, R148, R150, R48 | 0.80 | 1.00 | 0.89 | 0.95 | 0.44 | 1.00 | 0.61 | 0.80 | 190/190 (1.00) | 936 | 0.04 / 0.39 |
| **macro mean of 1** | | | 0.80 | 1.00 | 0.89 | 0.95 | 0.44 | 1.00 | 0.61 | 0.80 | 1.00 | 936 | 0.04 / 0.39 |
| **std of 1** | | | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0 |  |

New Anthropic spend of this call: $0.04.
