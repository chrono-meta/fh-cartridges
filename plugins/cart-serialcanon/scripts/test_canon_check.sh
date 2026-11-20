#!/usr/bin/env bash
# Lanes for canon_check.py. The bundled fixture (fixtures/serial) is the known-good side; --selftest plants one
# defect per lane and requires that lane, and only it, to turn red. The rest pin absence and exemption behaviour.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; C="$HERE/canon_check.py"; FX="$HERE/../fixtures/serial"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
pass=0; fail=0; ok(){ pass=$((pass+1)); echo "  ✅ $1"; }; bad(){ fail=$((fail+1)); echo "  ❌ $1"; printf '%s\n' "$out" | sed 's/^/     /'; }

out=$(python3 "$C" "$FX" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "L1 fixture green rc 0" || bad "L1 rc=$rc"
out=$(python3 "$C" --selftest 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$(printf '%s\n' "$out" | grep -c discriminates)" -eq 9 ] && ok "L2 selftest: 9 lanes discriminate" || bad "L2 rc=$rc"

cp -R "$FX" "$W/a"; rm "$W/a/canon/ledger.yaml"
out=$(python3 "$C" "$W/a" 2>&1); rc=$?
[ $rc -eq 2 ] && printf '%s\n' "$out" | grep -q "HARNESS-ERROR" && ok "L3 missing canon file → rc 2, not a pass" || bad "L3 rc=$rc"

cp -R "$FX" "$W/b"; rm "$W/b/episodes/"*.md
out=$(python3 "$C" "$W/b" 2>&1); rc=$?
[ $rc -eq 2 ] && ok "L4 zero episodes → rc 2" || bad "L4 rc=$rc"

cp -R "$FX" "$W/c"; python3 - "$W/c/episodes/05.md" <<'PY'
import sys; p=sys.argv[1]; t=open(p).read(); open(p,"w").write(t.replace("The orchard was quiet.","The orchard was quiet, and Hesper Quill watched it.",1))
PY
out=$(python3 "$C" "$W/c" 2>&1); rc=$?
[ $rc -eq 1 ] && printf '%s\n' "$out" | grep -q "Hesper Quill" && ok "L5 unregistered name → PENDING rc 1" || bad "L5 rc=$rc"
h=$(python3 -c "import hashlib;print(hashlib.sha1('The orchard was quiet, and Hesper Quill watched it.'.encode()).hexdigest()[:12])")
printf 'K11\t05.md\t%s\t\n' "$h" > "$W/c/reviewed.tsv"
out=$(python3 "$C" "$W/c" 2>&1); rc=$?
[ $rc -eq 1 ] && ok "L6 exemption without a reason is not an exemption" || bad "L6 rc=$rc"
printf 'K11\t05.md\t%s\ta passer-by, never named again\n' "$h" > "$W/c/reviewed.tsv"
out=$(python3 "$C" "$W/c" 2>&1); rc=$?
[ $rc -eq 0 ] && printf '%s\n' "$out" | grep -q "1 exempted" && ok "L7 exemption with a reason → rc 0, counted" || bad "L7 rc=$rc"

cp -R "$FX" "$W/d"; printf 'files: {canon: canon/missing.yaml}\n' > "$W/d/canon/schema.yaml"
out=$(python3 "$C" "$W/d" 2>&1); rc=$?
[ $rc -eq 2 ] && ok "L8 schema pointing at a missing file → rc 2" || bad "L8 rc=$rc"

cp -R "$FX" "$W/e"; sed -i.bak 's/status: draft/status: approved/' "$W/e/episodes/08.md"
out=$(python3 "$C" "$W/e" 2>&1); rc=$?
[ $rc -eq 0 ] && printf '%s\n' "$out" | grep -q "nothing blocks 9" && ok "L9 all approved → the episode being written is the next number" || bad "L9 rc=$rc"

cp -R "$FX" "$W/f"; python3 -c "import sys;open(sys.argv[1],'w').write('entries: '+'['*5000+']'*5000+'\\n')" "$W/f/canon/ledger.yaml"
out=$(python3 "$C" "$W/f" 2>&1); rc=$?
[ $rc -eq 2 ] && printf '%s\n' "$out" | grep -q "HARNESS-ERROR" && ! printf '%s\n' "$out" | grep -q Traceback && ok "L10 a crash (deeply nested canon) → rc 2 HARNESS-ERROR, never rc 1" || bad "L10 rc=$rc"

out=$(PYTHONIOENCODING=cp949 python3 "$C" "$FX" 2>&1); rc=$?
[ $rc -eq 0 ] && ! printf '%s\n' "$out" | grep -q Traceback && ok "L11 cp949 console (Korean Windows, piped) → green fixture still rc 0, no crash" || bad "L11 rc=$rc"

echo "lanes: $pass passed, $fail failed"; [ $fail -eq 0 ]
