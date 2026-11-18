# v2 engine (tc_engine) — eChipHub–SCL 0.8 µm test chip, package v0.4

Spec: project doc `v2-engine-spec.md`. Build log (reasons, failures, reviews): `v2-engine-build-log.md`.
Review findings tracker: `review-findings.md`.

Needs: Verilator 5 (lint and simulation), Yosys, Icarus Verilog (table check; `--icarus` runs), Python 3 + numpy + scikit-learn.

**Definition of done - one command, both builds, from a freshly unpacked copy, run from another folder:**

    ./check_all.sh /some/other/folder/checks        # PASS/FAIL + seconds per check, "ALL CHECKS PASS" at the end

Options (before the folder): `--quick` tiny 8->4->3 model and a mutant subset, about 2 min, for iteration only
(prints "QUICK CHECKS PASS", never "ALL CHECKS PASS"); `--icarus` simulate with Icarus instead of Verilator.

What it runs for each build (digits 64->48->10 and the random 64->48->14 stand-in; the two builds run in parallel):

    verilator --lint-only -Wall ...                   # lint
    ./synth_tc.sh rtl out                             # generic-library synthesis, latch check, writes the mapped netlist out_gate.v
    ./equiv.sh rtl out_gate.v                         # FORMAL equivalence: RTL == the exact netlist synth_tc.sh measured (Yosys, all inputs/states)
    python3 wrom_check.py model.npz w                 # exhaustive table check of every hardwired value (RTL + gate)
    ./run_tb.sh model.npz w 1 30                      # RTL sim: random, digit, threshold-boundary, streamed, stopped-clock, fuzz...
    ./run_tb.sh model.npz w 1 30 gate                 # gate sim: the exact netlist synth_tc.sh measures
    python3 mutants.py model.npz w                    # 11 core + 5 data mutants (see below)

plus `python3 tc_model.py` (golden self-check), `python3 spec_numbers.py` (numbers quoted in the spec) and, once:
`python3 equiv_selftest.py` (three planted bugs - one gate changed, one threshold +1, one weight flipped - must each FAIL equiv.sh) and
`./startup_selftest.sh` (start-up after a stopped-clock reset or mode change: the derived minimum idle bytes pass, one fewer fails; review R18).

Expected check counts (seed 1, 30 images, v0.4 vectors with the limit, abort, start-up and long hardwired fuzz sections): see `v2-engine-spec.md`; both simulators give the same counts. (v0.3 vectors: digits 1,584, 14-class 1,997.)
Expected run time, 2 cores: see "Run time" below.

Notes on what each step proves
- equiv.sh proves the mapped netlist equals the RTL (flops matched by name, logic by SAT, state by induction after
  `proc; memory; flatten`; the `memory` pass is needed because the big case tables become ROMs). This is what closes
  review R17; the gate simulation is now a second, sampled check of the same netlist.
- The GATE half of wrom_check.py synthesises tc_wrom SEPARATELY (own yosys run, tc_wrom as top module). It is
  NOT the netlist synth_tc.sh measures. It stays as a sanity check; the proof for the measured netlist is equiv.sh.
- Simulation uses Verilator by default (2-state: it cannot see X/uninitialised-state bugs; the proof for reset
  behaviour of the netlist is equiv.sh plus `--icarus`, which uses 4-state Icarus). Run `--icarus` before a release.
- mutants.py verdicts: CAUGHT, SURVIVED (problem), EQUIVALENT (declared, with the reason), CONTRADICTION (declared
  equivalent but the run fails or does not compile: problem), NEEDS_LIMIT_TESTS (kept for future use; the list is
  EMPTY since integration, so the five top-bit mutants must be CAUGHT by the spec-limit tests), BROKEN
  (mutant does not compile or hangs: problem). Data mutants show the table-check result and the end-to-end failing-check
  count as separate columns; the end-to-end count is the real sensitivity and is flagged THIN (warning) under 10.
  Each core mutant is applied to a temp copy with an exactly-once pattern assert; rtl/ is never edited.

Run time (see FIXLOG.md for the measured numbers): Verilator everywhere, builds in parallel: about 15.5 min measured with the machine shared with another team and a background Icarus job (digits and random builds in parallel; roughly 10-12 min on an idle 2-core machine, estimate not measured);
`--quick` about 2 min (1 m 51 s measured, also under load); `--icarus` adds roughly 5 min (RTL) + 15 min (gate) + 15-20 min (mutants) per build,
single-threaded, i.e. over an hour.

Helper files: equiv.sh, equiv_selftest.py, startup_selftest.sh, mk_startup.py, mutants_data.py, quick_model.py.
Fix records for v0.4: FIXLOG_teamA.md, FIXLOG_teamB.md, OPUS_LOG.md.
Hand-written: rtl/tc_core.v, rtl/tc_rsync.v, rtl/tc_dsync.v. Generated: tc_wrom.v, tc_engine.v.
builds/ holds pre-generated RTL for the trained digits model and a random 64->48->14 stand-in.
