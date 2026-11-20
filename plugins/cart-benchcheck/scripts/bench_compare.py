#!/usr/bin/env python3
"""bench_compare.py — is the difference between two benchmark sample sets real? Decided without a model.

usage: bench_compare.py <before> <after> [--higher-is-better] [--alpha 0.05] [--min-effect 1.0] [--min-n 5] [--unit s]

<before> / <after>: a file with one number per line (blank lines and «#» comments ignored), or a hyperfine
`--export-json` file with exactly one result (results[0].times, seconds). A trailing unit is read: time units
(ns, us, µs, ms, s, min) are converted so «1 s» and «900 ms» compare correctly; any other unit must be the same in
both files; a file that mixes units, or units that cannot be compared, is HARNESS-ERROR.

Method (after Go's benchstat): drop outliers by the 1.5×IQR rule, compare the remaining samples with a two-sided
Mann-Whitney U test (exact when there are no ties and n1+n2 <= 40, normal approximation with tie correction
otherwise), report the change of the medians. A change is claimed only when p < alpha AND |change| >= min-effect %.

Verdict line (first line of output, exact wording):
  VERDICT: FASTER|SLOWER (... p=...)      rc 0   (BETTER|WORSE with --higher-is-better)
  VERDICT: NO-DIFFERENCE (~ ...)          rc 0   — the data does not support a change; say «no measurable change»
  VERDICT: TOO-FEW (...)                  rc 1   — fewer than --min-n samples left in a set; no verdict, get more runs
  HARNESS-ERROR: ...                      rc 2   — unreadable / empty / non-numeric input; never a verdict
"""
import json
import math
import statistics
import re
import sys

NUM = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([A-Za-zµμ%/]*)\s*$")
# time units are converted to seconds; any other unit must be the same on every line of both files
TIME = {"s": 1.0, "sec": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "μs": 1e-6, "ns": 1e-9, "m": 60.0, "min": 60.0}


class HarnessError(Exception):
    pass


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise HarnessError("cannot read %s (%s)" % (path, e.__class__.__name__))
    units = set()
    s = text.lstrip()
    if s.startswith("{"):
        try:
            j = json.loads(text)
            if len(j["results"]) != 1:
                raise HarnessError("%s has %d hyperfine results — export one command per file" % (path, len(j["results"])))
            times = j["results"][0]["times"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise HarnessError("%s looks like JSON but has no results[0].times (hyperfine --export-json)" % path)
        units.add("s")
        vals = []
        for t in times:
            if isinstance(t, bool) or not isinstance(t, (int, float)):
                raise HarnessError("%s: non-numeric entry in results[0].times" % path)
            vals.append(float(t))
    else:
        vals = []
        for i, line in enumerate(text.splitlines(), 1):
            line = line.split("#", 1)[0]
            if not line.strip():
                continue
            m = NUM.match(line)
            if not m:
                raise HarnessError("%s line %d is not a number: %r" % (path, i, line.strip()[:40]))
            vals.append(float(m.group(1)))
            units.add(m.group(2))
    if not vals:
        raise HarnessError("%s has no samples" % path)
    if any(math.isnan(v) or math.isinf(v) for v in vals):
        raise HarnessError("%s contains NaN or infinity" % path)
    return vals, units


def normalise(units, path):
    if len(units) > 1:
        raise HarnessError("%s mixes units %s — one unit per file" % (path, ", ".join(sorted(u or "none" for u in units))))


def to_common(b, ub, a, ua):
    (u1,), (u2,) = ub, ua
    if u1 == u2:
        return b, a, u1
    if u1 in TIME and u2 in TIME:
        return [x * TIME[u1] for x in b], [x * TIME[u2] for x in a], "s"
    raise HarnessError("before is in %r, after is in %r — not comparable" % (u1 or "no unit", u2 or "no unit"))


def quantile(xs, q):
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    f = pos - lo
    if xs[lo] == xs[hi] or f == 0:
        return xs[lo]
    v = xs[lo] + (xs[hi] - xs[lo]) * f
    return v if math.isfinite(v) else xs[lo] * (1 - f) + xs[hi] * f  # no overflow on huge values


def median(xs):
    return quantile(xs, 0.5)


def drop_outliers(xs):
    q1, q3 = quantile(xs, 0.25), quantile(xs, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    kept = [x for x in xs if lo <= x <= hi]
    return kept, len(xs) - len(kept)


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    r = [0.0] * len(values)
    i = 0
    ties = []
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        if j > i:
            ties.append(j - i + 1)
        i = j + 1
    return r, ties


def exact_u_cdf_two_sided(u, n1, n2):
    # number of arrangements with U statistic = k, f(n1, n2) by recursion on the largest element
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def f(a, b, k):
        if k < 0:
            return 0
        if a == 0 or b == 0:
            return 1 if k == 0 else 0
        return f(a - 1, b, k - b) + f(a, b - 1, k)

    total = math.comb(n1 + n2, n1)
    umin = min(u, n1 * n2 - u)
    p = 2.0 * sum(f(n1, n2, k) for k in range(int(math.floor(umin)) + 1)) / total
    return min(1.0, p)


def mann_whitney(a, b):
    n1, n2 = len(a), len(b)
    r, ties = ranks(a + b)
    r1 = sum(r[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    if not ties and n1 + n2 <= 40:
        return exact_u_cdf_two_sided(u1, n1, n2), "exact"
    n = n1 + n2
    mu = n1 * n2 / 2.0
    tie_term = sum(t ** 3 - t for t in ties) / (n * (n - 1)) if n > 1 else 0.0
    var = n1 * n2 / 12.0 * ((n + 1) - tie_term)
    if var <= 0:
        return 1.0, "normal (all values equal)"
    z = (abs(u1 - mu) - 0.5) / math.sqrt(var)
    z = max(z, 0.0)
    p = math.erfc(z / math.sqrt(2.0))
    return min(1.0, p), "normal+ties" if ties else "normal"


def fmt(x):
    return ("%.6g" % x)


def main(argv):
    for _s in (sys.stdout, sys.stderr):  # a cp949 (Korean Windows) or ASCII console must not turn a verdict into a crash
        try:
            _s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    args = argv[1:]
    opts = {"--alpha": 0.05, "--min-effect": 1.0, "--min-n": 5, "--unit": ""}
    higher = False
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--higher-is-better":
            higher = True
        elif a in opts:
            if i + 1 >= len(args):
                raise HarnessError("%s needs a value" % a)
            v = args[i + 1]
            try:
                opts[a] = v if a == "--unit" else (int(v) if a == "--min-n" else float(v))
            except ValueError:
                raise HarnessError("%s: not a number: %r" % (a, v))
            i += 1
        elif a.startswith("-"):
            raise HarnessError("unknown option %s" % a)
        else:
            pos.append(a)
        i += 1
    if len(pos) != 2:
        raise HarnessError("need exactly two sample files: <before> <after>")
    if not all(math.isfinite(opts[k]) for k in ("--alpha", "--min-effect")) or not (0 < opts["--alpha"] < 1) or opts["--min-effect"] < 0 or opts["--min-n"] < 2:
        raise HarnessError("alpha must be in (0,1), min-effect >= 0, min-n >= 2")
    (vb, ub), (va, ua) = load(pos[0]), load(pos[1])
    normalise(ub, pos[0]); normalise(ua, pos[1])
    before_raw, after_raw, common = to_common(vb, ub, va, ua)
    if opts["--unit"] and common and opts["--unit"] != common:
        raise HarnessError("--unit %s given, but the files are in %s — --unit only labels files without a unit" % (opts["--unit"], common))
    before, ob = drop_outliers(before_raw)
    after, oa = drop_outliers(after_raw)
    unit = (" " + opts["--unit"]) if opts["--unit"] else ((" " + common) if common else "")
    lines = []
    mb, ma = median(before), median(after)
    det = []
    det.append("before: n=%d (outliers dropped %d of %d) median=%s%s min=%s max=%s" % (len(before), ob, len(before_raw), fmt(mb), unit, fmt(min(before)), fmt(max(before))))
    det.append("after:  n=%d (outliers dropped %d of %d) median=%s%s min=%s max=%s" % (len(after), oa, len(after_raw), fmt(ma), unit, fmt(min(after)), fmt(max(after))))
    for name, xs in (("before", before), ("after", after)):
        m = statistics.fmean(xs)
        if len(xs) > 1 and m != 0 and math.isfinite(m):
            try:
                cv = abs(statistics.stdev(xs) / m) * 100  # exact arithmetic inside, no overflow
            except (OverflowError, ValueError):
                continue
            if cv > 10:
                det.append("NOISE: %s spread is %.1f%% of its mean (>10%%) — quiet the machine or add runs before trusting small changes" % (name, cv))
    if len(before) < opts["--min-n"] or len(after) < opts["--min-n"]:
        lines.append("VERDICT: TOO-FEW (need >= %d samples per set after outlier removal; have %d and %d) — no verdict; run each side more times" % (opts["--min-n"], len(before), len(after)))
        print("\n".join(lines + det))
        return 1
    if mb == 0:
        raise HarnessError("before median is 0 — a relative change is undefined")
    change = (ma - mb) / abs(mb) * 100.0
    if not all(math.isfinite(v) for v in (mb, ma, change)):
        raise HarnessError("median or change is not finite (before %r, after %r) — the samples are out of range" % (mb, ma))
    p, method = mann_whitney(before, after)
    sig = p < opts["--alpha"] and abs(change) >= opts["--min-effect"]
    if not sig:
        why = []
        if p >= opts["--alpha"]:
            why.append("p=%.3g >= alpha %.3g" % (p, opts["--alpha"]))
        if abs(change) < opts["--min-effect"]:
            why.append("|change| %.2f%% < min-effect %.2f%%" % (abs(change), opts["--min-effect"]))
        lines.append("VERDICT: NO-DIFFERENCE (~ median change %+.2f%%, %s) — say «no measurable change»; do not report the %+.2f%%" % (change, "; ".join(why), change))
    else:
        improved = (change > 0) if higher else (change < 0)
        word = ("BETTER" if improved else "WORSE") if higher else ("FASTER" if improved else "SLOWER")
        lines.append("VERDICT: %s (median %s -> %s%s, %+.2f%%, p=%.3g, Mann-Whitney %s, n=%d/%d)" % (word, fmt(mb), fmt(ma), unit, change, p, method, len(before), len(after)))
    det.append("test: Mann-Whitney U two-sided (%s), alpha=%.3g, min-effect=%.2f%%, direction: %s is better" % (method, opts["--alpha"], opts["--min-effect"], "higher" if higher else "lower"))
    print("\n".join(lines + det))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except HarnessError as e:
        print("HARNESS-ERROR: %s" % e)
        sys.exit(2)
    except Exception as e:  # never fold an internal error into a verdict
        print("HARNESS-ERROR: internal %s: %s" % (e.__class__.__name__, e))
        sys.exit(2)
