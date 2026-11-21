#!/usr/bin/env python3
"""Console-encoding lanes for winport_check.py (stdlib only). A Korean-Windows console is cp949; these lanes run the checker
under PYTHONIOENCODING=cp949 with stdout piped and read the RAW BYTES, so they see what the user's console gets.

  python3 test_console.py            lanes                                    rc 0 all pass, 1 any red
  python3 test_console.py --probes   revert probes: a temp copy of the checker with one guard removed must turn its
                                     own lane red (nothing is read from the environment)

  U2 piped cp949: the output is UTF-8 and carries the real em dash (the _console_safe guard switched the stream)
  U3 backstop: with _console_safe() not called, main()'s errors=backslashreplace still prints the verdict — no
     traceback, the same exit code, the character escaped
  U4 an already-closed stdout: _console_safe() returns quietly instead of raising (a crash would exit 1, «findings»)
"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "winport_check.py")
CALL = "    _console_safe()\n"                      # the __main__ call the U3 copy and probe «guard» remove
BACKSTOP = '            _s.reconfigure(errors="backslashreplace")\n'   # main()'s guard: probe «backstop» removes it
TRY_EXCEPT = "        except (AttributeError, ValueError, TypeError, OSError):\n"  # probe «try» neuters it
PROBES = {"guard": (CALL, "", "U2"), "backstop": (BACKSTOP, "            pass\n", "U3"),
          "try": (TRY_EXCEPT, "        except ZeroDivisionError:\n", "U4")}
# ---- per-cartridge input: args to the checker, its expected exit code, and a character cp949 cannot encode
WANT, RC = "\u2014", 2


def args(tmp):
    p = os.path.join(tmp, "s.py")
    open(p, "w", encoding="utf-8").write('print("hi")\n')
    return ["check", p, "--no-run"]   # «WINPORT UNCHECKED — not a pass»


def run(script, tmp):
    env = dict(os.environ, PYTHONIOENCODING="cp949")
    env.pop("PYTHONUTF8", None)
    p = subprocess.run([sys.executable, script] + args(tmp), capture_output=True, env=env, timeout=120,
                       stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout, p.stderr


def without(src, old, new):
    if src.count(old) != 1:
        raise SystemExit("HARNESS-ERROR test_console: %r not found exactly once in %s — the lane is stale" % (old.strip(), SCRIPT))
    return src.replace(old, new)


def lanes(script, strict=False):
    res = []
    src = open(script, encoding="utf-8").read()
    if strict:  # the real checker: every anchor the probes edit must be there exactly once, or the lanes are stale
        for old, _, _ in PROBES.values():
            without(src, old, old)
    with tempfile.TemporaryDirectory(prefix="console_lane_") as t:
        rc, out, err = run(script, t)
        try:
            text = out.decode("utf-8")
            utf8 = True
        except UnicodeDecodeError:
            text, utf8 = "", False
        res.append(("U2", rc == RC and utf8 and WANT in text and b"\\u" not in out and b"\\x" not in out))
        cp = os.path.join(t, "nocall", os.path.basename(script))
        shutil.copytree(os.path.dirname(script), os.path.dirname(cp))
        open(cp, "w", encoding="utf-8").write(src.replace(CALL, "", 1))  # a probe copy may already lack the call
        rc3, out3, err3 = run(cp, t)
        escaped = WANT.encode("unicode_escape")
        res.append(("U3", rc3 == RC and b"Traceback" not in out3 + err3 and escaped in out3))
        probe = ("import importlib.util, io, sys\n"
                 "spec = importlib.util.spec_from_file_location('m', %r)\n"
                 "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                 "w = io.TextIOWrapper(io.BytesIO(), encoding='cp949'); w.close()\n"
                 "real = sys.stdout; sys.stdout = w\n"
                 "m._console_safe()\n"
                 "sys.stdout = real; print('U4-OK')\n") % script
        p = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", timeout=60)
        res.append(("U4", p.returncode == 0 and "U4-OK" in p.stdout))
    return res


def main():
    for s in (sys.stdout, sys.stderr):  # this runner prints ✅/❌: same console rule as the checkers
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, TypeError, OSError):
            pass
    if "--probes" in sys.argv:
        src, bad = open(SCRIPT, encoding="utf-8").read(), 0
        for name, (old, new, owned) in PROBES.items():
            with tempfile.TemporaryDirectory(prefix="console_probe_") as t:
                d = os.path.join(t, "s")
                shutil.copytree(HERE, d)
                p = os.path.join(d, os.path.basename(SCRIPT))
                open(p, "w", encoding="utf-8").write(without(src, old, new))
                reds = [lid for lid, ok in lanes(p) if not ok]
            good = owned in reds
            print("%s probe %s: red lanes %s (must include %s)" % ("✅" if good else "❌", name, reds, owned))
            bad += not good
        print("console probes: %d passed, %d failed" % (len(PROBES) - bad, bad))
        return 1 if bad else 0
    res = lanes(SCRIPT, strict=True)
    for lid, ok in res:
        print("%s %s" % ("✅" if ok else "❌", lid))
    failed = sum(1 for _, ok in res if not ok)
    print("console lanes: %d passed, %d failed" % (len(res) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
