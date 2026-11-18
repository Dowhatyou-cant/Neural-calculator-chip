#!/bin/bash
# usage: run_tb.sh model.npz work_dir [seed] [n_img] [rtl|gate]
# Generates RTL + vectors and runs the self-checking testbench.
#   rtl  : simulate the RTL
#   gate : synthesise with synth_tc.sh and simulate THAT mapped netlist (ge_cells.v)
# Simulator: SIM=verilator (default, seconds) or SIM=icarus (slow, minutes, the
# original reference; 4-state, so it also catches X/uninitialised-state bugs).
# Both give identical check counts (proved in FIXLOG.md, R21).
# The vectors in work_dir are reused when model, seed, n_img and the generator
# files are unchanged (stamp), so rtl and gate runs can share one folder.
# Exit code != 0 on any failure.
set -e
here=$(cd "$(dirname "$0")" && pwd)
npz=$(cd "$(dirname "$1")" && pwd)/$(basename "$1"); mkdir -p "$2"; wd=$(cd "$2" && pwd); seed=${3:-1}; nimg=${4:-40}; kind=${5:-rtl}
sim=${SIM:-verilator}
[ "$kind" = rtl ] || [ "$kind" = gate ] || { echo "kind must be rtl or gate" >&2; exit 2; }
[ "$sim" = verilator ] || [ "$sim" = icarus ] || { echo "SIM must be verilator or icarus" >&2; exit 2; }
python3 "$here/gen_tc.py" "$npz" "$wd/rtl" > /dev/null
stamp=$(cat "$npz" "$here/mk_tests.py" "$here/tc_model.py" "$here/boundary.py" | md5sum | cut -d' ' -f1)-$seed-$nimg
if [ "$(cat "$wd/vectors.stamp" 2>/dev/null)" != "$stamp" ]; then
  rm -f "$wd/vectors.stamp"
  python3 "$here/mk_tests.py" "$npz" "$wd" "$seed" "$nimg"
  echo "$stamp" > "$wd/vectors.stamp"
fi
if [ "$kind" = gate ]; then
  "$here/synth_tc.sh" "$wd/rtl" "$wd/synth" > /dev/null
  src="$wd/synth_gate.v $here/ge_cells.v"
else
  src="$wd/rtl/*.v"
fi
cd "$wd"
if [ "$sim" = icarus ]; then
  iverilog -g2005 -I . -o "sim_$kind.vvp" "$here/tb/tb_tc.v" $src
  run="vvp -n sim_$kind.vvp"
else
  verilator --binary --timing -Wno-fatal -Wno-lint -I. --top-module tb_tc --Mdir "obj_$kind" -o sim \
    "$here/tb/tb_tc.v" $src > "verilator_$kind.log" 2>&1 || { tail -20 "verilator_$kind.log"; exit 2; }
  run="obj_$kind/sim"
fi
set +e
$run > "sim_$kind.log" 2>&1; rc=$?
grep -E "FAIL|SUMMARY|^PASS" "sim_$kind.log" | tail -8
exit $rc
