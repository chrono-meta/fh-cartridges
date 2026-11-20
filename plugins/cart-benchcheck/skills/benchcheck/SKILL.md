---
name: benchcheck
description: Use when a performance claim is about to be made or checked — «is it faster now», «did this optimisation help», «compare these benchmark runs», before/after timings, throughput or latency numbers — decides the claim with a statistics script before any number is reported
---

# A speed claim is a statistics claim

«12% faster» from one run before and one run after is a guess: repeated runs of the same code differ by that much.
So the order is fixed: **samples first, the script decides, you report its verdict.**

## 1. Get samples, not a number

- Each side (before / after) needs **at least 5 runs, 10 or more is better**, on the same machine, same input, same build mode.
  Run them interleaved where you can (before, after, before, after …) so drift hits both sides alike.
- Save one number per line, one file per side (`before.txt`, `after.txt`). A `hyperfine --export-json` file also works.
- If you cannot run the benchmark (no access, too slow, needs hardware you do not have), **say so and stop.**
  Do not write «expected» or «typical» numbers in place of measurements, and do not estimate a speedup from reading the code.

## 2. Let the script decide

```
python3 <this plugin>/scripts/bench_compare.py before.txt after.txt [--higher-is-better] [--unit ms]
```

Use `--higher-is-better` for throughput (ops/s, req/s); the default is lower-is-better (time, latency, memory).
The first line of its output is the verdict:

- `VERDICT: FASTER` / `SLOWER` (or `BETTER` / `WORSE`), rc 0: the change is real at p < 0.05 and at least 1%. Report the
  median change and the p-value from that line.
- `VERDICT: NO-DIFFERENCE (~ …)`, rc 0: the data does not show a change. Say «no measurable change». **Do not report the
  percentage** in that line as a gain or a loss, not even as «slightly faster» or «a small improvement».
- `VERDICT: TOO-FEW`, rc 1: not enough runs. Get more runs, or tell the user there is no verdict yet.
- `HARNESS-ERROR`, rc 2: the input could not be read. Fix the input. Never fall back to comparing the averages yourself.

A `NOISE:` line means the spread on one side is large. Name it next to the verdict. Do not use it to override the verdict.

## 3. Report

- Quote the verdict line exactly. Report only numbers that the script printed. For FASTER/SLOWER/BETTER/WORSE that is the
  medians, n per side and p. For NO-DIFFERENCE it is the medians and n, with no percentage given as a change. For
  TOO-FEW it is n per side. Never compute a p-value, a mean or a percentage yourself.
- Say what the percentage is a change of: «median time 100 → 50 ms (−50%)». A −50% time is not «50% faster» (that is a
  2× speedup). Do not convert between the two in your head.
- One number per claim: a reported change must come from a FASTER/SLOWER (BETTER/WORSE) verdict for that exact comparison. If you compare several
  benchmarks, run the script once per pair and report each verdict on its own line. Do not pool or average them.
- If the user's own claim disagrees with the verdict (they say faster, the script says `~`), say so plainly.

## Before you say it is done

- Every performance number you report has a script verdict behind it, and the verdict line is quoted.
- No `~` result is described as a gain or a loss.
- Missing measurements are named as missing, not filled in.

## Method

The method follows Go's benchstat (1.5×IQR outlier rule, Mann-Whitney U, `~` for no significant change). The decision is a script, the
model reports only its verdict, and missing runs are never replaced by expected numbers.
