# Cheap benchmark: regulations and sections only

Every run stops after the section walks and the citation hop (`--stop-after sections`). Regulation columns are exact. Page-UB columns score `upper_bound.json` (every selected node cited once): recall is a ceiling, precision a lower bound of the real figure (`spec/finding/cheap-bench.md`). F2 = 5PR / (4P + R). Std is the sample standard deviation over cases.

Run folder `c2-v3c-vet1`, part `tune` of `testing/_split.json`.

| case | gold regs | run regs | reg P | reg R | reg F1 | reg F2 | page-UB P | page-UB R | page-UB F1 | page-UB F2 | gold reqs in sections | selected nodes | $ spent / replayed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ts-m1-adaptive-headlamp | R10, R148, R149, R48 | R10, R128, R149, R155, R48 | 0.60 | 0.75 | 0.67 | 0.71 | 0.32 | 0.73 | 0.45 | 0.58 | 123/157 (0.78) | 1275 | 0.00 / 0.43 |
| ts-m1-braking-system | R10, R13H, R79 | R10, R13H, R155, R156 | 0.50 | 0.67 | 0.57 | 0.62 | 0.37 | 0.71 | 0.49 | 0.60 | 139/173 (0.80) | 881 | 0.00 / 0.33 |
| ts-m1-cybersecurity-ota | R10, R155, R156 | R10, R155, R156 | 1.00 | 1.00 | 1.00 | 1.00 | 0.52 | 0.89 | 0.66 | 0.78 | 122/128 (0.95) | 424 | 0.00 / 0.27 |
| ts-m1-power-steering-b | R10, R155, R156, R79 | R10, R155, R156, R79 | 1.00 | 1.00 | 1.00 | 1.00 | 0.60 | 0.98 | 0.74 | 0.87 | 182/190 (0.96) | 538 | 0.00 / 0.33 |
| ts-m1-windscreen | R10, R43 | R43 | 1.00 | 0.50 | 0.67 | 0.56 | 0.63 | 0.57 | 0.60 | 0.58 | 131/210 (0.62) | 716 | 0.00 / 0.27 |
| ts-m3-bus-signal-lamps | R10, R148, R150, R48 | R148, R150, R48 | 1.00 | 0.75 | 0.86 | 0.79 | 0.66 | 0.83 | 0.74 | 0.79 | 190/221 (0.86) | 725 | 0.01 / 0.34 |
| ts-motorcycle-led-headlamp | R10, R128, R149, R53 | R10, R149, R53 | 1.00 | 0.75 | 0.86 | 0.79 | 0.56 | 0.82 | 0.66 | 0.75 | 202/241 (0.84) | 810 | 0.02 / 0.32 |
| ts-n1-van-rear-lamps | R10, R23, R38, R48 | R128, R148, R37, R48 | 0.25 | 0.25 | 0.25 | 0.25 | 0.11 | 0.27 | 0.16 | 0.21 | 38/151 (0.25) | 727 | 0.00 / 0.34 |
| ts-n2-truck-aebs | R10, R131, R13H | R10, R131, R155, R156 | 0.50 | 0.67 | 0.57 | 0.62 | 0.42 | 0.49 | 0.45 | 0.47 | 95/181 (0.52) | 576 | 0.00 / 0.32 |
| ts-n3-o4-coupling | R10, R102 |  | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0/122 (0.00) | 0 | 0.00 / 0.15 |
| **macro mean of 10** | | | 0.68 | 0.63 | 0.64 | 0.63 | 0.42 | 0.63 | 0.49 | 0.56 | 0.66 | 667 | 0.03 / 3.08 |
| **std of 10** | | | 0.37 | 0.31 | 0.32 | 0.31 | 0.22 | 0.30 | 0.25 | 0.27 | 0.32 | 329 |  |

New Anthropic spend of this call: $0.03.
