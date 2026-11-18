#!/bin/bash
# Start-up boundary self-test (review R18). For each start-up case the minimum number of idle
# bytes derived from the RTL must PASS and one fewer must FAIL. Proves the boundary tests can fail.
#   usage: ./startup_selftest.sh model.npz rtl_dir workdir
# Minimum idle bytes on the real host (first clock edge samples byte 1; tb op 9):
#   pwr_hw     power-up reset, clock stopped, hardwired START  : 2  (reset synchroniser: 2 edges)
#   rst_hw     reset with the clock stopped, hardwired START   : 2
#   rst_stream reset with the clock stopped, streamed START    : 3  (mode synchroniser is held in reset too)
#   mode_h2s   mode pin 0->1 with the clock stopped, START      : 1
#   mode_s2h   mode pin 1->0 with the clock stopped, START      : 1
HERE=$(cd "$(dirname "$0")" && pwd)
npz=$(cd "$(dirname "$1")" && pwd)/$(basename "$1"); rtl=$(cd "$2" && pwd); out=$3
mkdir -p "$out"; out=$(cd "$out" && pwd)
bad=0
for spec in pwr_hw:2 rst_hw:2 rst_stream:3 mode_h2s:1 mode_s2h:1; do
  case=${spec%%:*}; min=${spec##*:}
  for n in $((min-1)) $min; do
    WD=$out/${case}_$n
    python3 "$HERE/mk_startup.py" "$npz" "$WD" "$case" "$n" > "$WD.gen.log" 2>&1 || { echo "GEN FAIL $case $n"; bad=1; continue; }
    verilator --binary --timing -Wno-fatal -Wno-lint -O0 -I"$WD" --top-module tb_tc --Mdir "$WD/o" -o sim \
      "$HERE/tb/tb_tc.v" "$rtl"/*.v > "$WD.vl.log" 2>&1 || { echo "COMPILE FAIL $case $n"; bad=1; continue; }
    (cd "$WD" && ./o/sim > sim.log 2>&1) 2>/dev/null; rc=$?
    if [ $n -lt $min ]; then want=FAIL; else want=PASS; fi
    if [ $rc -ne 0 ]; then got=FAIL; else got=PASS; fi
    [ $got = $want ] && v=OK || { v=WRONG; bad=1; }
    echo "$v  $case idle=$n  expected $want got $got  $(grep SUMMARY "$WD/sim.log")"
  done
done
[ $bad -eq 0 ] && echo "startup self-test: all boundaries as derived" || echo "startup self-test: PROBLEM"
exit $bad
