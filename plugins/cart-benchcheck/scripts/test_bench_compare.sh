#!/usr/bin/env bash
# Lanes for bench_compare.py — known sample pairs are the answer key (known-pair).
#   B1 a clear speedup (10 runs each, no overlap) → FASTER, rc 0, exact test
#   B2 control: same distribution, medians 8% apart by noise → NO-DIFFERENCE ~, rc 0, the line says not to report the %
#   B3 a slowdown → SLOWER; with --higher-is-better the same data reads BETTER
#   B4 fewer than 5 runs on a side → TOO-FEW rc 1, no FASTER/SLOWER word anywhere
#   B5 one wild outlier on the after side does not flip B1's verdict and is counted as dropped
#   B6 significant but under --min-effect → NO-DIFFERENCE with the min-effect reason
#   B7 hyperfine --export-json is read; ties use the normal approximation
#   B8 garbage / empty / missing / NaN / bad option → HARNESS-ERROR rc 2, never a VERDICT line
#   B9 high spread → a NOISE line next to the verdict
#   B10 review R1: p-values match scipy.stats.mannwhitneyu (B1 exact 1.08e-05 · B2 exact 0.247 · B7 asymptotic 0.00115 on the 8/6 left after the IQR drop)
#   B12 review R2: Greek μ is read; --unit cannot relabel a file that has a unit; an extreme-value median is exactly 0
#       (refused) and a tiny subnormal pair keeps its +50%; 1e200 values do not crash
#   B11 review R1: units — «1 s» vs «900 ms» is FASTER (not +89900%); ms vs ops/s, a file mixing units, a multi-result
#       hyperfine file, non-finite medians/changes and NaN options are HARNESS-ERROR
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; D="$HERE/bench_compare.py"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
pass=0; fail=0; ok(){ pass=$((pass+1)); echo "  ✅ $1"; }; bad(){ fail=$((fail+1)); echo "  ❌ $1"; printf '%s\n' "$out" | sed 's/^/     /'; }
w(){ f="$W/$1"; shift; printf '%s\n' "$@" > "$f"; echo "$f"; }
first(){ printf '%s\n' "$out" | head -1; }

A=$(w a1 100.2 101.1 99.4 102.3 100.7 98.9 101.6 100.0 99.8 103.1); B=$(w b1 90.2 91.1 89.4 92.3 90.7 88.9 91.6 90.0 89.8 93.1)
out=$(python3 "$D" "$A" "$B" --unit ms); rc=$?
if [ $rc -eq 0 ] && first | grep -q '^VERDICT: FASTER ' && first | grep -qF 'exact' && first | grep -qF '%'; then ok "B1 clear speedup → FASTER (exact)"; else bad "B1 rc=$rc"; fi

A=$(w a2 100 112 95 108 103 97 110 92 105 99); B=$(w b2 96 104 90 101 94 107 89 98 93 111)
out=$(python3 "$D" "$A" "$B"); rc=$?
if [ $rc -eq 0 ] && first | grep -q '^VERDICT: NO-DIFFERENCE (~ ' && first | grep -qF 'do not report' && ! printf '%s\n' "$out" | grep -qE 'FASTER|SLOWER'; then ok "B2 control: noise → NO-DIFFERENCE ~"; else bad "B2 rc=$rc"; fi

A=$(w a3 90 91 89 92 90 88 91 90 89 93); B=$(w b3 100 101 99 102 100 98 101 100 99 103)
out=$(python3 "$D" "$A" "$B"); rc=$?; o1=$(first)
out=$(python3 "$D" "$A" "$B" --higher-is-better); rc2=$?
if [ $rc -eq 0 ] && [ $rc2 -eq 0 ] && printf '%s' "$o1" | grep -q '^VERDICT: SLOWER ' && first | grep -q '^VERDICT: BETTER '; then ok "B3 slowdown → SLOWER; --higher-is-better → BETTER"; else bad "B3 rc=$rc rc2=$rc2 first=$o1"; fi

A=$(w a4 100 101 99 102); B=$(w b4 50 51 49 52 50 51)
out=$(python3 "$D" "$A" "$B"); rc=$?
if [ $rc -eq 1 ] && first | grep -q '^VERDICT: TOO-FEW ' && ! printf '%s\n' "$out" | grep -qE 'FASTER|SLOWER|BETTER|WORSE'; then ok "B4 4 runs → TOO-FEW rc 1"; else bad "B4 rc=$rc"; fi

A=$(w a5 100 101 99 102 100 98 101 100 99 103); B=$(w b5 90 91 89 92 90 88 91 90 89 900)
out=$(python3 "$D" "$A" "$B"); rc=$?
if [ $rc -eq 0 ] && first | grep -q '^VERDICT: FASTER ' && printf '%s\n' "$out" | grep -qF 'outliers dropped 1 of 10'; then ok "B5 outlier dropped, verdict holds"; else bad "B5 rc=$rc"; fi

A=$(w a6 1000 1001 1000 1001 1000 1001 1000 1001 1000 1001); B=$(w b6 995 996 995 996 995 996 995 996 995 996)
out=$(python3 "$D" "$A" "$B"); rc=$?
if [ $rc -eq 0 ] && first | grep -q '^VERDICT: NO-DIFFERENCE' && first | grep -qF 'min-effect'; then ok "B6 significant but 0.5% < min-effect → ~"; else bad "B6 rc=$rc"; fi

printf '{"results":[{"command":"old","times":[1.0,1.0,1.1,1.0,1.1,1.0,1.0,1.1]}]}' > "$W/h1.json"
printf '{"results":[{"command":"new","times":[0.8,0.8,0.9,0.8,0.8,0.9,0.8,0.8]}]}' > "$W/h2.json"
out=$(python3 "$D" "$W/h1.json" "$W/h2.json"); rc=$?
if [ $rc -eq 0 ] && first | grep -q '^VERDICT: FASTER ' && first | grep -qF 'normal+ties'; then ok "B7 hyperfine JSON read; ties → normal approximation"; else bad "B7 rc=$rc"; fi

G=$(w g1 100 "fast" 99); E=$(w e1 "# only a comment" ""); N=$(w n1 1 2 nan 4 5); J="$W/j.json"; printf '{"results":[]}' > "$J"
allok=1; for args in "$A $G" "$A $E" "$A $W/missing" "$A $N" "$A $J" "$A" "$A $A --alpha x" "$A $A --bogus"; do
  out=$(python3 "$D" $args 2>&1); rc=$?
  if [ $rc -ne 2 ] || ! first | grep -q '^HARNESS-ERROR' || printf '%s\n' "$out" | grep -q '^VERDICT'; then allok=0; echo "     args=[$args] rc=$rc"; fi
done
if [ $allok -eq 1 ]; then ok "B8 garbage/empty/missing/NaN/bad JSON/one file/bad option → HARNESS-ERROR rc 2"; else out=""; bad "B8"; fi

A=$(w a9 100 140 70 120 80 130 60 110 90 150); B=$(w b9 30 31 29 32 30 28 31 30 29 33)
out=$(python3 "$D" "$A" "$B"); rc=$?
if [ $rc -eq 0 ] && printf '%s\n' "$out" | grep -q '^NOISE: before'; then ok "B9 high spread → NOISE line"; else bad "B9 rc=$rc"; fi

A=$(w a10 100.2 101.1 99.4 102.3 100.7 98.9 101.6 100.0 99.8 103.1); B=$(w b10 90.2 91.1 89.4 92.3 90.7 88.9 91.6 90.0 89.8 93.1)
o1=$(python3 "$D" "$A" "$B" | head -1); o2=$(python3 "$D" "$W/a2" "$W/b2" | head -1); o3=$(python3 "$D" "$W/h1.json" "$W/h2.json" | head -1); out="$o1
$o2
$o3"
if printf '%s' "$o1" | grep -qF 'p=1.08e-05' && printf '%s' "$o2" | grep -qF 'p=0.247 ' && printf '%s' "$o3" | grep -qF 'p=0.00115,'; then ok "B10 p-values match scipy (exact, exact, asymptotic+ties)"; else bad "B10"; fi

U1=$(w u1 "1 s" "1 s" "1 s" "1 s" "1 s" "1 s" "1 s" "1 s" "1 s" "1 s"); U2=$(w u2 "900 ms" "900 ms" "900 ms" "900 ms" "900 ms" "900 ms" "900 ms" "900 ms" "900 ms" "900 ms")
out=$(python3 "$D" "$U1" "$U2"); rc=$?
if [ $rc -eq 0 ] && first | grep -q '^VERDICT: FASTER ' && first | grep -qF -- '-10.00%'; then ok "B11a 1 s vs 900 ms → FASTER −10%"; else bad "B11a rc=$rc"; fi
O=$(w op "5 ops/s" "5 ops/s" "5 ops/s" "5 ops/s" "5 ops/s"); MX=$(w mx "100 ms" "0.1 s" "100 ms" "100 ms" "100 ms"); 
printf '{"results":[{"times":[1,1,1,1,1]},{"times":[2,2,2,2,2]}]}' > "$W/multi.json"
X1=$(w x1 -1e308 1e308 -1e308 1e308 -1e308 1e308 -1e308 1e308 -1e308 1e308); X2=$(w x2 1 1 1 1 1 1 1 1 1 1); X3=$(w x3 1e-320 1e-320 1e-320 1e-320 1e-320 1e-320)
allok=1; for args in "$U2 $O" "$MX $U2" "$W/multi.json $W/h2.json" "$X1 $X2" "$X3 $X2" "$X2 $X2 --min-effect nan" "$X2 $X2 --alpha nan"; do
  out=$(python3 "$D" $args 2>&1); rc=$?
  if [ $rc -ne 2 ] || ! first | grep -q '^HARNESS-ERROR' || printf '%s\n' "$out" | grep -q '^VERDICT'; then allok=0; echo "     args=[$args] rc=$rc"; printf '%s\n' "$out" | head -2 | sed 's/^/       /'; fi
done
if [ $allok -eq 1 ]; then ok "B11b incomparable units / mixed units / multi-result JSON / non-finite / NaN options → HARNESS-ERROR"; else out=""; bad "B11b"; fi

G1=$(w g1 "1 μs" "1 μs" "1 μs" "1 μs" "1 μs"); G2=$(w g2 "0.9 μs" "0.9 μs" "0.9 μs" "0.9 μs" "0.9 μs")
o1=$(python3 "$D" "$G1" "$G2" | head -1); out=$(python3 "$D" "$U1" "$U2" --unit ms); r2=$?; o2=$(first)
out=$(python3 "$D" "$X1" "$X2"); o3=$(first)
T1=$(w t1 1e-323 1e-323 1e-323 1e-323 1e-323); T2=$(w t2 1.5e-323 1.5e-323 1.5e-323 1.5e-323 1.5e-323); out=$(python3 "$D" "$T1" "$T2"); o4=$(first)
E1=$(w e1 1e200 1.01e200 1e200 1.01e200 1e200 1.01e200); E2=$(w e2 9e199 9.1e199 9e199 9.1e199 9e199 9.1e199); out=$(python3 "$D" "$E1" "$E2"); r5=$?; o5=$(first)
out="$o1
$o2
$o3
$o4
$o5"
if printf '%s' "$o1" | grep -q '^VERDICT: FASTER' && [ $r2 -eq 2 ] && printf '%s' "$o3" | grep -qF 'before median is 0' && ! printf '%s' "$o4" | grep -qF '+100' && [ $r5 -eq 0 ] && printf '%s' "$o5" | grep -q '^VERDICT: FASTER'; then ok "B12 μ, --unit conflict, extreme median 0, subnormal, 1e200"; else bad "B12"; fi

A=$(w a13 100.2 101.1 99.4 102.3 100.7 98.9 101.6 100.0 99.8 103.1); B=$(w b13 90.2 91.1 89.4 92.3 90.7 88.9 91.6 90.0 89.8 93.1)
out=$(PYTHONIOENCODING=cp949 python3 "$D" "$A" "$B" --unit µs 2>&1); rc=$?
if [ $rc -eq 0 ] && first | grep -q '^VERDICT: FASTER ' && ! printf '%s\n' "$out" | grep -q 'HARNESS-ERROR'; then ok "B13 cp949 console → the verdict still prints (rc 0)"; else bad "B13 rc=$rc"; fi

echo "bench_compare lanes: $pass passed, $fail failed"
[ $fail -eq 0 ]
