"""Mutation test: every planted bug must make a check FAIL; the unchanged design
must PASS. Covers the hand-written core AND the generated weight data.

Rules (from reviews R13/R14/R16/R19/R27):
  - each mutant changes exactly ONE place (asserted exactly once), so its name is the bug tested;
  - run it on EVERY build that is claimed (check_all.sh does this);
  - a mutant that cannot change behaviour on this build (e.g. a bias bug when all
    hardwired biases are 0) is declared EQUIVALENT with the reason. A declared-
    equivalent mutant that FAILS (or does not even compile) is a CONTRADICTION:
    the declaration is wrong or the mutant is not what it claims. It is a problem.
  - verdicts: CAUGHT / SURVIVED / EQUIVALENT / CONTRADICTION / NEEDS_LIMIT_TESTS /
    BROKEN (does not compile or hangs). SURVIVED, CONTRADICTION, BROKEN and a
    failed control are problems (exit code 1). NEEDS_LIMIT_TESTS is reported
    separately and is not a problem.
  - data mutants: the table check (wrom_check.py) catches them by construction,
    so it is shown as its own column; the REAL sensitivity is the number of
    failing end-to-end checks. Under THIN_BELOW (10) fails the mutant is flagged
    THIN (a warning, not a failure).
  - the end-to-end runs use Verilator (SIM=icarus selects Icarus: much slower).

usage: python3 mutants.py model.npz work_dir [seed] [n_img] [n_boundary]
Environment: SIM=verilator|icarus; MUTANTS_DECLARE_EQUIVALENT=name[,name] declares
those core mutants equivalent (used ONLY to demonstrate the CONTRADICTION verdict).
Exit code != 0 on any problem.
"""
import sys, os, re, subprocess, numpy as np
import tc_model as M, gen_tc, wrom_check
from mutants_data import DATA

HERE = os.path.dirname(os.path.abspath(__file__))
THIN_BELOW = 10
SIM = os.environ.get('SIM', 'verilator')
TIMEOUT = 900
npz, wd = sys.argv[1], os.path.abspath(sys.argv[2])
seed = sys.argv[3] if len(sys.argv) > 3 else '9'
n_img = sys.argv[4] if len(sys.argv) > 4 else '3'
n_bnd = sys.argv[5] if len(sys.argv) > 5 else '12'
os.makedirs(wd, exist_ok=True)
subprocess.run([sys.executable, f'{HERE}/mk_tests.py', npz, wd, seed, n_img, n_bnd], check=True)
hw = M.clip_model(dict(np.load(npz)))
biases_all_zero = not np.any(hw['b2'])

# Core mutants that only the spec-limit tests (Team A, R16) can catch. Until those are merged
# they are reported as NEEDS_LIMIT_TESTS when they survive. Opus empties this list at integration.
NEEDS_LIMIT_TESTS = []   # emptied at integration (17 Nov): Team A's limit tests (mk_tests.py section 3c) must catch these

# core mutants: (name, exact text, replacement, equivalent-if reason or None)
CORE = [
    # R25 (added at integration on Team A's advice): START must clear the layer-1 sum; before v0.4 this survived every test
    ('start_no_clear_acc1', "      acc1[9:0]   <= 10'b0;\n      acc2[9:0]   <= bias[9:0];",
     "      acc2[9:0]   <= bias[9:0];", None),
    ('tie_to_higher_class', "($signed(n2[9:0]) > $signed(best[9:0]))",
     "($signed(n2[9:0]) >= $signed(best[9:0]))", None),
    ('bias_of_wrong_class', "assign idx_bc[3:0] = do_start ? 4'd0 : c[3:0] + 4'd1;",
     "assign idx_bc[3:0] = do_start ? 4'd0 : c[3:0];",
     "all hardwired biases are 0, so every class's bias reads the same" if biases_all_zero else None),
    ('minus_one_decode', "(w1[1:0] == 2'b11) ? acc1[9:0] - px[9:0]",
     "(w1[1:0] == 2'b10) ? acc1[9:0] - px[9:0]", None),
    ('cs_n_ignored', "in_q[7:0] <= cs_n ? 8'b0 : din[7:0];", "in_q[7:0] <= din[7:0];", None),
    ('threshold_compare_gt', "wire ge1 = ($signed(n1[9:0]) >= $signed(th[19:10]));",
     "wire ge1 = ($signed(n1[9:0]) > $signed(th[19:10]));", None),
    # "top bit dropped" (R16, review3_tools/x.py): bit 9 replaced by bit 8, i.e. a 9-bit signed value
    ('best_top_bit', "best[9:0]   <= n2[9:0];", "best[9:0]   <= {n2[8], n2[8:0]};", None),
    ('acc2_top_bit', "acc2[9:0] <= n2[9:0];", "acc2[9:0] <= {n2[8], n2[8:0]};", None),
    ('score_top_bit', "score[9:0] <= n2[9:0];", "score[9:0] <= {n2[8], n2[8:0]};", None),
    ('stream_bias_top_bit', "bmode ? bias_sr[9:0] :", "bmode ? {bias_sr[8], bias_sr[8:0]} :", None),
    ('stream_thr_top_bits', "mode_r ? th_sr[29:0] :",
     "mode_r ? {th_sr[28],th_sr[28:20],th_sr[18],th_sr[18:10],th_sr[8],th_sr[8:0]} :", None),
]
# MUTANTS_SUBSET=name,name restricts the run to those mutants (check_all.sh --quick only; the
# headline then says "SUBSET"). The full check never sets it.
subset = [n for n in os.environ.get('MUTANTS_SUBSET', '').split(',') if n]
known = [c[0] for c in CORE] + [d[0] for d in DATA]
for n in subset:
    assert n in known, f"MUTANTS_SUBSET: unknown mutant {n}"
if subset:
    CORE = [c for c in CORE if c[0] in subset]; DATA = [d for d in DATA if d[0] in subset]
declared = [n for n in os.environ.get('MUTANTS_DECLARE_EQUIVALENT', '').split(',') if n]
for n in declared:
    assert n in known, f"MUTANTS_DECLARE_EQUIVALENT: unknown core mutant {n}"


def fails_of(summary):
    m = re.search(r'failures=(\d+)', summary or '')
    return int(m.group(1)) if m else None


def e2e(name, rtl_dir):
    """returns (rc, summary line); rc None = did not compile, 'timeout' = hung"""
    files = [f'{rtl_dir}/{f}' for f in sorted(os.listdir(rtl_dir)) if f.endswith('.v')]
    tb = f'{HERE}/tb/tb_tc.v'
    if SIM == 'icarus':
        c = subprocess.run(['iverilog', '-g2005', '-I', wd, '-o', f'{wd}/{name}.vvp', tb] + files,
                           capture_output=True, text=True)
        cmd = ['vvp', '-n', f'{name}.vvp']
    else:
        c = subprocess.run(['verilator', '--binary', '--timing', '-Wno-fatal', '-Wno-lint', f'-I{wd}',
                            '--top-module', 'tb_tc', '--Mdir', f'{wd}/obj_{name}', '-o', 'sim', tb] + files,
                           capture_output=True, text=True)
        cmd = [f'{wd}/obj_{name}/sim']
    if c.returncode:
        return None, (c.stderr or c.stdout)[-300:]
    try:
        r = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'timeout', f'no result after {TIMEOUT}s'
    summ = [l for l in r.stdout.splitlines() if l.startswith('SUMMARY')]
    if SIM != 'icarus':
        subprocess.run(['rm', '-rf', f'{wd}/obj_{name}'])
    return r.returncode, summ[-1] if summ else r.stdout[-200:]


rows = []   # (name, verdict, fails, table, text)
base = f'{wd}/rtl_control'; gen_tc.build(hw, base)
rc, s = e2e('control', base)
rows.append(('control (unchanged)', 'PASS' if rc == 0 else 'FAILED', fails_of(s), None, s))
wr = wrom_check.check(hw, f'{wd}/wrom_control', base, gate=False)
rows.append(('control table check', 'PASS' if wr[0][1] == 0 else 'FAILED', None, None, wr[0][2]))

for name, old, new, equiv in CORE:
    if name in declared:
        equiv = "DECLARED EQUIVALENT FOR THE CONTRADICTION DEMO (MUTANTS_DECLARE_EQUIVALENT)"
    d = f'{wd}/rtl_{name}'; gen_tc.build(hw, d)
    p = f'{d}/tc_core.v'; t = open(p).read()
    n = t.count(old)
    assert n == 1, f"mutant {name}: pattern found {n} times, must be exactly once"
    open(p, 'w').write(t.replace(old, new))
    rc, s = e2e(name, d)
    if equiv:
        if rc == 0:
            verdict = 'EQUIVALENT'; s = f"{s}  [equivalent on this build: {equiv}]"
        else:
            verdict = 'CONTRADICTION'
            s = f"{s}  [declared equivalent ({equiv}) but the run {'did not compile' if rc is None else 'failed'}]"
    elif rc in (None, 'timeout'):
        verdict = 'BROKEN'
    elif rc != 0:
        verdict = 'CAUGHT'
    else:
        verdict = 'NEEDS_LIMIT_TESTS' if name in NEEDS_LIMIT_TESTS else 'SURVIVED'
    rows.append((f'core: {name}', verdict, fails_of(s), None, s))

for name, fn in DATA:
    d = f'{wd}/rtl_{name}'; gen_tc.build(fn(hw), d)
    tab = wrom_check.check(hw, f'{wd}/wrom_{name}', d, gate=False)[0]
    rc, s = e2e(name, d)
    n = fails_of(s)
    table = 'CAUGHT' if tab[1] != 0 else 'SURVIVED'
    thin = n is None or n < THIN_BELOW
    verdict = 'BROKEN' if rc in (None, 'timeout') else table
    rows.append((f'data: {name}', verdict, n, table, f"table: {tab[2]} | end-to-end: {s}" + ("  THIN" if thin else "")))

bad = 0
print(f"{'':5s}{'verdict':18s}{'mutant':30s}{'e2e fails':>10s}  {'table check':12s}detail")
for name, verdict, n, table, s in rows:
    ok = verdict in ('PASS', 'CAUGHT', 'EQUIVALENT', 'NEEDS_LIMIT_TESTS')
    bad += not ok
    print(f"{'OK  ' if ok else 'BAD '} {verdict:18s}{name:30s}{'' if n is None else n:>10}  {table or '-':12s}{s}")
core = [r for r in rows if r[0].startswith('core:')]
data = [r for r in rows if r[0].startswith('data:')]
cnt = [r for r in core if r[1] not in ('EQUIVALENT',)]
caught = sum(r[1] == 'CAUGHT' for r in core)
needs = [r[0][6:] for r in core if r[1] == 'NEEDS_LIMIT_TESTS']
equivs = sum(r[1] == 'EQUIVALENT' for r in core)
nd = [r[2] for r in data if r[2] is not None]
thin = [r[0][6:] for r in data if r[2] is None or r[2] < THIN_BELOW]
core_thin = [r[0][6:] for r in core if r[1] == 'CAUGHT' and r[2] is not None and r[2] < THIN_BELOW]
print(f"HEADLINE{' (SUBSET: quick mode, not the full set)' if subset else ''} {os.path.basename(npz)}: core mutants caught {caught}/{len(cnt)} "
      f"({equivs} declared equivalent, not counted; {len(needs)} NEEDS_LIMIT_TESTS: {', '.join(needs) or '-'}); "
      f"data mutants end-to-end fails {min(nd) if nd else '?'}-{max(nd) if nd else '?'} "
      f"(table check catches all {sum(r[3] == 'CAUGHT' for r in data)}/{len(data)}); "
      f"THIN (<{THIN_BELOW}): {', '.join(thin) or 'none'}; "
      f"core caught by <{THIN_BELOW} fails (warning): {', '.join(core_thin) or 'none'}")
print(f"mutation test on {os.path.basename(npz)}: {len(rows)} rows, {bad} problems "
      f"(a SURVIVED mutant, CONTRADICTION, BROKEN run or FAILED control is a problem)")
raise SystemExit(1 if bad else 0)
