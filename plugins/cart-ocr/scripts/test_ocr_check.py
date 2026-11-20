#!/usr/bin/env python3
"""Lanes for ocr_check.py — every check has a known-positive and a known-negative; standard library only.

  python3 test_ocr_check.py            run the lanes on this plugin                      rc 0 all pass, 1 any red
  python3 test_ocr_check.py --probes   revert probes: for each machine check, a copy of the plugin with that check
                                       removed must turn exactly its own lane red and leave every other lane green

Lane groups (a probe targets one group):
  structure       L1  row with wrong cell count -> STRUCTURE; clean table -> none
  table-as-lines  L2  receipt written as lines -> TABLE-AS-LINES; prose lines -> none
  sum             L3  total off by 200 -> SUM-MISMATCH, column SUSPECT; consistent -> VERIFIED; unreadable row -> SUM-UNVERIFIABLE
  narrow          L10 total misread by one look-alike digit -> SUSPECT only on cells one digit could explain;
                      two misreads at once -> whole column SUSPECT (fallback); the narrowed list always holds the cell
  confusable      L4  SDIB-I6ZI -> AMBIGUOUS, also when the engine read it identically; P-01 / A-101 / M8 / e-mail -> none
  engine          L5  reader 7,732,648 vs engine 2,732,648 -> DISAGREE; identical -> VERIFIED; conf 0.3 line ignored;
                      ₩ vs W not a disagreement
  channel         L6  no engine -> ENGINE UNMEASURED, fields UNCHECKED never VERIFIED; [UNREADABLE] -> UNREADABLE;
                      engine file without calibration record -> rc 2
  calibration     L7  live: read on the known pair -> calibrated; a wrong known pair -> rc 2 failed calibration
                      (SKIPPED, not passed, where apple-vision is absent)
  absent-engine   L8  PATH without swift -> apple-vision SKIPPED, read -> rc 2 HARNESS-ERROR; pdf without poppler -> rc 2
  pdf-layer       L11 PDF whose invisible text layer has a number one digit off the print -> TEXT-LAYER-DISAGREE, page
                      routed to OCR, rc 1; a PDF whose layer matches the print -> ROUTE text-layer, rc 0 (live)
  pdf             L12 image-only PDF -> ROUTE ocr «no text layer»; text-layer page read is usable by check --engine (live)
  multi-engine    L13 two --engine files (two pages) -> a number read only on page 2 is VERIFIED, one off is DISAGREE
  channel         L6 also: two misreads that net to one digit -> the cell narrowing missed is UNCHECKED, never VERIFIED,
                      and the text output says UNCHECKED is not a pass
  stdlib          L9  runs under python3 -S -I
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
PY = sys.executable or "python3"

# A probe may also turn red the lanes of checks that run inside it — declared here, not tolerated silently.
DEPENDENTS = {"sum": ["narrow"], "engine": ["multi-engine", "pdf"]}  # narrowing refines a SUM-MISMATCH; multi-engine and the text-layer page read are engine comparisons

PROBES = {  # group -> (exact text to remove or replace in ocr_check.py, replacement)
    "structure": ('    ("structure", lambda ex, st, f, et, tk: check_structure(ex, st, f)),  # CHECK:structure\n', ""),
    "table-as-lines": ('    ("table-as-lines", lambda ex, st, f, et, tk: check_table_as_lines(ex, st, f)),  # CHECK:table-as-lines\n', ""),
    "sum": ('    ("sum", lambda ex, st, f, et, tk: check_sum(ex, st, f)),  # CHECK:sum\n', ""),
    "narrow": ("NARROW = True  # CHECK:narrow", "NARROW = False  # CHECK:narrow"),
    "confusable": ('    ("confusable", lambda ex, st, f, et, tk: check_confusable(ex, st, f, et)),  # CHECK:confusable\n', ""),
    "engine": ('    ("engine", lambda ex, st, f, et, tk: check_engine(ex, st, f, tk)),  # CHECK:engine\n', ""),
    "calibration": ("    cal = calibrate()\n    data = {", "    cal = {\"pair\": \"none\", \"lines\": 0, \"exact\": 0}\n    data = {"),
    "pdf-layer": ("LAYER_CROSSCHECK = True  # CHECK:pdf-layer", "LAYER_CROSSCHECK = False  # CHECK:pdf-layer"),
}


class Lanes:
    def __init__(self, plugin):
        self.plugin = plugin
        self.script = os.path.join(plugin, "scripts", "ocr_check.py")
        self.tmp = tempfile.mkdtemp()
        self.res = {}  # group -> list of (name, ok)
        self.skipped = []

    def run(self, *args, env=None, py=None):
        p = subprocess.run((py or [PY]) + [self.script] + list(args), capture_output=True, text=True, env=env, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def put(self, name, obj):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return path

    def check(self, ex, engine=None):
        args = ["check", self.put("ex.json", ex), "--json"]
        if engine is not None:
            args[3:3] = ["--engine", self.put("eng.json", engine)]
        rc, out = self.run(*args)
        try:
            return rc, json.loads(out)
        except ValueError:
            return rc, {"raw": out, "findings": [], "fields": {}}

    def lane(self, group, name, ok):
        self.res.setdefault(group, []).append((name, bool(ok)))

    @staticmethod
    def has(r, code):
        return any(f.startswith(code + " ") for f in r[1].get("findings", []))

    def all(self):
        T = {"kind": "table", "header": ["item", "qty", "amount"],
             "rows": [["a", "2", "9,000"], ["b", "1", "5,200"], ["c", "1", "6,800"]], "total_row": ["total", "", "21,000"]}
        cal = {"pair": "calib.png", "lines": 4, "exact": 4}
        # L1 structure
        bad = json.loads(json.dumps(T)); bad["rows"][1] = ["b", "1"]
        self.lane("structure", "L1+ short row -> STRUCTURE", self.has(self.check(bad), "STRUCTURE"))
        self.lane("structure", "L1- clean table -> no STRUCTURE", not self.has(self.check(T), "STRUCTURE"))
        # L2 table-as-lines
        L = {"kind": "lines", "lines": ["RECEIPT", "item qty amount", "Latte 1 5,200", "Bagel 3 9,900", "Water 2 2,400", "TOTAL 33,300"]}
        self.lane("table-as-lines", "L2+ receipt as lines -> TABLE-AS-LINES", self.has(self.check(L), "TABLE-AS-LINES"))
        P = {"kind": "lines", "lines": ["신청서 APPLICATION FORM", "성명 Name: 최윤아", "주소 Address: 마포구 월드컵로 31길 7, 302호"]}
        self.lane("table-as-lines", "L2- form lines -> none", not self.has(self.check(P), "TABLE-AS-LINES"))
        # L3 sum
        off = json.loads(json.dumps(T)); off["total_row"][2] = "21,200"
        r = self.check(off)
        self.lane("sum", "L3+ total off by 200 -> SUM-MISMATCH", self.has(r, "SUM-MISMATCH") and r[1]["fields"].get("r0c2") == "SUSPECT")
        r = self.check(T)
        self.lane("sum", "L3- consistent -> column VERIFIED, no SUM finding",
                  not self.has(r, "SUM-MISMATCH") and r[1]["fields"].get("total.c2") == "VERIFIED" and r[1]["fields"].get("r1c2") == "VERIFIED")
        un = json.loads(json.dumps(T)); un["rows"][2] = ["c", "1", "[UNREADABLE]"]
        r = self.check(un)
        self.lane("sum", "L3+ unreadable row -> SUM-UNVERIFIABLE, total not VERIFIED",
                  self.has(r, "SUM-UNVERIFIABLE") and r[1]["fields"].get("total.c2") != "VERIFIED")
        # L10 narrow
        Ld = {"kind": "table", "header": ["date", "amount"],
              "rows": [["d1", "5,404,642"], ["d2", "2,079,211"], ["d3", "7,732,648"], ["d4", "4,111,211"]], "total_row": ["sum", "19,327,212"]}
        # rows add to 19,327,712; the total's hundreds 7 was read as 2 (look-alike). -500 at the hundreds needs a row
        # hundreds digit d with d-5 a look-alike of d: rows hold 6 and 2, neither qualifies -> only the total is SUSPECT
        r = self.check(Ld)
        f = r[1]["fields"]
        self.lane("narrow", "L10+ one look-alike digit -> only the total SUSPECT, every row UNCHECKED",
                  f.get("total.c1") == "SUSPECT" and all(f.get("r%dc1" % i) == "UNCHECKED" for i in range(4)) and self.has(r, "SUM-MISMATCH"))
        two = json.loads(json.dumps(Ld)); two["rows"][2][1] = "2,732,648"  # second misread: 7 -> 2 in the millions
        r = self.check(two)
        self.lane("narrow", "L10- two misreads -> whole column SUSPECT (no narrowing claimed)",
                  all(r[1]["fields"].get("r%dc1" % i) == "SUSPECT" for i in range(4)) and r[1]["fields"].get("total.c1") == "SUSPECT")
        # L4 confusable
        C = {"kind": "lines", "lines": ["Serial", "SDIB-I6ZI"]}
        self.lane("confusable", "L4+ SDIB-I6ZI -> AMBIGUOUS", self.has(self.check(C), "AMBIGUOUS"))
        N = {"kind": "lines", "lines": ["P-01 볼트 M8 Bolt", "A-101 010-4821-7730", "yuna.choi91@example.org", "2026-09-03"]}
        self.lane("confusable", "L4- P-01 / A-101 / M8 / e-mail / date -> none", not self.has(self.check(N), "AMBIGUOUS"))
        eng_same = {"engine": "apple-vision", "calibrated": cal, "lines": [{"text": "SDIB-I6ZI", "conf": 1.0}]}
        self.lane("confusable", "L4+ second engine read it identically -> still AMBIGUOUS (shared glyph ambiguity)", self.has(self.check(C, eng_same), "AMBIGUOUS"))
        # L5 engine
        E = {"kind": "table", "header": ["date", "amount"], "rows": [["2026-09-06", "7,732,648"], ["2026-09-07", "7,361,049"]], "total_row": None}
        eng = {"engine": "apple-vision", "calibrated": cal,
               "lines": [{"text": "2026-09-06 2,732,648", "conf": 1.0}, {"text": "2026-09-07 7,361,049", "conf": 1.0}]}
        r = self.check(E, eng)
        self.lane("engine", "L5+ one digit apart -> DISAGREE on r0c1 only",
                  r[1]["fields"].get("r0c1") == "DISAGREE" and r[1]["fields"].get("r1c1") == "VERIFIED")
        same = json.loads(json.dumps(eng)); same["lines"][0]["text"] = "2026-09-06 7,732,648"
        r = self.check(E, same)
        self.lane("engine", "L5- identical -> VERIFIED, no DISAGREE", not self.has(r, "DISAGREE") and r[1]["fields"].get("r0c1") == "VERIFIED")
        low = json.loads(json.dumps(eng)); low["lines"][0]["conf"] = 0.3
        r = self.check(E, low)
        self.lane("engine", "L5- conf 0.3 engine line is no evidence -> no DISAGREE, r0c1 UNCHECKED",
                  not self.has(r, "DISAGREE") and r[1]["fields"].get("r0c1") == "UNCHECKED")
        W = {"kind": "lines", "lines": ["금액 Amount: ₩2,360,000"]}
        r = self.check(W, {"engine": "apple-vision", "calibrated": cal, "lines": [{"text": "금액 Amount: W2,360,000", "conf": 0.5}]})
        self.lane("engine", "L5- ₩ read as W -> VERIFIED, not DISAGREE", not self.has(r, "DISAGREE") and r[1]["fields"].get("line0") == "VERIFIED")
        sep = {"engine": "apple-vision", "calibrated": cal, "lines": [{"text": "2026-09-06 7.732:648", "conf": 1.0}]}
        r = self.check(E, sep)
        self.lane("engine", "L5- separators . : read for , -> VERIFIED, not DISAGREE", not self.has(r, "DISAGREE") and r[1]["fields"].get("r0c1") == "VERIFIED")
        # L6 channel
        noeng = {"kind": "lines", "lines": ["Total 1,204,869"]}
        rc, out = self.run("check", self.put("n.json", noeng))
        self.lane("channel", "L6 no engine -> ENGINE UNMEASURED, UNCHECKED, never VERIFIED",
                  "ENGINE UNMEASURED" in out and "UNCHECKED=1" in out and "VERIFIED" not in out.replace("UNMEASURED", ""))
        r = self.check(un)
        self.lane("channel", "L6 [UNREADABLE] cell -> UNREADABLE status", r[1]["fields"].get("r2c2") == "UNREADABLE")
        rc, out = self.run("check", self.put("n2.json", noeng), "--engine", self.put("u.json", {"engine": "apple-vision", "lines": []}))
        self.lane("channel", "L6 engine file without calibration -> rc 2", rc == 2 and "HARNESS-ERROR" in out)
        rc, out = self.run("check", os.path.join(self.tmp, "missing.json"))
        self.lane("channel", "L6 missing extract -> rc 2", rc == 2 and "HARNESS-ERROR" in out)
        rc, out = self.run("check", self.put("ex.json", T), "--engine",
                           self.put("eng.json", {"engine": "apple-vision", "calibrated": cal, "lines": [{"text": "9,000", "conf": "high"}]}))
        self.lane("channel", "L6 malformed engine value (a crash) -> rc 2 HARNESS-ERROR, never rc 1", rc == 2 and "HARNESS-ERROR" in out and "Traceback" not in out)
        rc8, out8 = self.run("check", self.put("ex.json", T))
        rcc, outc = self.run("check", self.put("ex.json", T), env=dict(os.environ, PYTHONIOENCODING="cp949"))
        self.lane("channel", "L6 cp949 console -> same rc as UTF-8, no crash", rcc == rc8 and "Traceback" not in outc)
        # L7 calibration (live)
        rc0, out0 = self.run("engines")
        if "apple-vision OK" not in out0:
            self.skipped.append("L7 calibration: apple-vision not available here")
        else:
            rc, out = self.run("read", os.path.join(self.plugin, "fixtures", "calib.png"))
            self.lane("calibration", "L7+ known pair reads exactly -> rc 0, calibrated", rc == 0 and '"calibrated"' in out)
            bad_plugin = os.path.join(self.tmp, "badcal")
            shutil.copytree(self.plugin, bad_plugin)
            with open(os.path.join(bad_plugin, "fixtures", "calib.gt.txt"), "a", encoding="utf-8") as f:
                f.write("THIS LINE IS NOT IN THE IMAGE 4711\n")
            p = subprocess.run([PY, os.path.join(bad_plugin, "scripts", "ocr_check.py"), "read",
                                os.path.join(self.plugin, "fixtures", "calib.png")], capture_output=True, text=True, timeout=300)
            self.lane("calibration", "L7- wrong known pair -> rc 2 failed calibration, no lines printed",
                      p.returncode == 2 and "failed calibration" in p.stdout and '"lines"' not in p.stdout)
        # L8 absent engine
        env = dict(os.environ, PATH=self.tmp)  # no swift, no tesseract
        rc, out = self.run("engines", env=env, py=[sys.executable])
        self.lane("absent-engine", "L8 no swift -> apple-vision SKIPPED, rc 2", rc == 2 and "apple-vision SKIPPED" in out)
        rc, out = self.run("read", os.path.join(self.plugin, "fixtures", "calib.png"), env=env, py=[sys.executable])
        self.lane("absent-engine", "L8 read without engine -> rc 2 HARNESS-ERROR, no JSON lines", rc == 2 and out.startswith("HARNESS-ERROR"))
        rc, out = self.run("pdf", os.path.join(self.plugin, "fixtures", "pdf_text.pdf"), os.path.join(self.tmp, "np"), env=env, py=[sys.executable])
        self.lane("absent-engine", "L8 pdf without poppler -> rc 2 HARNESS-ERROR pdf SKIPPED", rc == 2 and "pdf SKIPPED" in out)
        # L13 multi-engine
        M = {"kind": "table", "header": ["n", "amount"], "rows": [["1", "4,815,279"], ["2", "2,604,118"], ["3", "1,111,333"]], "total_row": None}
        e1 = {"engine": "apple-vision", "calibrated": cal, "lines": [{"text": "1 4,815,279", "conf": 1.0}]}
        e2 = {"engine": "apple-vision", "calibrated": cal, "lines": [{"text": "2 2,604,118", "conf": 1.0}, {"text": "3 1,111,338", "conf": 1.0}]}
        rc, out = self.run("check", self.put("m.json", M), "--engine", self.put("e1.json", e1), "--engine", self.put("e2.json", e2), "--json")
        try:
            f = json.loads(out)["fields"]
        except ValueError:
            f = {}
        self.lane("multi-engine", "L13 page-2 engine counts: r1 VERIFIED, r2 DISAGREE, r0 VERIFIED",
                  f.get("r0c1") == "VERIFIED" and f.get("r1c1") == "VERIFIED" and f.get("r2c1") == "DISAGREE")
        # L6 compound misread: 20,000 -> 18,000 and 30,000 -> 31,000 net -1,000; narrowing names r1, misses r2
        Cm = {"kind": "table", "header": ["i", "amount"], "rows": [["a", "10,000"], ["b", "18,000"], ["c", "31,000"]], "total_row": ["t", "60,000"]}
        r = self.check(Cm)
        rc, out = self.run("check", self.put("cm.json", Cm))
        self.lane("channel", "L6 two misreads netting one digit -> missed cell not VERIFIED, UNCHECKED line printed",
                  r[1]["fields"].get("r2c1") in ("UNCHECKED", "SUSPECT") and "not a pass" in out)
        # L11 / L12 pdf (live: poppler + apple-vision)
        if "apple-vision OK" not in out0 or not shutil.which("pdftotext"):
            self.skipped.append("L11/L12 pdf: poppler or apple-vision not available here")
        else:
            fx = os.path.join(self.plugin, "fixtures")
            rc, out = self.run("pdf", os.path.join(fx, "pdf_stale.pdf"), os.path.join(self.tmp, "ps"))
            self.lane("pdf-layer", "L11+ stale invisible layer -> TEXT-LAYER-DISAGREE, ROUTE ocr, rc 1",
                      rc == 1 and "TEXT-LAYER-DISAGREE" in out and "ROUTE ocr" in out)
            rc, out = self.run("pdf", os.path.join(fx, "pdf_text.pdf"), os.path.join(self.tmp, "pt"))
            self.lane("pdf-layer", "L11- matching layer -> ROUTE text-layer, rc 0", rc == 0 and "ROUTE text-layer —" in out)
            X = {"kind": "lines", "lines": ["STATEMENT 7731", "Alpha 4,815,279", "Beta 2,604,118", "Total 7,419,397"]}
            r = self.check(X, json.load(open(os.path.join(self.tmp, "pt", "page1.read.json"))))
            self.lane("pdf", "L12 text-layer page read -> check VERIFIED", r[1]["fields"].get("line1") == "VERIFIED")
            rc, out = self.run("pdf", os.path.join(fx, "pdf_scan.pdf"), os.path.join(self.tmp, "pn"))
            self.lane("pdf", "L12 image-only PDF -> ROUTE ocr no text layer, rc 0", rc == 0 and "ROUTE ocr — no text layer" in out)
        # L9 stdlib
        rc, out = self.run("check", self.put("s.json", T), py=[PY, "-S", "-I"])
        self.lane("stdlib", "L9 runs under python3 -S -I", rc == 0 and "FIELDS" in out)

    def report(self, quiet=False):
        red = sorted(g for g, ls in self.res.items() if not all(ok for _, ok in ls))
        if not quiet:
            for g, ls in self.res.items():
                for n, ok in ls:
                    print(("  ✅ " if ok else "  ❌ ") + "[%s] %s" % (g, n))
            for s in self.skipped:
                print("  ⏭  SKIPPED " + s)
            n = sum(len(ls) for ls in self.res.values()); p = sum(ok for ls in self.res.values() for _, ok in ls)
            print("LANES %d/%d pass, %d skipped (skipped is not pass)" % (p, n, len(self.skipped)))
        return red


def main():
    if "--probes" not in sys.argv:
        L = Lanes(PLUGIN); L.all()
        return 1 if L.report() else 0
    bad = 0
    for group, (old, new) in PROBES.items():
        d = tempfile.mkdtemp()
        cp = os.path.join(d, "cart-ocr")
        shutil.copytree(PLUGIN, cp)
        sp = os.path.join(cp, "scripts", "ocr_check.py")
        src = open(sp, encoding="utf-8").read()
        if src.count(old) != 1:
            print("PROBE %s: anchor not found exactly once — probe UNMEASURED" % group); bad += 1; continue
        open(sp, "w", encoding="utf-8").write(src.replace(old, new))
        L = Lanes(cp); L.all(); red = L.report(quiet=True)
        want = sorted([group] + DEPENDENTS.get(group, []))
        ok = red == want
        bad += not ok
        print("PROBE %-15s removed -> red lanes %s  %s" % (group, red or "none", ("✅ exactly its own" + (" + declared dependents" if DEPENDENTS.get(group) else "")) if ok else "❌ expected %s" % want))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
