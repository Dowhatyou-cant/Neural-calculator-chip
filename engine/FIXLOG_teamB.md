# Team B FIXLOG (flow and scripts) - package v0.3 -> v0.4

Folder: /home/claude/fix/B. No change to rtl/, mk_tests.py, tb/tb_tc.v, tc_model.py.
Times are wall clock (`date +%H:%M`) on a 2-core machine shared with Team A.

## 11:32 Start - baseline facts measured before changing anything
- Read PLAN.md, check_all.sh, run_tb.sh, synth_tc.sh, wrom_check.py, mutants.py, review3_tools/eq.sh and x.py.
- Verilator 5.020 and Yosys 0.33 are installed. Digits model (seed 1, n_img 30): vectors take 12.8 s to generate (mk_tests.py, python golden model), 3,605,441 words.
- Verilator on the digits build, same testbench: RTL compile 7.1 s + run 3.5 s -> `SUMMARY checks=1584 failures=0 (scores=1393 checkpoints=190)`. Gate netlist (synth_gate.v + ge_cells.v) compile 14.1 s + run 7.7 s -> identical SUMMARY. So Verilator handles ge_cells.v correctly on this build.
- Started the ORIGINAL scripts (snapshot copy /tmp/bw/B_orig_snapshot, Icarus) in the background for both builds, rtl then gate, to get reference counts and Icarus times for the R21 proof. Results are filled in under R21 below.

## R17 equivalence (11:25-11:32)
What: new `equiv.sh rtl_dir gate_netlist` (from review3_tools/eq.sh, but it takes ge_cells.v from its own folder instead of a hard-coded /tmp path, and it exits non-zero unless Yosys prints "Equivalence successfully proven").
Why: gate simulation only samples the netlist; the equivalence proof covers all inputs/states.
Command: `./synth_tc.sh builds/digits_64_48_10 /tmp/bw/d; ./equiv.sh builds/digits_64_48_10 /tmp/bw/d_gate.v`
Result (digits): 321 $equiv cells, 321 proven, 0 unproven, "Equivalence successfully proven!", rc=0, 7.5 s.
New `equiv_selftest.py model.npz dir` plants the three bugs (see below). Shared data mutations moved to `mutants_data.py` (used by mutants.py and the selftest).


## R21 first pieces (11:30)
- run_tb.sh now uses Verilator by default (SIM=icarus for the old behaviour) and reuses vectors in the work folder via a stamp (md5 of model + generator files + seed + n_img), so the rtl and gate runs of a build do not regenerate 3.6M words twice.
- check_all.sh rewrite, --quick: in progress.

## R16 + R19a + R27 mutants.py rewrite (11:32)
- Rewrote mutants.py: Verilator end to end; verdicts CAUGHT/SURVIVED/EQUIVALENT/CONTRADICTION/NEEDS_LIMIT_TESTS/BROKEN; 5 top-bit core mutants added (exact edits from x.py, exactly-once assert); data rows have separate table-check and end-to-end-fails columns, THIN under 10; HEADLINE line.
- First run on digits started (took more than 120 s, running in background); results below when done.

## 11:47 R17 planted-bug proof (equiv_selftest.py, `python3 equiv_selftest.py model.npz dir`)
Command per build; the RTL is regenerated from the changed model for bugs 2 and 3, the netlist stays the original one.
| build | control | one gate NAND2->NOR2 | one reachable threshold +1 | one layer-1 weight flipped |
|---|---|---|---|---|
| digits | PASS, 0 unproven | step FAILS, 20 unproven $equiv cells | FAILS, 10 | FAILS, 9 |
| rand 14-class | PASS, 0 unproven | FAILS, 19 | FAILS, 10 | FAILS, 9 |
Time: about 55 s per build (a failing proof is slower than a passing one: ~29 s vs 7 s).
Failure 1 (mine): the first selftest printed `unproven=?`. Symptom: counts missing. Root cause: when `equiv_status -assert` fails, Yosys prints `Found N unproven $equiv cells in 'equiv_status -assert'` instead of the "Of those cells ... N are unproven" line I parsed. Found by reading the failing output by hand. Fix: parse both forms; re-ran, numbers above.
Failure 2 (environment, not a bug): `/usr/bin/time` does not exist here; used `date +%s` instead.

## 11:40 R19a CONTRADICTION demo
Command: `MUTANTS_DECLARE_EQUIVALENT=tie_to_higher_class python3 mutants.py quick_model.npz dir 9 3 12` (env hook that exists only for this demonstration; it declares that real, non-equivalent mutant equivalent).
Result: row `BAD CONTRADICTION core: tie_to_higher_class  15 fails ... [declared equivalent (...) but the run failed]`, `1 problems`, script exit code 1 (the shell printed rc=1). Without the hook the same mutant is CAUGHT with 15 failing checks.
The old code would have printed CAUGHT for it (verdict `'EQUIVALENT' if rc == 0 else 'CAUGHT'`), i.e. a wrong declaration was reported as good news.

## 11:36 R16 top-bit mutants / R27 reporting - first measured results (mutants.py on digits, seed 9, 3 images, 12 boundary)
17 rows, 0 problems, 2 m 35 s (contended). All five top-bit mutants are exactly-once matches. Surprise: with the CURRENT vectors they are already CAUGHT on the digits build (end-to-end failing checks: best_top_bit 1, acc2_top_bit 9, score_top_bit 21, stream_bias_top_bit 21, stream_thr_top_bits 8), because the random streamed models in mk_tests section 3 reach large values sometimes. On the tiny quick model best_top_bit SURVIVES (0 fails) and is reported NEEDS_LIMIT_TESTS, as designed. These are weak catches (1-9 fails): Team A's limit tests are still needed (acceptance is >=10 each). I added a warning "core caught by <10 fails" to the headline so weak catches are visible.
Data mutants digits: end-to-end fails wipe_corner 177, flip_corner 180, flip_one_layer2 23, threshold_plus_one 9 (THIN), threshold_minus_one 3 (THIN); table check caught 5/5 (by construction). Headline: `core mutants caught 9/9 (1 declared equivalent: bias_of_wrong_class, all hardwired biases 0); data end-to-end fails 3-180; THIN: threshold_plus_one, threshold_minus_one`.
So the sensitivity of the end-to-end suite to a single threshold change is only 3-9 failing checks: THIN is a real finding, not a formality.
Failure 3 (mine): first quick-mode run, mutants step failed in 0 s. Symptom: Traceback from `subprocess.CalledProcessError ... mk_tests.py ... returncode 1`. Root cause: I passed n_img=2 and mk_tests.py asserts n_img >= 3. Found in the step log. Fix: quick mutants use `9 3 6`. Re-ran OK.

## 11:39 R21 quick mode
`check_all.sh --quick /tmp/bq`: model 8->4->3 from quick_model.py (non-zero biases and thresholds), mutant subset (threshold_compare_gt, minus_one_decode, tie_to_higher_class, stream_thr_top_bits, flip_one_layer2_weight, threshold_plus_one) because each Verilator compile is 8-12 s and the full 16 compiles alone take ~2.5 min. Measured 1 m 51 s while another job (Icarus reference run) and Team A were using the cores. QUICK prints "QUICK CHECKS PASS" and never "ALL CHECKS PASS".
Compile-flag test (control build, tiny model): -O3 compile 11.8 s / run 0.7 s; -O0 8.4 s / 5.9 s; -O1 7.5 s / 5.0 s. Not worth changing: kept defaults.

## Design decisions in R21 (reasons)
- Verilator for RTL, gate and mutant runs (default); Icarus remains available with `--icarus`/`SIM=icarus`. Reason: the plan target (<15 min) cannot be met with 15 min of Icarus gate simulation per build. Risk: Verilator is 2-state, so X/uninitialised-state bugs are invisible to it; the formal equivalence (R17) and an occasional `--icarus` run cover that. Documented in README.
- vectors are generated once per build and shared by the rtl and gate runs (stamp file), instead of three mk_tests runs (13 s each on digits).
- the two builds run in parallel (background subshells); per-step times are printed, plus the total.

## 12:06 Full run: `cd /tmp && /home/claude/fix/B/check_all.sh /tmp/b_checks` (started 11:50)
Result: ALL CHECKS PASS, total elapsed 15m33s. Machine was shared: Team A's jobs plus my background Icarus reference run (nice 19), so these times are pessimistic.
| step | digits | rand 14-class |
|---|---|---|
| lint | 1 s | 1 s |
| synth | 24 s | 28 s |
| equiv (R17) | 40 s PASS, 321/321 $equiv proven | 55 s PASS |
| table (5,200 values) | 14 s | 15 s |
| rtl sim (Verilator) | 90 s, 1,584 checks, 0 fail | 112 s, 1,997 checks |
| gate sim (Verilator) | 90 s, 1,584 checks | 109 s, 1,997 checks |
| mutants | 496 s | 485 s |
Global: golden 16 s, spec_numbers 0 s, equiv_selftest 111 s (run once, after the builds). Builds run in parallel, so total (15m33s) < sum.
Headlines: digits `core caught 9/9 (1 declared equivalent), data end-to-end fails 3-180, THIN: threshold_plus_one, threshold_minus_one`; rand `core caught 8/10, 2 NEEDS_LIMIT_TESTS (best_top_bit, acc2_top_bit), data fails 10-232, THIN none`. Weak core catches (<10 fails): digits best_top_bit, acc2_top_bit, stream_thr_top_bits; rand stream_thr_top_bits.
Where the time goes: mutants 8 min (16 Verilator compiles per build at 8-30 s each under load; the runs themselves are seconds). Further saving would need compiling mutants in parallel, which needs more than 2 cores.

## R21 counts: Verilator vs Icarus (same vectors, seed 1, 30 images)
| build | Icarus RTL (original run_tb.sh) | Verilator RTL | Icarus gate | Verilator gate |
|---|---|---|---|---|
| digits | 1,584 checks, 0 fail, 339 s | 1,584, 90 s | 1,584, 0 fail, 1,340 s (loaded machine) | 1,584 |
| rand 14 | 1,997 checks, 0 fail, 680 s | 1,997, 112 s | NOT RUN (stopped to free the cores; Icarus gate of the rand build would take 20+ min) | 1,997 |
Counts equal on every pair that was run (3 of 4 Icarus references); Icarus gate on the rand build was not completed. The gate netlist of both builds is additionally proven equal to the RTL by equiv.sh.

## Not done / caveats
- Icarus gate run of the rand build (see above). `--icarus` mode of check_all.sh itself was not executed end to end (only the original run_tb.sh with Icarus, and mutants.py's SIM=icarus path is untested).
- NEEDS_LIMIT_TESTS list left in mutants.py for Opus to remove at integration. Currently 3 of the 5 top-bit mutants are caught anyway (weakly) on digits.
- Plan remarks: (1) the top-bit mutants are not "barely survive" on the digits build: they are caught with 1-21 fails, so the list only matters on the rand build and tiny models; (2) Verilator is 2-state, so Icarus is still the only X-checker; (3) 15 min is only met at about 15.5 min under load; the mutants step (8 min) is compile-bound.
- Wall-clock note: the machine clock in this log is that of the sandbox.
