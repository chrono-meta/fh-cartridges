#!/usr/bin/env python3
"""Lanes for winport_check.py (stdlib only).

  python3 test_winport_check.py            run every lane
  python3 test_winport_check.py --probes   revert probes: neuter one check at a time (WINPORT_PROBE=<check>) and
                                           require that exactly its own lane goes red

Each lane writes a small script into a fresh temp folder, runs the checker on it and compares rc + the codes printed.
A lane that cannot run (no ko_KR.CP949 locale, no sandbox-exec) is NOT-APPLICABLE, named, never counted as a pass.
"""
import os, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.environ.get("WINPORT_CHECK_UNDER_TEST") or os.path.join(HERE, "winport_check.py")  # override: run the lanes on another version

CLEAN = '''import json, os, subprocess, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "data.json"), encoding="utf-8") as f:
    rows = json.load(f)
out = subprocess.run(["git", "--version"], capture_output=True).stdout.decode("utf-8", "replace")
print(len(rows), "rows", "café")
'''

LANES = [
    # id, script body, extra files, args to the checker, expected rc, codes that must appear, codes that must not
    ("P1", 'import os\nREPO = "/private/tmp/somewhere/repo"\nprint(os.path.isdir(REPO))\n', {}, ["--no-run"], 1,
     ["PINNED-PATH"], []),
    ("P2", 'URL = "/api/v1/items"\nprint(URL)\n', {}, ["--no-run"], 2, [], ["PINNED-PATH"]),
    ("E1", 'data = open("data.json").read()\nprint(len(data))\n', {"data.json": "[]"}, ["--no-run"], 1,
     ["LOCALE-ENCODING"], []),
    ("E2", 'data = open("data.json", "rb").read()\nprint(len(data))\n', {"data.json": "[]"}, ["--no-run"], 2, [],
     ["LOCALE-ENCODING"]),
    ("E3", 'from pathlib import Path\nprint(Path("data.json").read_text())\n', {"data.json": "[]"}, ["--no-run"], 1,
     ["LOCALE-ENCODING"], []),
    ("D1", 'import subprocess\nprint(subprocess.run(["git","--version"], capture_output=True, text=True).stdout)\n',
     {}, ["--no-run"], 1, ["LOCALE-DECODE"], []),
    ("D2", 'import subprocess\nprint(subprocess.run(["git","--version"], capture_output=True, text=True, encoding="utf-8").stdout)\n',
     {}, ["--no-run"], 2, [], ["LOCALE-DECODE"]),
    ("B1", 'import csv\nwith open("s.csv", encoding="utf-8", newline="") as f:\n    print(list(csv.reader(f)))\n',
     {"s.csv": "a,b\n"}, ["--no-run"], 2, ["BOM-UNHANDLED"], []),
    ("B2", 'import csv\nwith open("o.csv", "w", encoding="utf-8", newline="") as f:\n    csv.writer(f).writerow(["a"])\n',
     {}, ["--no-run"], 2, [], ["BOM-UNHANDLED"]),
    ("C1", CLEAN, {"data.json": "[1,2]"}, [], 0, ["WINPORT PASS"], ["PINNED-PATH", "LOCALE-ENCODING", "LOCALE-DECODE"]),
    ("C2", CLEAN, {"data.json": "[1,2]"}, ["--no-run"], 2, ["UNCHECKED"], ["WINPORT PASS"]),
    # dynamic: a path assembled at run time escapes the static check; the relocated sandboxed run catches it
    ("R1", 'import os, sys\nREPO = os.path.join(os.sep, *sys.argv[1].split("/"))\n'
           'print(sorted(os.listdir(REPO)))\n', {"repo/a.txt": "x"}, ["--", "{ORIG}/repo"], 1, ["RELOCATED-RUN"], []),
    # dynamic: printing a character cp949 cannot encode, with no stdout reconfigure
    ("R2", 'print("caf\\u00e9 결제")\n', {}, [], 1, ["CP949-RUN"], []),
    # dynamic: reading UTF-8 Korean with the locale default (the static check is neutered by --no-static here)
    ("R3", 'print(open("k.txt").read())\n', {"k.txt": "결제 흐름\n"}, ["--no-static"], 1, ["CP949-RUN"], []),
    ("H1", 'def broken(:\n', {}, [], 2, ["HARNESS-ERROR"], ["WINPORT PASS"]),
    # environment, not the script: the checker itself runs inside another sandbox (as under a sandboxed agent runner),
    # so its own sandbox-exec is refused. That is UNCHECKED, never a finding (fh_module_contract §2e).
    ("N1", CLEAN, {"data.json": "[1,2]"}, [], 2, ["UNCHECKED", "sandbox refused"],
     ["WINPORT PASS", "RELOCATED-RUN", "WINPORT FINDINGS"], {"outer": True}),
    # same refusal, but the static half has a real finding: that finding still counts, the refusal adds nothing
    ("N2", 'import os\nREPO = "/private/tmp/somewhere/repo"\nprint(os.path.isdir(REPO))\n', {}, [], 1,
     ["PINNED-PATH", "sandbox refused"], ["RELOCATED-RUN", "WINPORT PASS"], {"outer": True}),
    # environment again: no writable temp folder for the moved copy (writes allowed only to /dev). UNCHECKED, rc 2 —
    # before the fix this was an uncaught traceback, exit 1, which reads as «found a defect».
    ("N3", CLEAN, {"data.json": "[1,2]"}, [], 2, ["UNCHECKED", "temporary folder"],
     ["WINPORT PASS", "WINPORT FINDINGS", "Traceback"], {"outer": "nowrite"}),
    # near-miss kinds the checker can tell from the input (fh_module_contract §2e): refused with exit 2, named, NOT checked.
    # The in-definition pair that must still pass is C1.
    ("K1", 'Write-Output "hi"\n', {}, [], 2, ["NOT checked", "PowerShell"], ["WINPORT PASS", "WINPORT FINDINGS"], {"name": "s.ps1"}),
    ("K2", '@echo off\r\necho hi\r\n', {}, [], 2, ["NOT checked", "batch"], ["WINPORT PASS", "WINPORT FINDINGS"], {"name": "s.bat"}),
    ("K3", '@echo off\r\necho hi\r\n', {}, [], 2, ["NOT checked", "batch"], ["WINPORT PASS", "WINPORT FINDINGS"], {"name": "s.cmd"}),
    ("K4", '#!/bin/bash\necho hi\n', {}, [], 2, ["NOT checked", "shell script"], ["WINPORT PASS", "WINPORT FINDINGS"], {"name": "s.sh"}),
    ("K5", 'console.log("hi")\n', {}, [], 2, ["NOT checked", "JavaScript"], ["WINPORT PASS", "WINPORT FINDINGS"], {"name": "s.js"}),
    ("K6", 'MZ\x90\x00', {}, [], 2, ["NOT checked", "compiled"], ["WINPORT PASS", "WINPORT FINDINGS"], {"name": "s.exe"}),
    ("K7", 'print("hi")\n', {}, [], 2, ["NOT checked", "not a recognised kind"], ["WINPORT PASS", "WINPORT FINDINGS"], {"name": "s.txt"}),
    # the run is not a security sandbox, but it is contained where it can be (2026-11-20 public-edition review, M1/L1):
    # Q1 a folder name holding a quote used to end the profile's path string early, so the original folder stayed
    #    readable and R1's failure became a false WINPORT PASS. Now refused: UNCHECKED, exit 2.
    ("Q1", 'import os, sys\nREPO = os.path.join(os.sep, *sys.argv[1].split("/"))\nprint(sorted(os.listdir(REPO)))\n',
     {"repo/a.txt": "x"}, ["--", "{ORIG}/repo"], 2, ["UNCHECKED", "quote safely"], ["WINPORT PASS", "RUN ok"],
     {"dirname": 'p") (literal "z'}),
    # W1 a write outside the moved copy is denied (it used to land): a RELOCATED-RUN finding, and the file is not there
    ("W1", 'import os, sys\nopen(os.path.join(sys.argv[1], "leak.txt"), "w", encoding="utf-8").write("x")\nprint("wrote")\n',
     {}, ["--", "{OUT}"], 1, ["RELOCATED-RUN"], ["WINPORT PASS"], {"absent": "out/leak.txt"}),
    # W2 the network is denied (a localhost listener used to accept): UNCHECKED, exit 2 — not a finding about Windows
    ("W2", 'import socket, sys\ns = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5)\ns.close()\nprint("connected")\n',
     {}, ["--", "{PORT}"], 2, ["UNCHECKED", "network"], ["WINPORT PASS", "RELOCATED-RUN"]),
    # G1 a stray WINPORT_PROBE outside the lane harness is refused (it used to turn this UNCHECKED into WINPORT PASS)
    ("G1", CLEAN, {"data.json": "[1,2]"}, ["--no-run"], 2, ["HARNESS-ERROR", "outside the lane harness"], ["WINPORT PASS"],
     {"env": {"WINPORT_PROBE": "unchecked"}, "noharness": True}),
    # U1 a cp949 console (Korean Windows, piped): the verdict prints, no crash (it used to exit 1 with a traceback)
    ("U1", CLEAN, {"data.json": "[1,2]"}, ["--no-run"], 2, ["WINPORT UNCHECKED"], ["Traceback", "WINPORT FINDINGS"],
     {"env": {"PYTHONIOENCODING": "cp949"}}),
]
PROBE_OF = {"pinned": ["P1"], "encoding": ["E1", "E3"], "decode": ["D1"], "relocate": ["R1"], "cp949": ["R2", "R3"],
            "unchecked": ["C2"], "refusal": ["N1"], "kind": ["K1", "K5"], "quote": ["Q1"], "writes": ["W1"], "net": ["W2"]}
OUTER = '(version 1)(allow default)(deny file-write* (subpath "/nonexistent-winport-lane"))'
OUTER_NOWRITE = '(version 1)(allow default)(deny file-write* (require-not (subpath "/dev")))'



def dynamic_available():
    loc = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split()
    return os.path.exists("/usr/bin/sandbox-exec") and "ko_KR.CP949" in loc


def run_lane(lane, probe=None):
    lid, body, files, args, want_rc, must, mustnot = lane[:7]
    opts = lane[7] if len(lane) > 7 else {}
    with tempfile.TemporaryDirectory(prefix="winport_lane_") as t:
        t = os.path.realpath(t)
        src = os.path.join(t, opts.get("dirname", "proj"))
        os.makedirs(src)
        out_dir = os.path.join(t, "out")
        os.makedirs(out_dir)
        lsock = socket.socket()
        lsock.bind(("127.0.0.1", 0))
        lsock.listen(4)
        name = opts.get("name", "s.py")
        with open(os.path.join(src, name), "w", encoding="utf-8") as f:
            f.write(body)
        for n, txt in files.items():
            p = os.path.join(src, n)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(txt)
        a = [x.replace("{ORIG}", src.lstrip("/")).replace("{OUT}", out_dir).replace("{PORT}", str(lsock.getsockname()[1]))
             for x in args]
        env = dict(os.environ)
        env.pop("WINPORT_PROBE", None)
        env.pop("WINPORT_TEST_HARNESS", None)
        if not opts.get("noharness"):
            env["WINPORT_TEST_HARNESS"] = "1"
        env.update(opts.get("env", {}))
        if probe:
            env["WINPORT_PROBE"] = probe
        cmd = [sys.executable, CHECK, "check", os.path.join(src, name), *a]
        if opts.get("outer"):
            cmd = ["/usr/bin/sandbox-exec", "-p", OUTER_NOWRITE if opts["outer"] == "nowrite" else OUTER, *cmd]
        try:
            p = subprocess.run(cmd, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
        finally:
            lsock.close()
        out = p.stdout + p.stderr
        ok = p.returncode == want_rc and all(m in out for m in must) and not any(m in out for m in mustnot)
        if opts.get("absent") and os.path.exists(os.path.join(t, opts["absent"])):
            ok, out = False, out + "\n    (the file %s was written)" % opts["absent"]
        return ok, p.returncode, out


def main():
    dyn = dynamic_available()
    dyn_lanes = {"C1", "R1", "R2", "R3", "H1", "N1", "N2", "N3", "Q1", "W1", "W2"}
    if "--probes" in sys.argv:
        bad = 0
        for probe, owned in PROBE_OF.items():
            reds = []
            for lane in LANES:
                if lane[0] in dyn_lanes and not dyn:
                    continue
                ok, _, _ = run_lane(lane, probe)
                if not ok:
                    reds.append(lane[0])
            want = [x for x in owned if dyn or x not in dyn_lanes]
            good = set(want) <= set(reds) and bool(want)
            print(f"{'✅' if good else '❌'} probe {probe}: red lanes {reds} (must include {want})")
            bad += not good
        print(f"winport probes: {len(PROBE_OF) - bad} passed, {bad} failed")
        return 1 if bad else 0
    passed = failed = na = 0
    for lane in LANES:
        if lane[0] in dyn_lanes and not dyn:
            print(f"➖ NOT-APPLICABLE {lane[0]} (needs sandbox-exec and the ko_KR.CP949 locale)")
            na += 1
            continue
        ok, rc, out = run_lane(lane)
        print(f"{'✅' if ok else '❌'} {lane[0]} rc={rc}" + ("" if ok else "\n    " + out.strip().replace("\n", "\n    ")))
        passed += ok
        failed += not ok
    pc = subprocess.run([sys.executable, os.path.join(HERE, "test_console.py")], capture_output=True, text=True,
                        encoding="utf-8", timeout=300)
    ok = pc.returncode == 0
    print(f"{'✅' if ok else '❌'} U2-U4 console lanes (cp949 output bytes, main() backstop, closed stdout)"
          + ("" if ok else "\n    " + pc.stdout.strip().replace("\n", "\n    ")))
    passed += ok
    failed += not ok
    print(f"winport lanes: {passed} passed, {failed} failed, {na} not applicable on this platform")
    return 1 if failed else 0


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
    sys.exit(main())
