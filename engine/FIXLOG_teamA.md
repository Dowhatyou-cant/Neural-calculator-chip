# FIXLOG Team A (tests): R16, R18, R25, R19b

Format per step: time, what/why, command, result, failures (symptom, root cause, how found, fix, check).

## 11:31 Step 0: baselines and analysis (no code changed yet)
- Command: /tmp/A/sim.sh rand_644814.npz /tmp/A/base14 1 30 (gen_tc + mk_tests + Verilator build + run); same for v2_P2_H48_A2.npz.
- Result before any change: 14-class words=4,930,621 (stream.hex 19.7 MB), SUMMARY checks=1997 failures=0 (scores=1805 checkpoints=191), Verilator run 6.4 s.
  Digits: words=3,605,441, checks=1584 failures=0, 4.2 s. These are the "before" sizes for the 30 percent growth budget (limit 6.4M words on 14-class).
- Analysis done by reading RTL (derived before measuring; to be confirmed by planted runs):
  - rsync releases nrst after edge 2 after rst_n rises; in_q is live from edge 3. dsync (mode) is also held in reset by nrst, so mode_s is valid only after edge 4.
  - Real host convention assumed: first clock edge samples byte 1. So START may be byte 3 (2 idle bytes) in hardwired mode, byte 4 (3 idle bytes) in streamed mode (mode pin = 1). Mode pin change without reset: 1 idle byte.
  - Existing tb op 5/6 convention (phantom idle first edge) would need 1 less idle byte; new tb op 9 will model the real-host convention.
  - best only affects result (checkpoint), not score monitor, so best mutant needs >=10 symbols whose result changes.
  - Stale acc1 only affects neuron 0 of class 0, so the abort tests must be chosen where the golden model says the stale value changes a score (check with a no-clear model).

## 11:41 Steps 1-4: code written, 14-class RTL run passes, top-bit and acc1 mutants caught
Changed (all in Team A files):
- tc_model.py: clip_model(q, thr_lim) and stream_streamed(x, q, thr_lim, start_first) so streamed thresholds can reach -512..511 (default 300 unchanged); TracedModel (min/max of every signed field, byte()/step() behaviour unchanged); NoClearAcc1Model (planted-bug golden model, START keeps acc1). tc_model.py self-check still 400/0.
- tb/tb_tc.v: op 8 (reset pulse with stopped clock, clock stays stopped), op 9 (first clock edge samples the byte = real host), POWERUP_NOCLK param (power-up reset with no clock). Compiles in Verilator; Icarus compile checked in the gate run at the end.
- mk_tests.py: new sections 3c limits (R16), 5b abort tests (R25), 6c startup boundary (R18), fuzz_hw_long (R25), per-section table, range line, no silent image fallback (R19b).
Command: /tmp/A/sim.sh rand_644814.npz /tmp/A/n14 1 30
Result 14-class: words=6,065,041 (+23 percent vs 4,930,621), checks=3193 failures=0 (scores=2764 checkpoints=428), run 14 s, generation ~90 s.
Range line: n1[-192..192] n2[-511..511] score[-511..511] best[-511..511] acc2[-508..508] thr_stream[-512..511] bias_stream[-508..508] thr_hw[-21..66] bias_hw[-27..34].
Mutants (14-class, Verilator, one edit each on a copy of tc_core.v, pattern asserted to match once):
  score_top_bit 637 failures; acc2_top_bit 687; best_top_bit 100; stream_bias_top_bit 759; stream_thr_top_bits 581; start_no_clear_acc1 37 (all CAUGHT, all >=10).
Planted no-clear-acc1 model changes the output in 25/40 abort tests (all 22 directed ones by construction, min |stale acc1| = 8).
Failures hit on the way:
- mk_tests "no streamed abort point found": symptom SystemExit after 90 s. Root cause: small random models with 30 percent nonzero weights rarely give |acc1| >= 10 mid-neuron at random cut points. Found by reading the loop conditions. Fix: directed streamed models use T1 70 percent +1 and pixels 2..3, threshold |acc1|>=8. Check: generator now finds all 10.
- first mutant script run: equivalent mutants "COMPILE FAIL" because the run directory name contained parentheses (make/verilator path). Not an RTL problem. Fix: rename to *_equiv.

## 12:12 Steps 5-6: digits build, equivalent mutants, start-up boundary table, R19b
- Digits build (Verilator): words=4,625,354 (+28 percent vs 3,605,441), checks=2732 failures=0 (scores=2304 checkpoints=427). Planted-bug no-clear model changes output in 26/40 abort tests.
- Digits mutants: score_top_bit 637, acc2_top_bit 687, best_top_bit 100, stream_bias_top_bit 759, stream_thr_top_bits 581, start_no_clear_acc1 41 failures (all CAUGHT). The by-design-equivalent ones (hw bias top bit, hw threshold top bits, acc1 top bit) SURVIVE on both builds with 0 failures, as expected (acc1 within +-192, hardwired bias/threshold small).
- Same mutant counts on 14-class and digits for the limit mutants because the limit models are streamed and identical (same seed); the build only changes the hardwired part.
- Start-up boundary table (mk_startup.py + Verilator RTL, 14-class build, real-host model: first clock edge samples byte 1), failures per case/idle count:
  pwr_hw (power-up, no clock): idle 0 FAIL(1), 1 FAIL(1), 2 pass, 3 pass, 4 pass
  rst_hw (stopped-clock reset mid-run, hardwired): 0 FAIL(1), 1 FAIL(1), 2 pass, 3, 4 pass
  rst_stream (mode pin 1, START first): 0,1,2 FAIL(2), 3 pass, 4 pass
  mode_h2s (pin change, clock stopped): 0 FAIL(2), 1 pass, 2.. pass
  mode_s2h: 0 FAIL(1), 1 pass, 2.. pass
  This matches the edge derivation: hardwired START = byte 3 (2 idle), streamed START = byte 4 (3 idle: dsync is also held in reset by nrst, so mode_s is valid only after edge 4), mode change alone = 1 idle. The requested planted case (0 idle after stopped-clock reset) FAILS (rst_hw idle=0: 1 failure; pwr_hw idle=0: 1 failure).
  Commands: python3 mk_startup.py model.npz WD case n; verilator ...; /tmp/A/startup_table.sh.
- R19b check: forcing sys.modules['sklearn']=None gives "ERROR: cannot load the digits dataset ... Refusing to fall back to random images silently." and exit 1; with sklearn the run prints "image set: digits test split (30 images)"; a NI != 64 model prints "random pixels".
- Failure: first equivalent-mutant run printed COMPILE FAIL for one run; cause was my mutant script racing a killed earlier background run in the same directory (I had to kill a duplicate run because the script ignored its filter argument: python3 - $WD did not pass the extra args). Fixed (pass "$@"), rerun: SURVIVED with 0 failures.

## 12:46 Step 7: gate-level run and final regression
- Command: ./run_tb.sh rand_644814.npz /tmp/A/WDG 1 30 gate (Icarus, synth_tc.sh netlist + ge_cells.v). Result: SUMMARY checks=3193 failures=0 (scores=2764 checkpoints=428), PASS. Icarus compile of tb_tc.v (iverilog -g2005) OK. Gate run took roughly 35 minutes of wall time on the shared 2 cores (synthesis a few minutes, the rest Icarus simulation of 6.07M words; I did not time it exactly). This is a large increase vs the old 4.9M-word run, relevant for Team B's R21 time target.
- Final Verilator regression after the last code change (startup_cases refactor): digits words=4,625,354 checks=2732 failures=0; 14-class words=6,065,041 checks=3193 failures=0 (same vectors the gate run used).
- Size vs before: 14-class 4,930,621 -> 6,065,041 words (+23 percent); digits 3,605,441 -> 4,625,354 (+28 percent). Checks 1997 -> 3193 and 1584 -> 2732.
- Not done / caveats: (1) the real-host edge model (first clock edge samples byte 1) is an assumption about the ESP32 LCD peripheral; if the host has a phantom first edge the minimums drop by one. (2) -512 is included as a threshold (spec range), so the printed range is -512..511 not exactly +-511. (3) Vector generation takes ~90 s (pure Python), up from ~25 s. (4) run_tb.sh, check_all.sh are untouched (not my files); mutants.py from Team B should add the start_no_clear_acc1 mutant if it is not already in its list.
