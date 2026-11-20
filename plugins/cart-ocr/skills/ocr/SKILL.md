---
name: ocr
description: Use when text or tables are pulled out of a scanned PDF, a photo or a screenshot of a document — receipts, invoices, forms, ledgers, tables, serial or account numbers, Korean and English — «OCR this», «extract the table from this scan», «what does this receipt say?», «how much is the total on this receipt?», «is this serial number O or 0?», «read the numbers off this photo» — the reading is checked by scripts (sum row, a calibrated second engine, look-alike characters) and every field comes back VERIFIED, DISAGREE, AMBIGUOUS, UNREADABLE or UNCHECKED
---

# A number read off an image is a guess until something else agrees

Measured before this cartridge: a careful reader that was told to mark unreadable values did mark
blotted and creased cells — but on a noisy ledger it misread the printed total in 2 of 2 runs and a row amount in 1,
and on look-alike serial codes (I l | 1, O 0) it got 4 of 8 wrong in both runs, all of them **without any sign of
doubt**. So the order is fixed: **you read, the scripts check, every field carries a status, nothing unchecked is
called verified.**

`S=<this plugin>/scripts`

## 1. Which engines are here

```
python3 $S/ocr_check.py engines
```
`ENGINE apple-vision OK` (macOS, needs `swift`) · `ENGINE tesseract SKIPPED …` (not used by this version even when
installed — named so its absence is visible) · `model-vision EXTERNAL` (you). A SKIPPED engine is reported as SKIPPED
in your answer, never silently dropped.

**A PDF goes through `pdf` first**, page by page:
```
python3 $S/ocr_check.py pdf in.pdf pages/
```
One `ROUTE` line per page. `text-layer` — the PDF's own text, compared with the calibrated engine's read of the
rendered page: transcribe that page from `pages/pageN.layer.txt` (still check it against `pageN.png`). `ocr` — no text
layer, or `TEXT-LAYER-DISAGREE` (the hidden layer says a different number than the print: a stale or bad OCR layer):
read `pageN.png` like any image and say the layer was not used and why. `text-layer-unverified` — no engine to compare:
use the layer but call it unverified. `HARNESS-ERROR pdf SKIPPED` (no poppler): say the PDF was not read, or render
it some other way and say so — never guess the content. Every page's `pageN.read.json` is that page's engine file for
step 4.

## 2. You read first, into a typed file — before looking at any engine output

Open the image and write one JSON per document (`extract.json`):
- a table: `{"kind": "table", "header": [...], "rows": [[...], ...], "total_row": [...] or null}` — one cell per
  column, empty string for an empty cell, the printed total/합계 row in `total_row`. A receipt or ledger **is** a table.
- anything else: `{"kind": "lines", "lines": [...]}`.
- copy what is printed: no correcting, no computing, no reformatting digits.
- a value you cannot read is written `[UNREADABLE]` (whole cell, or the part: `010-3307-[UNREADABLE]`). Never fill a
  hidden value from context, from a sum, or from a pattern in the other rows.

## 3. Second engine, calibrated

```
python3 $S/ocr_check.py read <image> > read.json
```
It first reads a shipped known pair (`fixtures/calib.png`) and refuses (`HARNESS-ERROR … failed calibration`, rc 2)
unless every known line comes back exactly. rc 2 for any reason = the second engine is UNMEASURED: say so and go on
without `--engine`. Never treat a missing engine as agreement.

## 4. Check

```
python3 $S/ocr_check.py check extract.json --engine read.json --json
```
A document over several pages: one `--engine pages/pageN.read.json` per page, all in the same call.
- `SUM-MISMATCH`: the rows do not add up to the printed total. When one misread digit could explain the difference,
  the finding names those cells and only they are SUSPECT; re-read them first, then the rest of the column. When no
  single digit explains it, the whole column is SUSPECT. Fix a value only if you now see it differently; never edit a value to make the sum work. If the rows and
  the total really are printed inconsistently, report both numbers and say the document does not add up.
- `SUM-UNVERIFIABLE`: a row is unreadable, so the total cannot be checked — say exactly that.
- `DISAGREE`: the calibrated engine read a number one character away. Look again; if you still cannot tell, keep the
  field flagged.
- `AMBIGUOUS`: a code with look-alike characters (a second engine agreeing does not clear it: both share the print). Do not pick one; flag it and
  ask for the original or a sharper image.
- `STRUCTURE` / `TABLE-AS-LINES`: fix the shape of your file (that is not a reading change) and check again.
After any change to extract.json, run check again and use the last run.

## 5. Answer

Give the extracted text/table, then one line per field that is not VERIFIED, with its status: DISAGREE, AMBIGUOUS,
SUSPECT (in a column that failed the sum), UNREADABLE, and how many fields are UNCHECKED (nothing checked them — not a
pass). Quote the check's FIELDS line and the engine line (calibrated / SKIPPED / UNMEASURED). If asked for a single
number (the total), give it with its status, not bare.

## Not covered (say so when it matters)

Handwriting, rotated pages beyond a few degrees, multi-page reflow, and checksums of IDs (Luhn, 주민번호, IBAN) are not
checked by these scripts. A field VERIFIED by the engine means two readers agreed, not that the print is right.
