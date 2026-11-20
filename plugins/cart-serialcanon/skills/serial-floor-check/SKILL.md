---
name: serial-floor-check
description: Use when checking serial-fiction episodes against their canon files — «check episode N against my canon», «is anything overdue in my foreshadowing?», «which decisions do I have to make before the next episode?», «did I use a name before introducing it?», «how many unregistered names are there?» — runs canon_check.py first and reports only from its output, then adds what a script cannot judge
---

# The script checks the canon's structure; you check what it cannot

## 1. Run it

```
python3 <this cartridge>/scripts/canon_check.py <serial folder> [--schema FILE]
```

The folder needs `canon/canon.yaml`, `canon/ledger.yaml`, `canon/outline.yaml` and `episodes/NN.md` with front
matter (template: `fixtures/template/`). If the author's files use other field names or places, write
`canon/schema.yaml` to map them (see the script header) — **do not rename the author's fields**.

## 2. Read the exit code

- **rc 0** — every lane passed. It does not mean the episode is consistent: the `-- judgment UNMEASURED` line names
  what was not checked. Go to step 3.
- **rc 1** — show **every** FAIL and PENDING line to the author, in the script's words, before anything else:
  - K6 OVERDUE: a set-up whose payoff episode has passed. Ask: pay it off now, move `payoff_by`, or drop it?
  - K9 decide-by: a decision that must be settled before this episode. Ask the author; do not pick an answer.
  - K3 name-order: a name used before the episode that introduces it. Ask which is right.
  - K11 new-names: candidates, not verdicts. Register the name, or — if it is not a name — exempt it in
    `reviewed.tsv` with a reason (`lane<TAB>file<TAB>hash<TAB>reason`; no reason, no exemption).
  - K1 rules: an author rule was broken. Fix the text the way the author says.
  - K7 / K8 / K10: the outline, the episode files or two declared fields disagree. Ask which side is right.
- **rc 2** — the canon or an episode cannot be read. Fix the file. **Never** do the check by reading instead and
  call it passed.

## 3. Then the part no script does

Read the new episode against the outline beat and the open decisions: does it settle something the beat leaves
open? Does a character know or do something the glossary `attrs` or an earlier episode rules out? Report these as
your reading, separate from the script's findings.
