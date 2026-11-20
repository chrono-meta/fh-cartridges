---
name: winport
description: Use when a Python script is written or reviewed that must also run on Windows — build agents, CI runners, a Korean-Windows (cp949) machine, «it works on my Mac» — «will this run on Windows?», «why does it crash on the build agent?», «is this script portable?», «make this work on our Windows runners» — a script copies the folder elsewhere and runs it under the cp949 locale with the original folder unreadable, and reads the code for pinned machine paths and locale-codec I/O
---

# A script is not portable until it ran somewhere else

Measured before this cartridge: asked for a Python script
that runs `git log` in a repository and «runs on our Windows build agents as well as on macOS», a careful model wrote
correct UTF-8 handling in every run — and in **3 of 3 Sonnet runs** pasted the absolute macOS path it was given as the
repository location. The script passed on the Mac it was written on and died on Windows (`NotADirectoryError`). Reading
the code did not catch it; running it from another folder does.

`S=<this plugin>/scripts`

## 1. Write the script so it can move

- Paths: resolve data from `os.path.dirname(os.path.abspath(__file__))` or take them as arguments. A path you were
  **given** in the request is where the files are *today, on this machine* — do not paste it into the code.
- Text files: `encoding="utf-8"` on every text `open()`, `read_text()`, `write_text()`; `utf-8-sig` for CSV from Excel.
- Child processes: read bytes and `.decode("utf-8", "replace")`, or pass `encoding="utf-8"` with `text=True`.
- Printing: a piped stdout on Korean Windows is cp949; `sys.stdout.reconfigure(errors="replace")` (or `encoding="utf-8"`
  when the reader expects UTF-8) before printing anything outside cp949 (`é`, `ï`, emoji).

## 2. Check it — every time, before you say it works on Windows

```
python3 $S/winport_check.py check <script.py> [-- <the arguments the agent will pass>]
```

It reads the code (PINNED-PATH, LOCALE-ENCODING, LOCALE-DECODE, BOM-UNHANDLED warning) **and** runs a copy of the
script's folder from a new place under the `ko_KR.CP949` locale, `PYTHONUTF8=0`, piped stdout, under `sandbox-exec`: the
original folder is unreadable and, best effort, the network and writes outside the moved copy are denied — the
script's own sockets and file writes only, not work it hands to a system service (RELOCATED-RUN, CP949-RUN,
RUN-FAILED). Fix every `FAIL` and run it again until the
last line starts with `WINPORT PASS`. That line also names what was not exercised (§4).

- `WINPORT UNCHECKED` (no `sandbox-exec`, no `ko_KR.CP949` locale, or `--no-run`) is **not a pass**. Say which half did
  not run. Never report «works on Windows» from the static half alone.
- **The run executes the script, and it is not a security sandbox**: the script runs as the user and can still read
  the user's other files. **Read the script before you run the check.** If you did not write it and do not trust it,
  or it deletes files or needs the network, pass `--no-run` and say the run half did not run.
- A script that tries the network comes back `UNCHECKED` (the run is denied the network); a write outside the moved
  copy is a `RELOCATED-RUN` finding. A folder path holding `"` or `\` is refused (`UNCHECKED`): the sandbox profile
  cannot quote it safely.
- A `WARN` does not fail the check; mention it.
- This is a Mac-side approximation of a Windows agent (locale codec, moved folder). It does not exercise `\` path
  separators, drive letters, file locks or antivirus. When a real Windows machine is available, run it there too.

## 3. Report

One line per finding you fixed, then the checker's last line verbatim, e.g. `WINPORT PASS — checked on macOS …; not
exercised: …`. On an UNCHECKED run, quote the `UNCHECKED` line that says why, then `WINPORT UNCHECKED — not a pass`.

## 4. Outside this cartridge's definition — say so, do not pass it silently

This checks **Python scripts only**, and only what a Mac can reproduce. For a near-miss request, say the sentence below
for its kind. Do not give a result for it, and do not answer «works on Windows».

**Kinds the checker recognises from the file and refuses** (exit 2, `WINPORT UNCHECKED — NOT checked: … is <kind>`):

| kind | files | say |
|---|---|---|
| PowerShell | `.ps1`, `.psm1` | «cart-winport does not check PowerShell scripts; it is not verified for Windows. Go on without a check, or run it on a Windows machine first?» |
| batch | `.bat`, `.cmd` | «cart-winport does not check batch files; it is not verified for Windows. Go on without a check, or run it on a Windows machine first?» |
| shell script | `.sh`, `.bash`, `.zsh` | «cart-winport does not check shell scripts; it is not verified for Windows (which shell runs it there is also unchecked). Go on without a check, or check it another way?» |
| Node | `.js`, `.mjs`, `.cjs`, `.ts` | «cart-winport does not check JavaScript/TypeScript; it is not verified for Windows. Go on without a check, or check it another way?» |
| compiled | `.exe`, `.dll`, `.msi` | «cart-winport does not check compiled programs; it is not verified for Windows. Go on without a check, or run it on a Windows machine first?» |
| anything else | any other extension | «cart-winport checks Python (.py) scripts only; this file is not verified for Windows. Go on without a check, or check it another way?» |

**Kinds the checker cannot tell from the file** — the SKILL's sentence is the only guard. A `WINPORT PASS` names what it
did not exercise; read that line before you report.

- **A Python script whose Windows-only branch** (`os.name == "nt"`, `sys.platform == "win32"`) calls another file
  (`.bat`, `.ps1`, an `.exe`) or does different work: the Mac run never reaches it. Say «cart-winport checked the Python
  on macOS; the Windows-only branch at line N (it calls `<file>`) was not run, so that step is not verified for Windows.
  Go on without a check, or run it on a Windows machine first?» A `.bat`/`.ps1` it calls is one of the kinds above.
- **Windows-only failure modes**: `\` separators, drive letters, file locks, antivirus, long paths. Say «cart-winport does
  not exercise <mode>; not verified for Windows. Go on, or check it on a Windows machine?»
- **The Windows machine itself** (is Python, git or a tool installed there; which version; what PATH): say «cart-winport
  checks the script, not the build agent. Ask whoever runs the agents, or check it there.»

**When the checker cannot run here** (`UNCHECKED run not possible here: sandbox refused …`, `no writable temporary
folder`, no `ko_KR.CP949` locale): that is the environment, not the script. Say which half did not run and that the
script is not verified for Windows; never turn it into a finding or a pass. «Sandbox refused» usually means this
checker is already running inside a sandbox.
