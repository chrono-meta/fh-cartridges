---
name: serial-flow
description: Use when helping an author plan, set up or continue a serial story (web novel, serial fiction, episodic series) — «help me plan my serial», «set up the canon for my story», «outline the first episodes», «is this episode consistent with what we decided?», «what do I still have to decide before episode N?» — runs one batched intake, writes a typed canon (glossary, open decisions with deadlines, foreshadowing ledger, outline beats) and keeps every later episode checked against it
---

# Canon first, then episodes — and never decide for the author

A serial goes wrong in two ways that cost the author many messages: the assistant asks questions one at a time,
and the assistant quietly decides things the author had not decided. This flow removes both. Questions are asked
in one batch with defaults; anything the author has not decided becomes a **decision entry with a deadline**,
never a fact in the canon.

## 1. Intake — one message, not twenty

Ask everything below **in one message**, each with a proposed default the author can accept with «ok»:

1. Premise in one or two sentences, and the planned length (number of episodes).
2. Point of view and tense.
3. Two or three works whose feel the author wants (taste anchors), and one they do **not** want.
4. Hard constraints: things that must never happen or be shown, words or registers to avoid, facts about a
   character that are fixed (an injury, an age, who knows what).
5. What the author already knows about the ending, and what they want to keep open for now.
6. Anything already written or named (characters, places) that must be kept as is.

Do not start the canon until the author has answered. If an answer is missing, use the stated default and **say
so in the canon summary**, so it can be corrected in the same review.

## 2. Write the canon — typed, not prose

<!-- cart-only --> Copy `fixtures/template/` from this cartridge into the author's serial folder and fill it in. The field names are what `scripts/canon_check.py` reads.

Whatever the format, the canon has these parts:

- **Glossary**: every named person, place, group and object, with the episode that introduces it (`first_used`)
  and the fixed facts later episodes must respect (`attrs`) — injuries, relationships, who knows what.
- **In-world labels** (a coined category, a title, a ritual name) are glossary entries too. Use only the canonical
  form; a shortened form a weekly reader cannot map back is a defect. When a label returns after several episodes,
  re-gloss it in half a sentence.
- **Decisions**: every question the author has not settled, with an id and a `decide_by` episode — the last
  episode that can be written before it must be settled. «Who did it», «does she leave», «what is in the letter».
  If you would otherwise have invented an answer, it belongs here instead.
- **Foreshadowing ledger**: each set-up with `planted_at`, `payoff_by` and status. A set-up without a payoff
  episode is not planned yet — ask.
- **Outline**: arcs with episode ranges that cover the whole serial, and for each planned episode a title and
  beats. A beat says which decisions **stay open** in that episode.
- **Constraints**: the author's hard rules from intake.
- **Notation**: when the prose has several layers (narration, speech, a character's written record, a second
  in-world writer), give each layer its own mark and record the marks as a canon rule. Two marks for four layers
  make quoted records melt into narration.
  <!-- cart-only --> Write the ones a pattern can catch into `canon/rules.yaml` (`forbid`) so the checker enforces them.

## 3. One review, one screen

Show the author a one-screen summary: premise, the arcs, episodes 1–3 beats, the glossary names, and **the list of
open decisions with their deadlines**, with the defaults you assumed marked. Ask for approval or corrections in one
reply. Then apply every correction to the canon.

When the author changes their mind about something already in the canon, change it **everywhere it lives**:
the glossary entry, every beat that depends on it, ledger items it set up, decisions it settled or opened. List the
places you changed back to the author in one line each.

## 4. Episodes

For each episode:

1. Draft from its beats. Use only registered names. If a new name is needed, add it to the glossary in the same
   step. Do not settle a decision the beat leaves open; if the scene seems to need it, ask.
2. <!-- cart-only --> Run the floor check (skill `serial-floor-check`): `python3 <this cartridge>/scripts/canon_check.py <serial folder>`. rc 1 = show every FAIL / PENDING line to the author and fix only what they choose; rc 2 = the canon or an episode cannot be read — fix that, never skip the check.
3. Check the canon's own state before the author approves: decisions whose deadline is this episode or earlier,
   ledger items whose payoff episode has passed, names used before the episode that introduces them.
4. Cold read (skill `serial-coldread`) when the author wants a reader's view.
5. Only the author approves. Mark the episode approved, record fired foreshadowing and settled decisions.

## 5. Author feedback

Group the spots the author flags into a few classes. Sweep each class through **every** episode, including ones
the author has not read yet, and show the first batch's before/after as the calibration for the rest. Where the
author's taste is split, offer a proposal, never an edit.

## Never

- Decide a plot question the author has not decided. Make it a decision entry and ask.
- Ask intake questions one at a time.
- Judge taste (is it good, is it funny) as a pass/fail; offer it as an opinion, clearly marked.
- Change approved episodes without the author asking.
