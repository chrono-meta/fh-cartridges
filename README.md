# fh-cartridges

Claude Code plugins («cartridges») that each put a script where a model without them was measured to fail. The model
still does the work; a script decides the part it gets wrong silently, and the result carries a typed status instead of
a confident sentence.

| cartridge | what the script decides | measured (details in [EVIDENCE.md](EVIDENCE.md)) |
|---|---|---|
| [cart-ocr](plugins/cart-ocr) | OCR of scans, photos and screenshots: sum row, calibrated second engine, look-alike characters, a status per field | silent wrong values 6 / 7 / 7 → 0 / 0 / 1 |
| [cart-serialcanon](plugins/cart-serialcanon) | serial fiction against a typed canon: overdue foreshadowing, passed decision deadlines, names used too early | planted defects 10 / 18 → 18 / 18 |
| [cart-benchcheck](plugins/cart-benchcheck) | before/after benchmark claims: outliers, Mann-Whitney U, `~` for no change | «% faster» on no-change data 7 / 9 → 0 / 9 |
| [cart-winport](plugins/cart-winport) | Python scripts for Windows build agents: pinned machine paths, locale-codec I/O, a relocated run under cp949 | held-out scripts 6 / 12 → 12 / 12 |

All numbers are pilot-sized. The numbers in this table were measured with `claude-sonnet-5-5` on a clean runner (no
other instructions loaded), on the fixtures named in EVIDENCE.md. EVIDENCE.md also
lists what each cartridge does not do and what was not measured.

## Install

```
claude plugin marketplace add chrono-meta/fh-cartridges
claude plugin install cart-benchcheck@fh-cartridges
```

Each skill describes when it applies, so after installing you ask in plain words («is it faster now?», «will this run on
our Windows build agents?»). Each plugin's README has its lanes (self-tests) and its named residuals.

## Requirements

- Python 3 (standard library only).
- cart-ocr's second engine and cart-winport's relocated run need macOS. Without it they report `SKIPPED` or `UNCHECKED`,
  never a pass.
- cart-ocr's PDF route needs poppler, called as an external program.

## forge-harness

The cartridges follow the module contract of [forge-harness](https://github.com/chrono-meta/forge-harness), which can
admit, load and measure them. They also work as ordinary Claude Code plugins without it.

## License

MIT, see [LICENSE](LICENSE). Idea sources: [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).
