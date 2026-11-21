#!/usr/bin/env python3
"""winport_check.py — will this Python script still run on a Windows build agent? (stdlib only)

  winport_check.py check SCRIPT.py [--no-run] [--no-static] [-- ARGS...]

Two independent checks:
  static   (AST) PINNED-PATH      a string literal that is an absolute machine path (/Users/…, /private/…, /tmp/…, C:\\…)
                 LOCALE-ENCODING  open() / io.open() / Path.read_text() / Path.write_text() in text mode with no encoding=
                 LOCALE-DECODE    subprocess run/check_output/Popen/call with text=True (or universal_newlines) and no
                                  encoding= — the output is decoded with the locale codec (cp949 on Korean Windows)
                 BOM-UNHANDLED    (warning) csv read through encoding="utf-8": an Excel CSV starts with a BOM
  run      the script's folder is copied to a new place and run there under the ko_KR.CP949 locale with PYTHONUTF8=0
           and piped stdout (what a Korean-Windows agent does by default), under sandbox-exec: the ORIGINAL folder is
           unreadable, and (best effort) the network and writes outside the moved copy's temp folder are denied. Those
           denials cover the script's own file writes and sockets; work the script hands to a system service or
           another process (open, osascript, defaults) is not covered.
           🟥 This is NOT a security sandbox: the script still runs as you and can read the rest of your files. Read an
           untrusted script before running it, or use --no-run. A path that still points at the original folder, or a
           locale-codec read/print, fails the run:
                 RELOCATED-RUN    the run failed reaching the original folder (or writing any path outside the copy)
                 CP949-RUN        UnicodeEncodeError / UnicodeDecodeError under the cp949 locale
                 RUN-FAILED       any other non-zero exit
  Missing sandbox-exec or the ko_KR.CP949 locale, or --no-run: the run is UNCHECKED, never a pass. So is an environment
  failure of the run itself: sandbox-exec refused (this checker already runs inside a sandbox), or no writable temporary
  folder for the moved copy, a folder path the sandbox profile cannot quote safely (" \\ or a control character), or
  a script that tried to reach the network. Those are not findings about the script.
  Near-miss inputs (fh_module_contract §2e): any file that is not .py is refused, its kind named, exit 2, NOT checked.
  A pass names what it did not exercise (Windows-only branches and the files they call, \\ separators, drive letters …).

Exit: 0 WINPORT PASS (both checks ran, no finding) · 1 WINPORT FINDINGS · 2 WINPORT UNCHECKED or HARNESS-ERROR.
WINPORT_PROBE=<pinned|encoding|decode|relocate|cp949|unchecked|refusal|kind|quote|writes|net> neuters one check (revert probes in the lanes).
"""
import ast, os, re, shutil, subprocess, sys, tempfile

# Revert probes for the lanes. Honoured only when the lane harness also sets WINPORT_TEST_HARNESS=1; a stray
# WINPORT_PROBE in the environment (an .envrc, a CI variable) is refused, never silently applied.
_HARNESS = os.environ.get("WINPORT_TEST_HARNESS") == "1"
PROBE = os.environ.get("WINPORT_PROBE", "") if _HARNESS else ""
PROBE_REFUSED = "" if _HARNESS else os.environ.get("WINPORT_PROBE", "")
ABS_PATH = re.compile(r"^(/(Users|private|tmp|home|var|opt|Volumes|mnt|root|srv)/|[A-Za-z]:\\\\?)")
SUBPROC = {"run", "check_output", "Popen", "call", "check_call"}
# Near-miss kinds the checker can tell from the input (fh_module_contract §2e). Anything not .py is refused with exit 2.
KINDS = {".ps1": "a PowerShell script", ".psm1": "a PowerShell module", ".bat": "a batch file", ".cmd": "a batch file",
         ".sh": "a shell script", ".bash": "a shell script", ".zsh": "a shell script",
         ".js": "a JavaScript (Node) file", ".mjs": "a JavaScript (Node) file", ".cjs": "a JavaScript (Node) file",
         ".ts": "a TypeScript (Node) file", ".exe": "a compiled program", ".dll": "a compiled library",
         ".msi": "a compiled installer"}
# A sandbox profile is text: a folder name holding " or \ could end the quoted path and append its own rules (a false
# PASS). Such a path is refused, never escaped by hand.
UNQUOTABLE = re.compile(r'["\\\x00-\x1f\x7f]')
NOT_EXERCISED = ("Windows-only branches (os.name == 'nt', sys.platform == 'win32') and any file they call, "
                 "\\ separators, drive letters, file locks, antivirus")


def kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def is_true(node):
    return isinstance(node, ast.Constant) and node.value is True


def static_findings(tree):
    out = []
    doc_ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                doc_ids.add(id(first.value))
    uses_csv = any(isinstance(n, ast.Name) and n.id == "csv" for n in ast.walk(tree))
    sub_names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "subprocess":
            sub_names |= {a.asname or a.name for a in n.names if a.name in SUBPROC}
    for n in ast.walk(tree):
        if PROBE != "pinned" and isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids:
            if ABS_PATH.match(n.value):
                out.append(("FAIL", "PINNED-PATH", n.lineno,
                            f"{n.value!r} — resolve it from __file__ or an argument; this path exists only on the machine that wrote it"))
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None
        # open() / io.open()
        if PROBE != "encoding" and ((isinstance(f, ast.Name) and fname == "open") or (fname == "open" and owner == "io")):
            mode = n.args[1] if len(n.args) > 1 else kw(n, "mode")
            binary = isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value
            unknown_mode = mode is not None and not isinstance(mode, ast.Constant)
            enc = kw(n, "encoding") or (n.args[3] if len(n.args) > 3 else None)
            if not binary and not unknown_mode and enc is None:
                out.append(("FAIL", "LOCALE-ENCODING", n.lineno,
                            "open() in text mode without encoding= — reads/writes cp949 on Korean Windows"))
            reading = mode is None or (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                                       and not any(c in mode.value for c in "wax"))
            if uses_csv and reading and isinstance(enc, ast.Constant) and str(enc.value).lower().replace("_", "-") in ("utf-8", "utf8"):
                out.append(("WARN", "BOM-UNHANDLED", n.lineno,
                            "csv through encoding='utf-8': an Excel export starts with a BOM, use 'utf-8-sig'"))
        if PROBE != "encoding" and fname in ("read_text", "write_text") and isinstance(f, ast.Attribute):
            if kw(n, "encoding") is None and not (fname == "read_text" and n.args):
                out.append(("FAIL", "LOCALE-ENCODING", n.lineno, f".{fname}() without encoding="))
        # subprocess.X(..., text=True) without encoding
        if PROBE != "decode" and fname in SUBPROC and (owner == "subprocess" or (isinstance(f, ast.Name) and fname in sub_names)):
            texty = is_true(kw(n, "text")) or is_true(kw(n, "universal_newlines"))
            if texty and kw(n, "encoding") is None:
                out.append(("FAIL", "LOCALE-DECODE", n.lineno,
                            "text=True without encoding= — child output is decoded with the locale codec (cp949)"))
    return out


def dynamic_ready():
    if not os.path.exists("/usr/bin/sandbox-exec"):
        return "no /usr/bin/sandbox-exec (macOS only)"
    loc = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split()
    if "ko_KR.CP949" not in loc:
        return "no ko_KR.CP949 locale"
    return None


def sandbox_profile(orig_dir, t):
    rules = ["(version 1)", "(allow default)"]
    if PROBE != "net":
        rules.append("(deny network*)")
    if PROBE != "writes":
        rules.append(f'(deny file-write* (require-not (require-any (subpath "{t}") (subpath "/dev"))))')
    rules.append(f'(deny file-read* file-write* (subpath "{orig_dir}"))')
    return "".join(rules)


def run_relocated(script, args):
    orig_dir = os.path.realpath(os.path.dirname(os.path.abspath(script)))
    if PROBE != "quote" and UNQUOTABLE.search(orig_dir):
        return [], "", ("run not possible here: the script's folder path contains a character the sandbox profile "
                        "cannot quote safely (\" or \\ or a control character) — rename the folder, or use --no-run")
    try:
        tmp = tempfile.TemporaryDirectory(prefix="winport_run_")
    except OSError as e:
        return [], "", f"run not possible here: no writable temporary folder for the moved copy ({e.__class__.__name__})"
    with tmp as t:
        t = os.path.realpath(t)
        if t == orig_dir or t.startswith(orig_dir + os.sep):
            return [], "", ("run not possible here: the temporary folder is inside the script's folder, so the copy "
                            "would copy itself and fall under the original-folder deny")
        if UNQUOTABLE.search(t):
            return [], "", "run not possible here: the temporary folder path cannot be quoted safely in the sandbox profile"
        copy_dir = os.path.join(t, "agent", os.path.basename(orig_dir) or "proj")
        try:
            shutil.copytree(orig_dir, copy_dir, symlinks=True)
        except OSError as e:
            return [], "", f"run not possible here: could not copy the script's folder ({e.__class__.__name__})"
        copy_script = os.path.join(copy_dir, os.path.basename(script))
        cargs = [a.replace(orig_dir, copy_dir) if a.startswith(orig_dir) else a for a in args]
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin", "HOME": t, "TMPDIR": t + "/",
               "PYTHONUTF8": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        if PROBE != "cp949":
            env.update({"LC_ALL": "ko_KR.CP949", "LANG": "ko_KR.CP949"})
        else:
            env.update({"LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"})
        cmd = [sys.executable, copy_script, *cargs]
        if PROBE != "relocate":
            profile = sandbox_profile(orig_dir, t)
            cmd = ["/usr/bin/sandbox-exec", "-p", profile, *cmd]
        else:
            cmd = [sys.executable, script, *args]
            copy_dir = orig_dir
        try:
            p = subprocess.run(cmd, cwd=copy_dir, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            return [("FAIL", "RUN-FAILED", 0, "timeout after 120 s")], "", None
        err = p.stderr.decode("utf-8", "replace")
        tail = " | ".join(l.strip() for l in err.strip().splitlines()[-2:])[:300]
        # sandbox-exec refused before the script started (rc 71, sandbox_apply): this checker is itself running inside
        # a sandbox. That is the environment, not the script — UNCHECKED, never a RELOCATED-RUN finding.
        if PROBE != "refusal" and cmd[0] == "/usr/bin/sandbox-exec" and err.lstrip().startswith("sandbox-exec:"):
            return [], "", ("run not possible here: sandbox refused (sandbox-exec could not start — is this checker "
                            f"already running inside a sandbox?): {tail}")
        if p.returncode == 0:
            return [], f"RUN ok rc=0 (copied to a new folder, ko_KR.CP949 locale, PYTHONUTF8=0, piped stdout, original folder unreadable)", None
        if PROBE != "net" and re.search(r"socket|urllib|http\.client|requests|ssl", err) and \
                re.search(r"Operation not permitted|Errno 1\]|gaierror|nodename nor servname", err):
            return [], "", ("run blocked: the script tried to reach the network, which this check denies — the run half "
                            f"is not verified (read the script; if it must use the network, use --no-run): {tail}")
        if re.search(r"Unicode(En|De)codeError", err):
            return [("FAIL", "CP949-RUN", 0, f"rc={p.returncode}: {tail}")], "", None
        if orig_dir in err or re.search(r"Operation not permitted|NotADirectoryError|FileNotFoundError|No such file", err):
            return [("FAIL", "RELOCATED-RUN", 0, f"rc={p.returncode}: {tail}")], "", None
        return [("FAIL", "RUN-FAILED", 0, f"rc={p.returncode}: {tail}")], "", None


def check(script, no_run, no_static, args):
    if not os.path.isfile(script):
        print(f"HARNESS-ERROR no such file: {script} — NOT checked")
        return 2
    ext = os.path.splitext(script)[1].lower()
    if ext != ".py":
        kind = KINDS.get(ext, "not a recognised kind") if PROBE != "kind" else "a non-Python file"
        print(f"WINPORT UNCHECKED — NOT checked: {script} is {kind}; cart-winport checks Python (.py) scripts only. "
              "Not verified for Windows.")
        return 2
    try:
        src = open(script, encoding="utf-8").read()
        tree = ast.parse(src, filename=script)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"HARNESS-ERROR cannot parse {script}: {e}")
        return 2
    findings, unchecked = [], []
    if no_static:
        unchecked.append("static check skipped (--no-static)")
    else:
        findings += static_findings(tree)
    if no_run:
        unchecked.append("run skipped (--no-run)")
    else:
        why = dynamic_ready()
        if why:
            unchecked.append(f"run not possible here: {why}")
        else:
            f2, note, env_fail = run_relocated(script, args)
            findings += f2
            if note:
                print(note)
            if env_fail:
                unchecked.append(env_fail)
    for sev, code, line, msg in findings:
        print(f"{sev} {code}" + (f" line {line}" if line else "") + f": {msg}")
    for u in unchecked:
        print(f"UNCHECKED {u}")
    fails = [f for f in findings if f[0] == "FAIL"]
    if fails:
        print(f"WINPORT FINDINGS ({len(fails)})")
        return 1
    if unchecked and PROBE != "unchecked":
        print("WINPORT UNCHECKED — not a pass")
        return 2
    print(f"WINPORT PASS — checked on macOS (moved folder, cp949 locale); not exercised: {NOT_EXERCISED}")
    return 0


def main(argv):
    for _s in (sys.stdout, sys.stderr):  # a cp949 (Korean Windows) or ASCII console must not turn a verdict into a crash
        try:
            _s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    if PROBE_REFUSED:
        print("HARNESS-ERROR WINPORT_PROBE=%s is set outside the lane harness; it would weaken the check. Unset it. "
              "NOT checked" % PROBE_REFUSED)
        return 2
    if PROBE:
        print("PROBE ACTIVE: %s - this result is a lane-harness result, not a check" % PROBE, file=sys.stderr)
    if len(argv) < 2 or argv[0] != "check":
        print(__doc__)
        return 2
    rest = argv[1:]
    args = []
    if "--" in rest:
        i = rest.index("--")
        rest, args = rest[:i], rest[i + 1:]
    flags = {x for x in rest if x.startswith("--")}
    pos = [x for x in rest if not x.startswith("--")]
    if len(pos) != 1 or flags - {"--no-run", "--no-static"}:
        print("HARNESS-ERROR usage: winport_check.py check SCRIPT.py [--no-run] [--no-static] [-- ARGS...]")
        return 2
    try:
        return check(pos[0], "--no-run" in flags, "--no-static" in flags, args)
    except Exception as e:  # a crash of the checker is never a finding (exit 1) and never a pass
        print(f"HARNESS-ERROR the checker failed ({e.__class__.__name__}: {e}) — NOT checked")
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
    sys.exit(main(sys.argv[1:]))
