# cart-benchcheck

Before/after performance claims, decided without a model. `scripts/bench_compare.py` takes two sample files (one number
per line, or a hyperfine `--export-json`), drops outliers by the 1.5×IQR rule, runs a two-sided Mann-Whitney U test
(exact when there are no ties and n1+n2 ≤ 40) and prints one verdict line: FASTER / SLOWER (BETTER / WORSE with
`--higher-is-better`), NO-DIFFERENCE `~`, TOO-FEW (rc 1, fewer than 5 runs on a side) or HARNESS-ERROR (rc 2).
The skill then reports only that verdict and never writes "expected" numbers in place of runs it could not make.

- Lanes: `bash scripts/test_bench_compare.sh` (known sample pairs are the answer key; p-values were cross-checked once
  against scipy.stats.mannwhitneyu, exact and asymptotic; lane B10 pins three of them).
- Evidence: EVIDENCE.md at the repository root.
- The statistics follow Go's benchstat (1.5×IQR outliers, Mann-Whitney U, `~` for no change).

## Named residuals

- The script judges the samples it is given. Whether they were measured fairly (same machine, warm-up, interleaving,
  build mode) is not visible to it; the skill asks for it, the script cannot check it.
- Several comparisons at α = 0.05 will give some false FASTER/SLOWER by chance; there is no multiple-comparison
  correction.
- A NOISE line warns at a coefficient of variation above 10%; that threshold is a convention, not calibrated.
