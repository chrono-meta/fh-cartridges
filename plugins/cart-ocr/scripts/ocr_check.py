#!/usr/bin/env python3
"""cart-ocr — engines, calibration, and machine checks on a document transcription (standard library only).

  ocr_check.py engines                      list OCR engines: OK or SKIPPED <reason>        rc 0 if one is OK, else 2
  ocr_check.py read IMAGE                   calibrate Apple Vision on the known pair, then read IMAGE -> JSON on stdout
                                            rc 0 read; rc 2 HARNESS-ERROR (engine absent, failed calibration, bad image)
  ocr_check.py pdf PDF OUTDIR               per page: text layer or OCR? writes pageN.png, pageN.layer.txt, pageN.read.json
                                            and prints one ROUTE line per page; rc 0, 1 TEXT-LAYER-DISAGREE, 2 HARNESS-ERROR
  ocr_check.py check EXTRACT.json [--engine READ.json ...] [--json]
                                            check a typed transcription; rc 0 no finding, 1 findings, 2 HARNESS-ERROR
                                            (one --engine per page for a multi-page document)

EXTRACT.json (written by the reader, one document):
  {"kind": "table", "header": [...], "rows": [[...], ...], "total_row": [...] | null}
  {"kind": "lines", "lines": [...]}
  A value that cannot be read is written with the marker [UNREADABLE] (whole cell, or the unreadable part).

Every field gets one status:
  VERIFIED     a machine check confirmed it (sum row adds up, or a calibrated second engine read the same characters)
  DISAGREE     the second engine read a different value of the same shape                      (finding)
  AMBIGUOUS    code-like token whose characters have look-alikes (I l | 1, O 0 Q D, S 5, B 8, Z 2, G 6);
               a second engine agreeing does not clear it                                     (finding)
  UNREADABLE   the reader marked it unreadable — reported as such, never filled
  UNCHECKED    no check could reach it (no engine, no sum row). Not a pass.
Document-level findings: SUM-MISMATCH, SUM-UNVERIFIABLE, STRUCTURE, TABLE-AS-LINES.
"""
import json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SWIFT_SRC = os.path.join(HERE, "vision_ocr.swift")
CALIB_IMG = os.path.join(ROOT, "fixtures", "calib.png")
CALIB_GT = os.path.join(ROOT, "fixtures", "calib.gt.txt")
CURRENCY = "₩$€£¥W"  # Vision reads ₩ as W; the symbol is not part of the number
UNREAD = re.compile(r"\[UNREADABLE\]", re.I)
CONFUSABLE = set("Il|1O0QDS5B8Z2G6")
NUM = re.compile(r"^[₩$€£¥W]?-?\d{1,3}(,\d{3})+(\.\d+)?$|^[₩$€£¥W]?-?\d+(\.\d+)?$")


class HarnessError(Exception):
    pass


def numkey(tok):
    """Comparison key for the engine check: currency symbol dropped, '.' and ',' between digits treated alike
    (the engine reads 5,404,642 as 5.404,642 or 2,079,398 as 2,079:398); also ':' and ';' between digits."""
    return re.sub(r"(?<=\d)[.:;](?=\d)", ",", ns(tok).lstrip(CURRENCY))


def ns(s):
    return re.sub(r"\s+", "", str(s or ""))


# ---------------------------------------------------------------- engines
def engine_status():
    st = {}
    if sys.platform != "darwin":
        st["apple-vision"] = "SKIPPED not macOS"
    elif not shutil.which("swift"):
        st["apple-vision"] = "SKIPPED swift not found (install Xcode command line tools)"
    else:
        st["apple-vision"] = "OK"
    st["tesseract"] = "OK" if shutil.which("tesseract") else "SKIPPED tesseract not installed"
    st["model-vision"] = "EXTERNAL the calling model reads the image itself; this script never sees it"
    return st


# Two passes of the same engine. Measured on the noisy ledger (EVIDENCE.md, cart-ocr follow-up): with Korean
# enabled only 6/38 lines reached conf >= 0.5; English-only reached 32/43 and read most amounts right. Each pass is
# calibrated on its own: the en-US pass only on the known-pair lines without Hangul.
PASSES = [("ko-KR,en-US", False), ("en-US", True)]


def run_vision(image, langs="ko-KR,en-US"):
    if engine_status()["apple-vision"] != "OK":
        raise HarnessError("apple-vision " + engine_status()["apple-vision"])
    try:
        p = subprocess.run(["swift", SWIFT_SRC, image, langs], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise HarnessError("apple-vision timed out")
    try:
        data = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise HarnessError("apple-vision gave no JSON (rc %d): %s" % (p.returncode, p.stderr.strip()[:200]))
    if p.returncode != 0 or "error" in data:
        raise HarnessError("apple-vision: %s" % data.get("error", "rc %d" % p.returncode))
    return data


def calibrate():
    """Known pair: the shipped image must read back exactly as its ground truth, or no number from the engine counts."""
    allwant = [l for l in open(CALIB_GT, encoding="utf-8").read().splitlines() if l.strip()]
    out = {"pair": os.path.basename(CALIB_IMG)}
    for langs, latin_only in PASSES:
        want = [w for w in allwant if not (latin_only and re.search(r"[가-힣]", w))]
        got_t = [ns(l["text"]) for l in run_vision(CALIB_IMG, langs)["lines"]]
        miss = [w for w in want if ns(w) not in got_t]
        if not want or miss:
            raise HarnessError("apple-vision [%s] failed calibration: %d/%d known lines not read exactly, e.g. %r"
                               % (langs, len(miss), len(want), (miss or ["no known lines"])[0]))
        out[langs] = "%d/%d exact" % (len(want), len(want))
    return out


def cmd_read(image):
    if not os.path.isfile(image):
        raise HarnessError("no such image: %s" % image)
    cal = calibrate()
    data = {"engine": "apple-vision", "lines": []}
    for langs, _ in PASSES:
        for l in run_vision(image, langs)["lines"]:
            l["pass"] = langs
            data["lines"].append(l)
    data["calibrated"] = cal
    print(json.dumps(data, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- PDF: text layer or OCR, per page
# A text layer is the PDF's own text and beats any OCR — unless it does not match the print (a stale or bad hidden OCR
# layer under a scan). So a layer is used only after the calibrated engine has read the rendered page: a layer number
# that the engine reads one character differently on that page means the layer is not the print -> TEXT-LAYER-DISAGREE,
# the page goes to OCR. No engine -> the layer is used but marked unverified, never as cross-checked.
LAYER_CROSSCHECK = True  # CHECK:pdf-layer — the revert probe sets this to False


def nums(text):
    return {numkey(t) for t in str(text).split() if len(re.findall(r"\d", numkey(t))) >= 3}


MAX_PDF_PAGES, POPPLER_TIMEOUT = 200, 120  # an untrusted PDF must not run poppler without bound


def cmd_pdf(pdf, outdir):
    if not os.path.isfile(pdf):
        raise HarnessError("no such pdf: %s" % pdf)
    miss = [t for t in ("pdfinfo", "pdftotext", "pdftoppm") if not shutil.which(t)]
    if miss:
        raise HarnessError("pdf SKIPPED: %s not found (poppler) — render the pages yourself or say the PDF was not read" % ", ".join(miss))
    pdf = os.path.abspath(pdf)  # never starts with «-», so poppler cannot read it as an option
    os.makedirs(outdir, exist_ok=True)
    info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, timeout=POPPLER_TIMEOUT).stdout
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    if not m:
        raise HarnessError("pdfinfo could not read %s" % pdf)
    if int(m.group(1)) > MAX_PDF_PAGES:
        raise HarnessError("pdf has %s pages, more than %d — split it and check the parts; NOT read" % (m.group(1), MAX_PDF_PAGES))
    try:
        cal = calibrate()
    except HarnessError as e:
        cal, why = None, str(e)
    rc = 0
    for i in range(1, int(m.group(1)) + 1):
        base = os.path.join(outdir, "page%d" % i)
        layer = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", pdf, "-"], capture_output=True, text=True,
                               timeout=POPPLER_TIMEOUT).stdout
        open(base + ".layer.txt", "w", encoding="utf-8").write(layer)
        subprocess.run(["pdftoppm", "-r", "200", "-f", str(i), "-l", str(i), "-singlefile", "-png", pdf, base], check=True,
                       timeout=POPPLER_TIMEOUT)
        eng = None
        if cal:
            eng = {"engine": "apple-vision", "lines": [], "calibrated": cal}
            for langs, _ in PASSES:
                for l in run_vision(base + ".png", langs)["lines"]:
                    l["pass"] = langs; eng["lines"].append(l)
        has_layer = len(re.sub(r"\s", "", layer)) >= 3
        if not has_layer:
            route, note = "ocr", "no text layer"
        elif eng is None:
            route, note = "text-layer-unverified", "engine UNMEASURED (%s); the layer was not compared with the print" % why
        else:
            seen = nums(" ".join(l["text"] for l in eng["lines"] if float(l.get("conf", 0)) >= 0.5))
            ln = nums(layer)
            bad = sorted((a, b) for a in ln - seen for b in seen - ln if hamming1(a, b)) if LAYER_CROSSCHECK else []
            if bad:
                route, note = "ocr", "TEXT-LAYER-DISAGREE layer vs print: " + ", ".join("%s/%s" % ab for ab in bad)
                rc = 1
            else:
                route, note = "text-layer", "layer numbers read on the print: %d/%d" % (len(ln & seen), len(ln))
        if route.startswith("text-layer"):
            rd = {"engine": "pdf-text-layer", "lines": [{"text": t, "conf": 1.0} for t in layer.splitlines() if t.strip()],
                  "calibrated": cal or {}, "route": route}
            if route == "text-layer-unverified":
                rd["calibrated"] = {}  # an unverified layer is not evidence for check --engine
        else:
            rd = eng or {"engine": "none", "lines": [], "route": route}
        rd["route"] = route
        json.dump(rd, open(base + ".read.json", "w", encoding="utf-8"), ensure_ascii=False)
        print("PAGE %d ROUTE %s — %s" % (i, route, note))
    return rc


# ---------------------------------------------------------------- checks
def to_num(s):
    t = ns(s).lstrip("₩$€£¥W")
    if not NUM.match(ns(s)) or not t:
        return None
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


CONF_LETTERS = set("IlOQDSBZG")
CONF_DIGITS = set("0125681|")


def code_like(tok):
    """A token with no language prior that mixes a look-alike letter (I l O Q D S B Z G) with a look-alike digit
    (0 1 2 5 6 8 or |): length >= 4, no run of 3+ lowercase letters, no Hangul. P-01 / A-101 do not qualify (P, A)."""
    t = UNREAD.sub("", tok).strip(".,:;()[]")
    if len(t) < 4 or re.search(r"[a-z]{3,}", t) or re.search(r"[가-힣]", t):
        return False
    return any(ch in CONF_LETTERS for ch in t) and any(ch in CONF_DIGITS for ch in t)


def fields(ex):
    """Yield (ref, value) for every field of the extract."""
    if ex.get("kind") == "table":
        for i, r in enumerate(ex.get("rows") or []):
            for k, v in enumerate(r):
                yield "r%dc%d" % (i, k), str(v)
        tr = ex.get("total_row")
        if tr:
            for k, v in enumerate(tr):
                yield "total.c%d" % k, str(v)
    else:
        for i, v in enumerate(ex.get("lines") or []):
            yield "line%d" % i, str(v)


def check_structure(ex, st, findings):
    kind = ex.get("kind")
    if kind not in ("table", "lines"):
        findings.append("STRUCTURE kind must be table or lines, got %r" % kind)
        return
    if kind == "table":
        h = ex.get("header") or []
        rows = ex.get("rows") or []
        if not h or not rows:
            findings.append("STRUCTURE table without header or rows")
        for i, r in enumerate(rows):
            if len(r) != len(h):
                findings.append("STRUCTURE r%d has %d cells, header has %d" % (i, len(r), len(h)))
        tr = ex.get("total_row")
        if tr and len(tr) != len(h):
            findings.append("STRUCTURE total row has %d cells, header has %d" % (len(tr), len(h)))


def check_table_as_lines(ex, st, findings):
    if ex.get("kind") != "lines":
        return
    rowish = [l for l in ex.get("lines") or [] if len(re.findall(r"\S+", l)) >= 3 and to_num(l.split()[-1]) is not None]
    if len(rowish) >= 3:
        findings.append("TABLE-AS-LINES %d lines end in a number after 2+ columns; transcribe as kind=table so columns and the total can be checked" % len(rowish))


def check_sum(ex, st, findings):
    if ex.get("kind") != "table" or not ex.get("total_row"):
        return
    rows = ex.get("rows") or []
    for k, tv in enumerate(ex["total_row"]):
        if UNREAD.search(str(tv)):
            continue
        tot = to_num(tv)
        if tot is None:
            continue
        col = [(i, r[k] if k < len(r) else "") for i, r in enumerate(rows)]
        bad = [i for i, v in col if UNREAD.search(str(v))]
        if bad:
            findings.append("SUM-UNVERIFIABLE c%d: rows %s unreadable, total %s cannot be checked" % (k, bad, tv))
            continue
        vals = [(i, to_num(v)) for i, v in col]
        if any(v is None for _, v in vals):
            findings.append("SUM-UNVERIFIABLE c%d: non-numeric cell in rows %s" % (k, [i for i, v in vals if v is None]))
            continue
        s = sum(v for _, v in vals)
        if abs(s - tot) > 0.005:
            cands = narrow(k, col, tv, s, tot) if NARROW else None
            if cands:
                findings.append("SUM-MISMATCH c%d: rows add to %s, total reads %s (diff %s) — one-digit misreads that would explain it: %s; re-read those first; if none is misread, re-read the whole column; if the print itself is inconsistent, report both numbers"
                                % (k, fmt(s), tv, fmt(tot - s), ", ".join(cands)))
                for ref in cands:
                    st[ref] = "SUSPECT"
            else:
                findings.append("SUM-MISMATCH c%d: rows add to %s, total reads %s (diff %s) — no single one-digit misread explains it, the whole column is SUSPECT; re-read the total and every cell of c%d; if the print itself is inconsistent, report both numbers"
                                % (k, fmt(s), tv, fmt(tot - s), k))
                for i, _ in vals:
                    st.setdefault("r%dc%d" % (i, k), "SUSPECT")
                st["total.c%d" % k] = "SUSPECT"
        else:
            for i, _ in vals:
                st["r%dc%d" % (i, k)] = "VERIFIED"
            st["total.c%d" % k] = "VERIFIED"


# Digits that print/scan alike. A sum mismatch explained by one such swap narrows SUSPECT to the cells that could hold it.
DIGIT_LOOKALIKE = {"0": "689", "1": "47", "2": "37", "3": "258", "4": "19", "5": "368", "6": "058", "7": "12",
                   "8": "03569", "9": "048"}
NARROW = True  # CHECK:narrow — the revert probe sets this to False


def one_digit_variants(text):
    """(value, lookalike?) for every string that differs from text in exactly one digit."""
    out = []
    for p, ch in enumerate(text):
        if ch.isdigit():
            for d in "0123456789":
                if d != ch:
                    v = to_num(text[:p] + d + text[p + 1:])
                    if v is not None:
                        out.append((v, d in DIGIT_LOOKALIKE[ch]))
    return out


def narrow(k, col, tv, rows_sum, tot):
    """Cells where ONE misread digit would make the column add up: the total read wrong (a variant equals the rows'
    sum) or one row read wrong (a variant moves the sum onto the total). Look-alike swaps first; if there are none,
    any one-digit change; if no cell qualifies, None (the caller marks the whole column)."""
    tiers = ([], [])
    for v, look in one_digit_variants(ns(tv)):
        if abs(v - rows_sum) < 0.005:
            tiers[0 if look else 1].append("total.c%d" % k)
    for i, cell in col:
        cur = to_num(cell)
        for v, look in one_digit_variants(ns(cell)):
            if abs(rows_sum - cur + v - tot) < 0.005:
                tiers[0 if look else 1].append("r%dc%d" % (i, k))
    for t in tiers:
        if t:
            return sorted(set(t), key=t.index)
    return None


def check_confusable(ex, st, findings, engine_text):
    for ref, v in fields(ex):
        for tok in str(v).split():
            # Engine agreement does NOT clear this: measured (follow-up O1b) the en-US pass read SDIB-I6ZI exactly as
            # the reader did, both wrong — two readers that share the font's I/l ambiguity are not independent.
            if code_like(tok):
                findings.append("AMBIGUOUS %s %r: look-alike characters — no reader can tell them apart on this print; ask for the original or a sharper image" % (ref, tok))
                st[ref] = "AMBIGUOUS"


def hamming1(a, b):
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def check_engine(ex, st, findings, engine_tokens):
    """Numbers of 3+ digits only. A reader number the engine read identically is VERIFIED. An engine number
    (confidence >= 0.5) that no reader field contains and that is one character away from exactly one reader number
    makes that reader number DISAGREE. Anything else stays UNCHECKED: no read is not a disagreement."""
    if engine_tokens is None:
        return
    reader = {}
    for ref, v in fields(ex):
        if UNREAD.search(v):
            continue
        for tok in v.split():
            t = numkey(tok)
            if len(re.findall(r"\d", t)) >= 3:
                reader.setdefault(t, []).append(ref)
    for t, refs in reader.items():
        if t in engine_tokens:
            for ref in refs:
                if st.get(ref) not in ("AMBIGUOUS", "SUSPECT"):
                    st.setdefault(ref, "VERIFIED-ENGINE")
    for e in sorted(engine_tokens):
        if e in reader or len(re.findall(r"\d", e)) < 3:
            continue
        near = [t for t in reader if hamming1(t, e)]
        if len(near) == 1:
            for ref in reader[near[0]]:
                findings.append("DISAGREE %s: reader %r, apple-vision %r — look again at this field" % (ref, near[0], e))
                st[ref] = "DISAGREE"


def fmt(x):
    return ("{:,.2f}".format(x)).rstrip("0").rstrip(".")


# Registry: the order checks run in. A revert probe deletes one line here and expects exactly its lane to go red.
CHECKS = [
    ("structure", lambda ex, st, f, et, tk: check_structure(ex, st, f)),  # CHECK:structure
    ("table-as-lines", lambda ex, st, f, et, tk: check_table_as_lines(ex, st, f)),  # CHECK:table-as-lines
    ("sum", lambda ex, st, f, et, tk: check_sum(ex, st, f)),  # CHECK:sum
    ("confusable", lambda ex, st, f, et, tk: check_confusable(ex, st, f, et)),  # CHECK:confusable
    ("engine", lambda ex, st, f, et, tk: check_engine(ex, st, f, tk)),  # CHECK:engine
]


def load_engine(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HarnessError("engine file unreadable: %s" % e)
    if not data.get("calibrated"):
        raise HarnessError("engine output has no calibration record — produce it with `ocr_check.py read`; an uncalibrated engine is not evidence")
    toks = set()
    text = []
    for l in data.get("lines", []):
        if float(l.get("conf", 0)) < 0.5:
            continue
        text.append(ns(l.get("text", "")))
        for t in str(l.get("text", "")).split():
            toks.add(numkey(t))
    return "\n".join(text), toks


def cmd_check(path, engine=None, as_json=False):
    try:
        ex = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HarnessError("extract unreadable: %s" % e)
    if not isinstance(ex, dict):
        raise HarnessError("extract must be one JSON object")
    engine_text, engine_tokens = "", None
    for e in engine or []:
        t, k = load_engine(e)
        engine_text += "\n" + t; engine_tokens = (engine_tokens or set()) | k
    st, findings = {}, []
    for _name, fn in CHECKS:
        fn(ex, st, findings, engine_text, engine_tokens)
    status = {}
    for ref, v in fields(ex):
        if UNREAD.search(v):
            status[ref] = "UNREADABLE"
        else:
            status[ref] = {"VERIFIED-ENGINE": "VERIFIED"}.get(st.get(ref), st.get(ref, "UNCHECKED"))
    counts = {}
    for s in status.values():
        counts[s] = counts.get(s, 0) + 1
    if as_json:
        print(json.dumps({"findings": findings, "fields": status, "counts": counts,
                          "engine": "apple-vision (calibrated)" if engine else "UNMEASURED no second engine"}, ensure_ascii=False, indent=1))
    else:
        for f in findings:
            print("FINDING " + f)
        if not engine:
            print("ENGINE UNMEASURED no second-engine read given; numeric fields not cross-checked")
        print("FIELDS " + " ".join("%s=%d" % kv for kv in sorted(counts.items())))
        if counts.get("UNCHECKED"):
            print("UNCHECKED %d field(s): nothing checked them — not a pass; report them as unchecked" % counts["UNCHECKED"])
        print(("FINDINGS %d" % len(findings)) if findings else "NO-FINDING (fields marked UNCHECKED were not checked by anything)")
    return 1 if findings else 0


def main(argv):
    for _s in (sys.stdout, sys.stderr):  # a cp949 (Korean Windows) or ASCII console must not turn a verdict into a crash
        try:
            _s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    try:
        if argv[0] == "engines" and len(argv) == 1:
            st = engine_status()
            for k, v in st.items():
                print("ENGINE %s %s" % (k, v))
            return 0 if any(v == "OK" for v in st.values()) else 2
        if argv[0] == "read" and len(argv) == 2:
            return cmd_read(argv[1])
        if argv[0] == "pdf" and len(argv) == 3:
            return cmd_pdf(argv[1], argv[2])
        if argv[0] == "check" and len(argv) >= 2:
            rest = argv[2:]
            eng = []
            js = "--json" in rest
            rest = [a for a in rest if a != "--json"]
            while rest[:1] == ["--engine"] and len(rest) >= 2:
                eng.append(rest[1]); rest = rest[2:]
            if rest:
                raise HarnessError("unknown arguments: %s" % rest)
            return cmd_check(argv[1], eng, js)
        raise HarnessError("usage: engines | read IMAGE | pdf PDF OUTDIR | check EXTRACT.json [--engine READ.json ...] [--json]")
    except HarnessError as e:
        print("HARNESS-ERROR " + str(e))
        return 2
    except Exception as e:  # a crash is never a finding (rc 1) and never a pass
        print("HARNESS-ERROR the checker failed (%s: %s) — NOT checked" % (e.__class__.__name__, e))
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
