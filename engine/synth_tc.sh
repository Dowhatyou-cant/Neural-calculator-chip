#!/bin/bash
# usage: synth_tc.sh rtl_dir out_prefix
# Synthesises tc_engine with the generic NAND2-equivalent library (ge.lib):
#   - fails on latches or check errors
#   - writes the SAME mapped netlist it measures to <out_prefix>_gate.v
#     (simulate it with ge_cells.v: run_tb.sh ... gate)
#   - reports logic depth from a separate generic-gate run (timing proxy only)
set -e
here=$(cd "$(dirname "$0")" && pwd)
d=$1; o=$2; lib=$here/ge.lib
yosys -p "read_verilog $d/*.v; hierarchy -top tc_engine; proc; check -assert; \
  synth -top tc_engine -flatten; select -assert-none t:\$dlatch* t:\$_DLATCH*; \
  dfflegalize -cell \$_DFF_P_ 01 -cell \$_DFF_PN0_ 01; dfflibmap -liberty $lib; \
  abc -liberty $lib; opt_clean; tee -o $o.stat stat -liberty $lib; \
  write_verilog -noattr -noexpr ${o}_gate.v" > $o.log 2>&1
grep -E "Chip area" $o.stat
grep -E "^\s+(DFFR?|NAND2|NOR2|INV|AOI21|OAI21|XOR2|XNOR2|MUX2|BUF)\s+[0-9]+" $o.stat || true
yosys -p "read_verilog $d/*.v; synth -top tc_engine -flatten; \
  abc -g AND,NAND,OR,NOR,XOR,XNOR,MUX; ltp -noff" 2>&1 \
  | grep -E "Longest topological path" | sed 's/^/logic depth (generic gates, proxy): /'
echo "netlist: ${o}_gate.v"
