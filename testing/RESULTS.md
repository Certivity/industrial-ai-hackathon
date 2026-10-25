# Benchmark of the agent on the generated cases

Default efforts of `src/ai_agent/config.py`; the gold of each case is a DeepSeek writer's opinion (`testing/README.md`). F2 = 5PR / (4P + R). Judge F2 only where the judge ran.

| case | gold regs | run regs | n gold / run | reg P | reg R | reg F1 | reg F2 | page P | page R | page F1 | page F2 | judge F2 strict / lenient | agent $ | valid |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ts-coach-m3 | R107 | R10, R107, R43 | 108 / 476 | 0.33 | 1.00 | 0.50 | 0.71 | 0.28 | 0.90 | 0.42 | 0.62 | - | 4.79 | yes |
| ts-ev-sound | R10, R100, R48, R51 | R10, R51 | 212 / 104 | 1.00 | 0.50 | 0.67 | 0.56 | 0.76 | 0.21 | 0.33 | 0.25 | - | 2.90 | yes |
| ts-lpg-conversion | R10, R67, R83 | R10, R67 | 304 / 987 | 1.00 | 0.67 | 0.80 | 0.71 | 0.75 | 0.81 | 0.78 | 0.80 | - | 4.69 | yes |
| ts-moto-antitheft | R10, R161, R162, R163 | R10, R162, R163, R62 | 232 / 265 | 0.75 | 0.75 | 0.75 | 0.75 | 0.78 | 0.71 | 0.74 | 0.72 | 0.51 / 0.67 | 2.13 | yes |
| ts-motorcycle-silencer | R10, R40, R53, R92 | R92 | 154 / 37 | 1.00 | 0.25 | 0.40 | 0.29 | 1.00 | 0.10 | 0.18 | 0.12 | - | 0.40 | yes |
| ts-pedestrian-front-end | R10, R127, R26, R42 | R10, R127, R26, R42 | 125 / 127 | 1.00 | 1.00 | 1.00 | 1.00 | 0.67 | 0.57 | 0.62 | 0.59 | 0.34 / 0.55 | 2.46 | yes |
| **mean of 6** | | | | 0.85 | 0.69 | 0.69 | 0.67 | 0.71 | 0.55 | 0.51 | 0.52 | | 17.36 | |

Total agent spend counted: $18.10 of $27.00.
