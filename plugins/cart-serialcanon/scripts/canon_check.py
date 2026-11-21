#!/usr/bin/env python3
"""canon_check.py — floor check of a serial's canon against its episodes, without a model.

usage: canon_check.py <serial root> [--schema FILE]
       canon_check.py --selftest

The serial root holds canon files and an episodes folder. Where each field lives is read from a schema
(defaults below; <root>/canon/schema.yaml or --schema overrides any part of it). Nothing about a particular
story is built in.

Lanes (one line each: «LANE STATUS detail»):
  K0  canon-parse     every declared canon file exists and parses (duplicate keys refused); at least one episode
  K7  ep-partition    arc ranges cover 1..total with no gap or overlap; each arc's episode list matches its range
  K8  ep-parity       episode front matter (episode, arc, title, status) matches the outline; a LOCKED arc is fully approved
  K6  ledger          foreshadowing ids unique, status known, dates sane; an open item whose payoff_by is before
                      the episode being written is OVERDUE
  K9  decide-by       an unresolved decision whose decide_by is at or before the episode being written blocks it
  K3  name-order      a registered name used in an episode before its first_used episode
  K11 new-names       capitalised multi-word names not in the glossary → candidates, PENDING until registered or
                      exempted with a reason in reviewed.tsv
  K1  rules           user-declared forbidden patterns (rules.yaml «forbid»), e.g. an attribute the canon rules out
  K10 anchors         user-declared pairs of canon fields that must be equal
  --  judgment        what this script cannot decide (an episode settling what the outline leaves open, tone,
                      motivation) is printed as UNMEASURED — it goes to the cold read, never counted as a pass

«The episode being written» = the lowest-numbered episode whose status is not approved; if every episode is
approved, the next number after the last.

Exit: 0 every lane PASS · 1 a FAIL or PENDING · 2 HARNESS-ERROR (missing or unreadable input, bad schema, no
episodes). Absence is never a pass: a missing canon file is 2, not 0.
Standard library only (scripts/miniyaml.py next to this file).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import miniyaml  # noqa: E402  (ships in this folder)

DEFAULT_SCHEMA = {
    "files": {"canon": "canon/canon.yaml", "ledger": "canon/ledger.yaml", "outline": "canon/outline.yaml"},
    "optional_files": {"rules": "canon/rules.yaml"},
    "episodes": {"dir": "episodes", "pattern": r"^(\d+)\.md$"},
    "paths": {
        "total": "canon.meta.total_episodes",
        "glossary": "canon.glossary",
        "decisions": "canon.decisions",
        "ledger": "ledger.foreshadowing",
        "arcs": "outline.arcs",
    },
    "fields": {
        "name": "name", "aliases": "aliases", "first_used": "first_used",
        "decision_id": "id", "decide_by": "decide_by", "resolved": "resolved",
        "item_id": "id", "planted_at": "planted_at", "payoff_by": "payoff_by", "status": "status", "fired_at": "fired_at",
        "arc_id": "id", "arc_range": "episodes", "arc_status": "status", "arc_list": "list", "list_ep": "ep", "list_title": "title",
        "ep_number": "episode", "ep_arc": "arc", "ep_title": "title", "ep_status": "status",
    },
    "values": {
        "ledger_status": ["open", "fired"], "ledger_fired": "fired",
        "episode_status": ["draft", "approved"], "episode_approved": "approved",
        "arc_status": ["LOCKED", "PROPOSED"], "arc_locked": "LOCKED",
    },
    "name_pattern": r"(?<![\w'])(?:[A-Z][a-z]+(?:['’][A-Za-z]+)?)(?:\s+(?:[A-Z][a-z]+(?:['’][A-Za-z]+)?))+",
    "anchors": [],
}
JUDGMENT = ("an episode settling what the outline leaves open; motive, tone and voice; a beat that contradicts an "
            "earlier episode in prose — cold read and the author")


class HarnessError(Exception):
    pass


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def get(docs, dotted):
    head, *rest = dotted.split(".")
    if head not in docs:
        raise HarnessError(f"schema path {dotted}: no file named {head}")
    cur = docs[head]
    for part in rest:
        if not isinstance(cur, dict) or part not in cur:
            raise HarnessError(f"schema path {dotted}: {part} missing")
        cur = cur[part]
    return cur


def truthy(v):
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes"))


def as_int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


RANGE_RE = re.compile(r"\s*(\d+)\s*[-–]\s*(\d+)\s*")
SENTENCE_GAP = re.compile(r"(?<=[.!?\"”])\s+")


def parse_range(v):
    """«3-7» or «3–7» → (3, 7); anything else → None."""
    found = RANGE_RE.fullmatch(str(v))
    if not found:
        return None
    lo, hi = found.groups()
    return int(lo), int(hi)


def sentences(text):
    pieces = (piece.strip() for piece in SENTENCE_GAP.split(text))
    return [piece for piece in pieces if piece]


def sha(s):
    return hashlib.sha1(s.encode()).hexdigest()[:12]


class Report:
    def __init__(self):
        self.rows = []

    def add(self, lane, status, detail):
        self.rows.append((lane, status, detail))

    def lane(self, name, problems, ok_text):
        """One checked lane: red with its problems listed, or green with a one-line summary."""
        self.add(name, "FAIL" if problems else "PASS", " · ".join(problems) or ok_text)

    def show(self):
        for row in self.rows:
            print("{:<16} {:<13} {}".format(*row))

    def rc(self):
        sts = {s for _, s, _ in self.rows}
        return 2 if "HARNESS-ERROR" in sts else 1 if sts & {"FAIL", "PENDING"} else 0


def load(root, schema_path):
    sch = DEFAULT_SCHEMA
    cand = schema_path or os.path.join(root, "canon", "schema.yaml")
    if schema_path or os.path.exists(cand):
        try:
            over = miniyaml.load_yaml(open(cand, encoding="utf-8").read())
        except (OSError, ValueError, miniyaml.YamlUnsupported) as e:
            raise HarnessError(f"schema {cand}: {e}")
        if not isinstance(over, dict):
            raise HarnessError(f"schema {cand}: not a mapping")
        sch = merge(DEFAULT_SCHEMA, over)
    docs = {}
    for key, rel in list(sch["files"].items()) + list(sch["optional_files"].items()):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            if key in sch["files"]:
                raise HarnessError(f"{rel} missing")
            docs[key] = {}
            continue
        try:
            d = miniyaml.load_yaml(open(p, encoding="utf-8").read())
        except (OSError, UnicodeDecodeError, ValueError, miniyaml.YamlUnsupported) as e:
            raise HarnessError(f"{rel}: {str(e).splitlines()[0]}")
        if not isinstance(d, dict):
            raise HarnessError(f"{rel}: not a mapping")
        docs[key] = d
    epdir = os.path.join(root, sch["episodes"]["dir"])
    eps = {}
    if os.path.isdir(epdir):
        for f in sorted(os.listdir(epdir)):
            m = re.match(sch["episodes"]["pattern"], f)
            if not m:
                continue
            t = open(os.path.join(epdir, f), encoding="utf-8").read()
            parts = t.split("---", 2)
            if not t.startswith("---") or len(parts) < 3:
                raise HarnessError(f"{f}: no front matter")
            try:
                fm = miniyaml.load_yaml(parts[1]) or {}
            except (ValueError, miniyaml.YamlUnsupported) as e:
                raise HarnessError(f"{f} front matter: {e}")
            eps[int(m.group(1))] = {"fm": fm, "body": parts[2], "file": f}
    if not eps:
        raise HarnessError("no episode files — absence is not zero")
    return sch, docs, eps


def load_reviewed(root):
    p = os.path.join(root, "reviewed.tsv")
    ok = set()
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4 and not line.startswith("#") and parts[3].strip():
                ok.add((parts[0], parts[1], parts[2]))
    return ok


def run(root, schema_path=None):
    R = Report()
    try:
        sch, docs, eps = load(root, schema_path)
        F, V = sch["fields"], sch["values"]
        total = get(docs, sch["paths"]["total"])
        gloss = get(docs, sch["paths"]["glossary"]) or []
        decs = get(docs, sch["paths"]["decisions"]) or []
        ledger = get(docs, sch["paths"]["ledger"]) or []
        arcs = get(docs, sch["paths"]["arcs"]) or []
        for what, v in (("glossary", gloss), ("decisions", decs), ("ledger", ledger), ("arcs", arcs)):
            if not isinstance(v, list):
                raise HarnessError(f"{what} is not a list")
    except HarnessError as e:
        R.add("K0 canon-parse", "HARNESS-ERROR", str(e))
        R.show()
        return 2
    R.add("K0 canon-parse", "PASS", f"{len(docs)} canon files · {len(eps)} episodes · no duplicate keys")
    reviewed = load_reviewed(root)
    approved = V["episode_approved"]
    pending = [n for n in sorted(eps) if str(eps[n]["fm"].get(F["ep_status"])) != approved]
    nxt = pending[0] if pending else max(eps) + 1
    last_pub = max([n for n in eps if n < nxt], default=0)

    # K7 partition
    bad, ranges = [], {}
    for a in arcs:
        r = parse_range(a.get(F["arc_range"]))
        aid = a.get(F["arc_id"])
        if not r:
            bad.append(f"{aid}: range «{a.get(F['arc_range'])}» unreadable")
            continue
        ranges[aid] = r
        listed = sorted(as_int(x.get(F["list_ep"])) or -1 for x in (a.get(F["arc_list"]) or []))
        if listed != list(range(r[0], r[1] + 1)):
            bad.append(f"{aid}: episode list {listed} ≠ range {r[0]}-{r[1]}")
    if as_int(total) is None:
        bad.append(f"total «{total}» is not an integer")
    else:
        cursor = 1  # the episode the next arc must start at
        for aid, (lo, hi) in sorted(ranges.items(), key=lambda kv: kv[1]):
            if lo != cursor:
                bad.append(f"{aid} starts at {lo}, expected {cursor}")
            cursor = hi + 1
        if cursor != total + 1:
            bad.append(f"arcs end at {cursor - 1} ≠ total {total}")
    R.lane("K7 ep-partition", bad, f"1–{total} contiguous")

    def arc_of(n):
        return next((aid for aid, (lo, hi) in ranges.items() if lo <= n <= hi), None)
    titles = {}
    for a in arcs:
        for x in a.get(F["arc_list"]) or []:
            titles[as_int(x.get(F["list_ep"]))] = str(x.get(F["list_title"], "")).strip()

    # K8 parity
    bad = []
    for num in sorted(eps):
        name, front = eps[num]["file"], eps[num]["fm"]
        want_arc = arc_of(num)
        if as_int(front.get(F["ep_number"])) != num:
            bad.append(f"{name} episode={front.get(F['ep_number'])}")
        if str(front.get(F["ep_arc"])) != str(want_arc):
            bad.append(f"{name} arc={front.get(F['ep_arc'])} (outline: {want_arc})")
        if str(front.get(F["ep_title"], "")).strip() != titles.get(num):
            bad.append(f"{name} title «{front.get(F['ep_title'])}» ≠ outline «{titles.get(num)}»")
        if str(front.get(F["ep_status"])) not in V["episode_status"]:
            bad.append(f"{name} status «{front.get(F['ep_status'])}»")
    for a in arcs:
        st, aid = str(a.get(F["arc_status"])), a.get(F["arc_id"])
        if st not in V["arc_status"]:
            bad.append(f"{aid} status «{st}»")
        elif st == V["arc_locked"] and aid in ranges:
            lo, hi = ranges[aid]
            miss = [k for k in range(lo, hi + 1)
                    if str(((eps.get(k) or {}).get("fm") or {}).get(F["ep_status"])) != approved]
            if miss:
                bad.append(f"{aid} is {st} but episodes {miss} are missing or not approved")
    R.lane("K8 ep-parity", bad, f"{len(eps)} episodes match the outline")

    # K6 ledger
    bad, due_now = [], []
    seen_ids = set()  # ledger ids already met, to catch duplicates
    for x in ledger:
        i = x.get(F["item_id"])
        if i is None or i in seen_ids:
            bad.append(f"id {i} missing or duplicate")
        seen_ids.add(i)
        st, pa, pb, fa = x.get(F["status"]), as_int(x.get(F["planted_at"])), as_int(x.get(F["payoff_by"])), as_int(x.get(F["fired_at"]))
        if st not in V["ledger_status"]:
            bad.append(f"{i} status «{st}»")
        if pa is None or pa > last_pub:
            bad.append(f"{i} planted_at={x.get(F['planted_at'])} (published up to {last_pub})")
        if pb is None or (pa is not None and pb < pa):
            bad.append(f"{i} payoff_by={x.get(F['payoff_by'])}")
        if st == V["ledger_fired"]:
            fired_ok = fa is not None and fa <= last_pub and (pa is None or fa >= pa)
            if not fired_ok:
                bad.append(f"{i} fired_at={x.get(F['fired_at'])}")
        elif pb is not None:
            if pb < nxt:
                bad.append(f"{i} OVERDUE: payoff_by {pb}, still {st}, writing {nxt}")
            elif pb == nxt:
                due_now.append(i)
    detail = " · ".join(bad) or f"{len(ledger)} items, none overdue"
    if due_now:
        detail += f" · due in {nxt}: {due_now}"
    R.add("K6 ledger", ("PASS", "FAIL")[bool(bad)], detail)

    # K9 decide-by
    due = [f"{d.get(F['decision_id'])} (decide_by {d.get(F['decide_by'])})" for d in decs
           if as_int(d.get(F["decide_by"])) is not None and d[F["decide_by"]] <= nxt and not truthy(d.get(F["resolved"]))]
    bad_shape = [str(d.get(F["decision_id"])) for d in decs if as_int(d.get(F["decide_by"])) is None]
    blocked = bool(due or bad_shape)
    R.add("K9 decide-by", ("PASS", "FAIL")[blocked],
          (f"must be settled before writing {nxt}: {due}" if due else f"nothing blocks {nxt}")
          + (f" · decide_by not an integer: {bad_shape}" if bad_shape else ""))

    # names
    names = {}
    for g in gloss:
        nm = str(g.get(F["name"], "")).strip()
        for alias in [nm] + list(g.get(F["aliases"]) or []):
            core = re.sub(r"^(the|The)\s+", "", str(alias).strip())
            if core:
                names[core] = (nm, as_int(g.get(F["first_used"])))

    # K3 name-order
    bad = []
    for core, (nm, fu) in sorted(names.items()):
        if fu is None:
            bad.append(f"{nm}: first_used missing")
            continue
        pat = re.compile(r"(?<![\w])" + re.escape(core) + r"(?![\w])")
        early = [n for n in sorted(eps) if n < fu and pat.search(eps[n]["body"])]
        if early:
            bad.append(f"{nm} appears in {early} before first_used {fu}")
    R.lane("K3 name-order", bad, f"{len(names)} names in order")

    # K11 new-names (candidates)
    cands, ok = [], 0
    pat = re.compile(sch["name_pattern"])
    known = set(names)
    for n, e in sorted(eps.items()):
        for s in sentences(e["body"]):
            for m in pat.finditer(s):
                words = m.group(0).split()
                if m.start() == 0 or s[:m.start()].rstrip().endswith(("\"", "“")):
                    words = words[1:]  # sentence-initial capital is not evidence of a name
                if len(words) < 2:
                    continue
                cand = " ".join(words)
                if any(k == cand or k in cand or cand in k for k in known):
                    continue
                key = ("K11", e["file"], sha(s))
                if key in reviewed:
                    ok += 1
                else:
                    cands.append(f"{e['file']}: «{cand}»")
    R.add("K11 new-names", "PENDING" if cands else "PASS",
          ("not in glossary — register or exempt: " + " · ".join(sorted(set(cands)))) if cands else f"none unregistered ({ok} exempted)")

    # K1 rules
    bad, ok = [], 0
    for r in (docs.get("rules") or {}).get("forbid") or []:
        try:
            rx = re.compile(str(r.get("pattern")))
        except re.error as e:
            R.add("K1 rules", "HARNESS-ERROR", f"rule {r.get('id')}: {e}")
            R.show()
            return 2
        for n, e in sorted(eps.items()):
            if as_int(r.get("from")) and n < r["from"]:
                continue
            for s in sentences(e["body"]):
                if rx.search(s):
                    if ("K1", e["file"], sha(s)) in reviewed:
                        ok += 1
                    else:
                        bad.append(f"{r.get('id')} in {e['file']}: {r.get('why', '')}".rstrip(": "))
    nrules = len((docs.get("rules") or {}).get("forbid") or [])
    R.lane("K1 rules", bad, f"{nrules} declared rules, no hit ({ok} exempted)")

    # K10 anchors
    bad = []
    for a in sch.get("anchors") or []:
        try:
            va, vb = get(docs, a["a"]), get(docs, a["b"])
        except (HarnessError, KeyError, TypeError) as e:
            bad.append(f"anchor {a}: {e}")
            continue
        if va != vb:
            bad.append(f"{a['a']}={va} ≠ {a['b']}={vb}" + (f" ({a['why']})" if a.get("why") else ""))
    R.lane("K10 anchors", bad, f"{len(sch.get('anchors') or [])} anchors equal")

    R.add("-- judgment", "UNMEASURED", JUDGMENT)
    R.show()
    return R.rc()


# ─────────────── selftest: plant one defect at a time in the bundled fixture; only that lane may turn red ───────────────
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "serial")
MUTANTS = [
    ("K0", "canon/canon.yaml", "meta:\n", "meta:\nmeta:\n"),
    ("K7", "canon/canon.yaml", "total_episodes: 12", "total_episodes: 13"),
    ("K8", "episodes/03.md", 'title: "The Weir"', 'title: "The Dam"'),
    ("K6", "canon/ledger.yaml", "planted_at: 2, payoff_by: 11", "planted_at: 2, payoff_by: 5"),
    ("K9", "canon/canon.yaml", "decide_by: 10, resolved: false", "decide_by: 7, resolved: false"),
    ("K3", "episodes/02.md", "the mill wheel", "the mill wheel that Rufus Tarrant built"),
    ("K11", "episodes/05.md", "The orchard was quiet.", "The orchard was quiet, and Hesper Quill watched it."),
    ("K1", "episodes/06.md", "Bea Sorrel held the lantern in her left hand.", "Bea Sorrel held the lantern in her right hand."),
    ("K10", "canon/outline.yaml", 'turn: 4', 'turn: 5'),
]


RED_STATES = ("FAIL", "PENDING", "HARNESS-ERROR")


def _check_tree(root):
    """Run this checker on ROOT in a child process; return (exit code, set of lane ids that are not green)."""
    proc = subprocess.run([sys.executable, os.path.abspath(__file__), root], capture_output=True, text=True)
    lit = set()
    for row in proc.stdout.splitlines():
        cells = row.split()
        if len(cells) >= 2 and any(st in cells[1:] for st in RED_STATES):
            lit.add(cells[0])
    return proc.returncode, lit


def selftest():
    """Each mutant breaks the bundled fixture in one place. A lane earns its keep only if it alone turns red."""
    verdicts = []
    with tempfile.TemporaryDirectory() as scratch:
        clean = os.path.join(scratch, "clean")
        shutil.copytree(FIXTURE, clean)
        code, lit = _check_tree(clean)
        print(f"baseline  rc={code} red={sorted(lit) or '-'}")
        if code != 0 or lit:
            print("  the unmodified fixture is not green, so no lane can be tested — selftest FAIL")
            return 1
        for idx, (lane_id, rel, before, after) in enumerate(MUTANTS):
            tree = os.path.join(scratch, f"mutant{idx}_{lane_id}")
            shutil.copytree(clean, tree)
            target = os.path.join(tree, rel)
            with open(target, encoding="utf-8") as fh:
                body = fh.read()
            if before not in body:
                print(f"{lane_id:<4} HARNESS-ERROR  mutation target missing in {rel}")
                verdicts.append(False)
                continue
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(body.replace(before, after, 1))
            code, lit = _check_tree(tree)
            expected_code = 2 if lane_id == "K0" else 1   # K0 breaks parsing: nothing else can run
            isolated = lit == {lane_id} and code == expected_code
            verdicts.append(isolated)
            print(f"{lane_id:<4} {'discriminates' if isolated else 'BROKEN':<14} rc={code} red={sorted(lit)}")
    passed = all(verdicts)
    print("selftest", "PASS" if passed else "FAIL")
    return 0 if passed else 1


def main(argv):
    for _s in (sys.stdout, sys.stderr):  # a cp949 (Korean Windows) or ASCII console must not turn a verdict into a crash
        try:
            _s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    if argv[1:2] == ["--selftest"]:
        return selftest()
    args = argv[1:]
    schema = None
    if "--schema" in args:
        i = args.index("--schema")
        if i + 1 >= len(args):
            print("K0 canon-parse    HARNESS-ERROR --schema needs a file")
            return 2
        schema = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or not os.path.isdir(args[0]):
        print("usage: canon_check.py <serial root> [--schema FILE] | --selftest")
        return 2
    try:
        return run(args[0], schema)
    except Exception as e:  # a crash is never a finding (rc 1) and never a pass
        print(f"K0 canon-parse    HARNESS-ERROR the checker failed ({e.__class__.__name__}: {e}) — NOT checked")
        return 2


def _console_safe():
    # Same rule as the other cartridges: UTF-8 when piped, replace on a non-UTF-8 interactive console (Korean Windows).
    for s in (sys.stdout, sys.stderr):
        enc = (getattr(s, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if enc == "utf8" or not hasattr(s, "reconfigure"):
            continue
        try:
            tty = s.isatty()
        except (AttributeError, ValueError, OSError):
            tty = False
        if tty:
            s.reconfigure(errors="replace")
        else:
            s.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    _console_safe()
    sys.exit(main(sys.argv))
