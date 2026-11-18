#!/bin/bash
# usage: equiv.sh rtl_dir gate_netlist 
# Formal equivalence (Yosys equiv_*) between the RTL and the EXACT mapped netlist
# that synth_tc.sh measured (<out>_gate.v, built from ge_cells.v cells). Closes
# review R17: the gate simulation only samples the netlist, this proves it equal.
# Flops are matched by name; combinational logic is proven by SAT and the
# sequential part by induction. `memory` is needed so big case tables (tc_wrom)
# become ROMs before flattening. Exit 0 only on "Equivalence successfully proven".
here=$(cd "$(dirname "$0")" && pwd)
R=$1; G=$2
out=$(yosys -p "
read_verilog $R/tc_core.v $R/tc_rsync.v $R/tc_dsync.v $R/tc_wrom.v $R/tc_engine.v; hierarchy -top tc_engine; proc; memory; flatten; opt_clean; rename tc_engine gold; design -stash gold;
read_verilog $G $here/ge_cells.v; hierarchy -top tc_engine; proc; memory; flatten; opt_clean; rename tc_engine gate; design -stash gate;
design -copy-from gold -as gold gold; design -copy-from gate -as gate gate;
equiv_make gold gate eq; hierarchy -top eq; async2sync; equiv_simple -seq 2; equiv_induct -seq 2; equiv_status -assert" 2>&1)
rc=$?
echo "$out" | grep -E "Found [0-9]+ \\\$equiv|Of those|unproven|Equivalence successfully|ERROR|proven" | tail -8
[ $rc -eq 0 ] && echo "$out" | grep -q "Equivalence successfully proven"
