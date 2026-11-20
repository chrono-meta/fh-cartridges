# Evidence

Each cartridge here was built only after a model without it was measured to fail at the task, and each was then measured
against that same model with the cartridge loaded. The rule that decides each verdict was written down before the runs.
All numbers are small (pilot size). They are effect sizes on the fixtures named, not rates for your data.

Terms:
- **bare** means the model without the cartridge;
- **clean runner** means a run with an empty home directory, a write sandbox and no other instructions loaded;
- **subagent arm** means the bare model ran as a subagent of a working session that had other instructions loaded.

## cart-ocr — silent wrong values

**Fixtures.** 9 generated documents (Korean and English) with exact ground truth, imitating real inputs:
- two window screenshots, light and dark;
- two re-photographed printouts, with perspective, shadow and glare;
- a noisy, date-heavy ledger;
- four PDFs: a text layer, a scan, a mixed two-page table, and a scan with a stale text layer.

The fixtures were frozen before the cartridge's last changes.

**Arms.** `claude-sonnet-5-5` on the clean runner, 3 runs per arm. Each run reads all 9 documents. The cartridge is the
version that was measured; the shipped version is reported as a secondary arm.

| | bare | with cart-ocr | shipped version (secondary) |
|---|---|---|---|
| silent errors (a wrong value with no sign of doubt) | 6 / 7 / 7 | **0 / 0 / 1** | 1 / 0 / 0 |
| wrong values | 6 / 7 / 7 | 7 / 7 / 6 | 6 / 5 / 7 |
| correct values that carry a flag (over-flagging) | 0 / 0 / 0 | 19 / 19 / 20 | 20 / 15 / 19 |

An earlier subagent-arm run on the same fixtures gave the same picture: 7 / 7 / 7 against 0 / 0 / 0.

**What it does.** It does not make the reader read better: wrong values are 20 against 20. It turns the wrong values into
flagged ones. The price is over-flagging: a sum mismatch marks several cells `SUSPECT`, and look-alike codes stay
`AMBIGUOUS` even when they are read right.

**Failure modes named.**
- Look-alike codes (`l | I 1`, `O 0`) and digit misreads that the reader cannot see.
- One remaining gap: a code read as only `|` and digits (`180-|8|1`) is not flagged as look-alike. It came back silent
  in 2 of 6 cart runs.
- The screenshots, the re-photographed invoice and all four PDFs were at ceiling in every arm, so no claim is made for
  them.

**Not measured.** Real photos and scans, handwriting, Haiku and Opus.

Requires macOS (Apple Vision) for the second engine.

## cart-serialcanon — canon state far from the draft

**Fixture.** An invented 30-episode serial with a large typed canon. Six defects are planted in episode 30. Three of them
live far from the draft:
- a foreshadowing payoff that is overdue;
- a decision whose deadline has passed;
- a name used before its introduction episode.

**Arms.** `claude-sonnet-5-5` on the clean runner, 3 runs per arm, plus 3 per arm on a clean control serial. A blind
judge scored the replies; it was first calibrated on an earlier set with known scores and agreed on 36 of 36 cells.

| | bare | with cart-serialcanon |
|---|---|---|
| planted defects found | 10 / 18 | **18 / 18** |
| far canon-state defects found | 1 / 9 | 9 / 9 |
| false canon claims on the clean control | 0 | 0 |

An earlier subagent-arm run gave the same numbers.

The checker also raised two candidate names that are quoted questions in prose. The user has to exempt them (checker
noise, named in the plugin README).

**Not measured.** Haiku, and serials in other languages. On authoring help (a separate three-arm study), the cartridge
beat the skill text alone but was about equal to the bare model.

## cart-benchcheck — «% faster» on data that shows no change

**Fixtures.** Repeated timing runs, including traps: too few runs, and data with no real change.

**Arms.** `claude-sonnet-5-5` on the clean runner, 9 trap runs and 3 control runs per arm.

| | bare | with cart-benchcheck |
|---|---|---|
| correct verdict on traps | 5 / 9 | **9 / 9** |
| a «X% faster» figure in the PR text on no-change data | 7 / 9 | **0 / 9** |
| controls | 3 / 3 | 3 / 3 |

**Head-to-head** against a public benchmark-manager skill, on the same fixtures, Sonnet, subagent arm: traps 9/9 vs 5/9, «% faster» on
a trap 1/9 vs 6/9.
- The trap gap is verdict wording: «no detectable change» against «insufficient data».
- The «% faster» gap is the failure this cartridge was built against.

**Not measured.** A false FASTER verdict: neither arm gave one on these fixtures.

## cart-winport — scripts that only run on the machine they were written on

**Task.** Write a Python script that runs `git log` and «runs on our Windows build agents as well as on macOS». The
held-out variants were not seen while the cartridge was built.

**Scoring.** Each script is run on macOS and on a Korean-locale Windows host (Python 3.12, cp949). It passes only if both
runs pass.

| arm (`claude-sonnet-5-5`, clean runner, 12 runs) | held-out WH3 | held-out WH4 | pooled |
|---|---|---|---|
| bare | 0 / 6 | 6 / 6 | 6 / 12 |
| with cart-winport | **6 / 6** | 6 / 6 | **12 / 12** |

**Failure mode named.** All 6 bare failures paste the absolute work directory they were given into the script and crash
on Windows. Reading the code did not catch this; running it from another folder does.

**Head-to-head** with ruff PLW1514 (the unspecified-encoding rule), subagent arm: 12/12 vs 7/12. Ruff does not check paths.

Requires macOS (`sandbox-exec`) for the relocated run.
