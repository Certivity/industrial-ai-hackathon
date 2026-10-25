# Cheap benchmark: regulations and sections only

Every run stops after the section walks and the citation hop (`--stop-after sections`). Regulation columns are exact. Page-UB columns score `upper_bound.json` (every selected node cited once): recall is a ceiling, precision a lower bound of the real figure (`spec/finding/cheap-bench.md`). F2 = 5PR / (4P + R). Std is the sample standard deviation over cases.

Run folder `c2-v3c`, part `heldout` of `testing/_split.json`.

| case | gold regs | run regs | reg P | reg R | reg F1 | reg F2 | page-UB P | page-UB R | page-UB F1 | page-UB F2 | gold reqs in sections | selected nodes | $ spent / replayed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ts-coach-m3 | R107 | R10, R107, R43 | 0.33 | 1.00 | 0.50 | 0.71 | 0.18 | 1.00 | 0.31 | 0.53 | 108/108 (1.00) | 1113 | 0.17 / 0.22 |
| ts-ev-sound | R10, R100, R48, R51 | R10, R155, R51 | 0.67 | 0.50 | 0.57 | 0.53 | 0.35 | 0.37 | 0.36 | 0.37 | 92/212 (0.43) | 608 | 0.19 / 0.11 |
| ts-l5-tricycle-lighting | R10, R148, R150, R53 | R10, R128, R148, R150 | 0.75 | 0.75 | 0.75 | 0.75 | 0.39 | 0.73 | 0.51 | 0.62 | 158/216 (0.73) | 761 | 0.18 / 0.15 |
| ts-lpg-conversion | R10, R67, R83 | R10, R67 | 1.00 | 0.67 | 0.80 | 0.71 | 0.64 | 0.84 | 0.72 | 0.79 | 270/304 (0.89) | 1201 | 0.18 / 0.13 |
| ts-m1-airbag-module | R10, R114, R137, R79 | R114, R79 | 1.00 | 0.50 | 0.67 | 0.56 | 0.52 | 0.26 | 0.34 | 0.28 | 56/156 (0.36) | 146 | 0.21 / 0.07 |
| ts-m1-frontal-crash | R10, R137, R26, R94 | R10, R137, R155, R79, R94 | 0.60 | 0.75 | 0.67 | 0.71 | 0.33 | 0.80 | 0.46 | 0.62 | 99/134 (0.74) | 944 | 0.30 / 0.10 |
| ts-m1-lane-keeping | R10, R155, R157, R79 | R10, R155, R156, R157, R79 | 0.80 | 1.00 | 0.89 | 0.95 | 0.46 | 0.86 | 0.60 | 0.73 | 276/312 (0.88) | 1088 | 0.24 / 0.20 |
| ts-m1-replacement-catalyst | R10, R103, R83 | R103 | 1.00 | 0.33 | 0.50 | 0.38 | 0.88 | 0.14 | 0.25 | 0.17 | 38/133 (0.29) | 43 | 0.15 / 0.05 |
| ts-m3-speed-limiter-b | R10, R107, R39, R89 | R10, R155, R89 | 0.67 | 0.50 | 0.57 | 0.53 | 0.43 | 0.51 | 0.47 | 0.49 | 85/153 (0.56) | 352 | 0.19 / 0.09 |
| ts-moto-antitheft | R10, R161, R162, R163 | R10, R162, R163, R62 | 0.75 | 0.75 | 0.75 | 0.75 | 0.57 | 0.78 | 0.66 | 0.73 | 157/232 (0.68) | 485 | 0.18 / 0.15 |
| ts-motorcycle-silencer | R10, R40, R53, R92 | R92 | 1.00 | 0.25 | 0.40 | 0.29 | 1.00 | 0.14 | 0.25 | 0.17 | 37/154 (0.24) | 46 | 0.13 / 0.05 |
| ts-n1-spare-wheel | R10, R39, R64 | R64 | 1.00 | 0.33 | 0.50 | 0.38 | 0.78 | 0.17 | 0.29 | 0.21 | 37/169 (0.22) | 44 | 0.13 / 0.05 |
| ts-n1-speedometer | R10, R39 | R10, R155, R39 | 0.67 | 1.00 | 0.80 | 0.91 | 0.37 | 0.72 | 0.49 | 0.60 | 77/90 (0.86) | 290 | 0.15 / 0.13 |
| ts-n3-direction-indicators | R10, R148, R48, R6 | R10, R128, R148, R37, R48 | 0.60 | 0.75 | 0.67 | 0.71 | 0.26 | 0.75 | 0.38 | 0.54 | 159/220 (0.72) | 964 | 0.18 / 0.22 |
| ts-o3-trailer-conspicuity | R10, R104, R150, R48 | R150, R48 | 1.00 | 0.50 | 0.67 | 0.56 | 0.59 | 0.55 | 0.57 | 0.56 | 126/223 (0.56) | 539 | 0.15 / 0.16 |
| ts-pedestrian-front-end | R10, R127, R26, R42 | R10, R127, R155, R156, R26, R42, R94 | 0.57 | 1.00 | 0.73 | 0.87 | 0.23 | 0.89 | 0.36 | 0.56 | 109/125 (0.87) | 912 | 0.29 / 0.14 |
| **macro mean of 16** | | | 0.78 | 0.66 | 0.65 | 0.64 | 0.50 | 0.59 | 0.44 | 0.50 | 0.63 | 596 | 3.01 / 2.03 |
| **std of 16** | | | 0.21 | 0.26 | 0.13 | 0.19 | 0.23 | 0.29 | 0.15 | 0.20 | 0.25 | 412 |  |

New Anthropic spend of this call: $3.01.
