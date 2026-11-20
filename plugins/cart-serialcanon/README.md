# cart-serialcanon

Serial fiction kept consistent with its canon. Three skills and one script:

- `serial-flow` — one batched intake, then a **typed canon** (glossary with `first_used` and fixed attributes,
  open decisions with `decide_by` deadlines, a foreshadowing ledger, an outline with beats per episode), then the
  episode loop. Anything the author has not decided becomes a decision entry, never a fact.
- `serial-floor-check` — runs `scripts/canon_check.py` and reports from its output.
- `serial-coldread` — a fresh reader sees only the published text and observes; observations are sorted against the
  canon afterwards (design / candidate / priority candidate, union across readers, no votes).
- `scripts/canon_check.py` — standard library only (`scripts/miniyaml.py`, vendored from cart-ghaudit). Lanes:
  K0 parse · K7 partition · K8 episode ↔ outline · K6 ledger (OVERDUE payoffs) · K9 decision deadlines ·
  K3 name used before its first episode · K11 unregistered names (candidates) · K1 author rules · K10 anchors.
  Field locations come from a schema (`canon/schema.yaml` overrides the defaults). rc 0 pass · 1 fail/pending ·
  2 HARNESS-ERROR (absence is never a pass). `--selftest` plants one defect per lane in `fixtures/serial`
  and requires exactly that lane to turn red.

Template: `fixtures/template/`. Lanes: `bash scripts/test_canon_check.sh`. Evidence: EVIDENCE.md at the repository root.

## Named residuals

- Whether an episode settles what its beat leaves open, contradicts an earlier episode in prose, or breaks a fixed
  attribute not written as a rule is **not** checked by the script; it prints that as UNMEASURED and the skills hand
  it to the reader and the author.
- K11 finds capitalised multi-word names (English). One-word names and other scripts need a `name_pattern` in the
  schema; until then they are not checked by K11 (K3 still checks registered ones).
- Exemptions are tied to a sentence hash; editing the sentence voids the exemption.
- Every fixture is invented; no story content is included.

## Versions and evidence

- **0.1.0** is the measured version: SC2 (far canon-state defects, cart 18/18 vs bare 10/18,
  SUPPORTED) and SC3 (authoring help, three arms: cart > skill-only, cart ≈ bare by the sealed rule).
- **0.1.1** adds text only, from an author's feedback round on a long serial (generalised, no story content):
  in-world labels as glossary entries with a re-gloss on return; one notation per text layer as a canon rule; an
  author-feedback sweep (classes → every episode → proposals for taste splits); a cold-read self-pass for dropped
  referents and missing time anchors. **Not re-measured.**
- Known checker noise: K11 flags capitalised question words quoted in prose («Does Ada»); exempt them in
  reviewed.tsv. A provenance lane («a character knows only what is in the in-world record») was proposed and is
  not built.
