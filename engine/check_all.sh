#!/bin/bash
# usage: check_all.sh [--quick] [--icarus] work_dir [model.npz ...]
# The definition of done, in one command: golden self-check and spec numbers, then
# for EVERY build given (default: both shipped models, run in PARALLEL):
#   lint, synthesis, formal equivalence RTL == measured netlist, exhaustive table
#   check, RTL sim, gate-level sim of the measured netlist, mutation test.
# Finally two self-tests: the equivalence step (three planted bugs must fail it) and the
# start-up boundaries (one idle byte fewer than the derived minimum must fail; review R18).
# Prints one line per check with its elapsed time, then the total; exits non-zero
# if anything fails.
#   --quick   tiny model (8->4->3), mutation subset: for iteration only, NOT the
#             definition of done (~2-3 min). Ignores any models given.
#   --icarus  simulate with Icarus (4-state, the original reference) instead of
#             Verilator: RTL ~5 min, gate ~15 min, mutants ~15-20 min per build.
quick=0; SIM=verilator
while [[ "$1" == --* ]]; do
  case "$1" in --quick) quick=1;; --icarus) SIM=icarus;; *) echo "unknown option $1" >&2; exit 2;; esac; shift
done
export SIM
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$1"; wd=$(cd "$1" && pwd); shift
models=("$@"); [ ${#models[@]} -eq 0 ] && models=("$here/v2_P2_H48_A2.npz" "$here/rand_644814.npz")
if [ $quick -eq 1 ]; then
  python3 "$here/quick_model.py" "$wd/quick_8_4_3.npz" || exit 2
  models=("$wd/quick_8_4_3.npz")
  mut_args="9 3 6"; export MUTANTS_SUBSET=threshold_compare_gt,minus_one_decode,tie_to_higher_class,stream_thr_top_bits,flip_one_layer2_weight,threshold_plus_one
  sim_args="1 6"
else
  mut_args="9 3 12"; sim_args="1 30"
fi
rm -f "$wd"/*.fail "$wd"/*.times
t_all=$(date +%s)
step() {  # tag, name, command...   (appends elapsed to $wd/<tag>.times, sets $wd/<tag>.fail)
  local tag=$1 name=$2; shift 2
  local t0=$(date +%s); local rc=0
  "$@" > "$wd/$name.log" 2>&1 || rc=1
  local dt=$(( $(date +%s) - t0 ))
  if [ $rc -eq 0 ]; then echo "PASS  $name  (${dt}s)"; else echo "FAIL  $name  (${dt}s, see $wd/$name.log)"; touch "$wd/$tag.fail"; fi
  printf '%s %s\n' "$name" "$dt" >> "$wd/$tag.times"
}
build() {  # one model, all its checks, sequential
  local m=$1 b; b=$(basename "$1" .npz)
  mkdir -p "$wd/$b"
  python3 "$here/gen_tc.py" "$m" "$wd/$b/rtl" > /dev/null
  step "$b" "$b.lint"    verilator --lint-only -Wall --top-module tc_engine "$wd/$b"/rtl/*.v
  step "$b" "$b.synth"   "$here/synth_tc.sh" "$wd/$b/rtl" "$wd/$b/synth"
  step "$b" "$b.equiv"   "$here/equiv.sh" "$wd/$b/rtl" "$wd/$b/synth_gate.v"
  step "$b" "$b.table"   python3 "$here/wrom_check.py" "$m" "$wd/$b/table"
  step "$b" "$b.rtl"     "$here/run_tb.sh" "$m" "$wd/$b/sim" $sim_args
  step "$b" "$b.gate"    "$here/run_tb.sh" "$m" "$wd/$b/sim" $sim_args gate
  step "$b" "$b.mutants" python3 "$here/mutants.py" "$m" "$wd/$b/mutants" $mut_args
}
step global golden python3 "$here/tc_model.py"
step global spec_numbers python3 "$here/spec_numbers.py"
for m in "${models[@]}"; do build "$m" & done
wait
step global equiv_selftest python3 "$here/equiv_selftest.py" "${models[0]}" "$wd/equiv_selftest"
[ $quick -eq 0 ] && step global startup_selftest "$here/startup_selftest.sh" "${models[0]}" "$wd/$(basename "${models[0]}" .npz)/rtl" "$wd/startup_selftest"
echo "---- mutation headlines (details in <build>.mutants.log)"
for m in "${models[@]}"; do grep -h HEADLINE "$wd/$(basename "$m" .npz).mutants.log"; done
echo "---- elapsed per step (s); builds ran in parallel, so the total is less than the sum"
cat "$wd"/*.times | sed 's/^/  /'
total=$(( $(date +%s) - t_all ))
echo "total elapsed: $((total/60))m$((total%60))s  (simulator: $SIM$([ $quick -eq 1 ] && echo ', QUICK MODE'))"
if ls "$wd"/*.fail >/dev/null 2>&1; then echo "SOME CHECKS FAILED"; exit 1; fi
[ $quick -eq 1 ] && echo "QUICK CHECKS PASS (not the definition of done: run without --quick)" || echo "ALL CHECKS PASS"
