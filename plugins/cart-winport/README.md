# cart-winport

Will this Python script still run on a Windows build agent? `scripts/winport_check.py` reads the code for paths pinned to
the writer's machine and for text I/O that falls back to the locale codec (cp949 on Korean Windows), then runs a copy of
the script's folder from a new place under the `ko_KR.CP949` locale with the original folder made unreadable and, best
effort, the network and writes outside the moved copy denied (`sandbox-exec`). The denials cover the script's own file
writes and sockets, not work it hands to a system service or another process.

**Not a security sandbox.** The checked script runs as you and can still read your other files. Read a script before
checking it; for a script you do not trust, use `--no-run` (the static half only, reported as `UNCHECKED`). Built after a failure-first measurement (EVIDENCE.md at the repository root).

- Lanes: `python3 scripts/test_winport_check.py` (31, incl. the console lanes U2–U4 of `scripts/test_console.py`, which
  has its own `--probes` (3)) · revert probes: `--probes` (11). Q1, W1 and W2 cover the
  containment: a folder name holding a quote (it used to give a false PASS), a write outside the copy, the network.
  G1 refuses a stray `WINPORT_PROBE` outside the lane harness; U1 runs the checker on a cp949 console.
- Near-miss inputs (forge-harness `fh_module_contract.md` §2e): a non-`.py` file is refused with exit 2, `WINPORT
  UNCHECKED — NOT checked: … is <kind>` (lanes K1–K7). A refused sandbox or a missing temp folder (the checker itself
  running inside a sandbox) is `UNCHECKED`, exit 2, never a finding (lanes N1–N3). The SKILL's §4 gives the sentence
  for each kind.
- Requires: Python 3 (stdlib). The run half needs macOS (`/usr/bin/sandbox-exec`) and the `ko_KR.CP949` locale; without
  them it reports `UNCHECKED`, never a pass.
- Does not exercise: `\` separators, drive letters, file locking, antivirus, PowerShell/batch scripts.
