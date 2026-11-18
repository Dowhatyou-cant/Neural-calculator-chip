"""Prove the equivalence step (equiv.sh) can FAIL. Three planted bugs, each must
make equiv.sh exit non-zero; the unchanged pair must pass.
  1. one gate of the measured netlist changed (NAND2 -> NOR2)
  2. one reachable threshold +1 in the model (RTL regenerated, netlist not)
  3. one layer-1 weight flipped in the model (RTL regenerated, netlist not)
usage: python3 equiv_selftest.py model.npz work_dir     exit 0 iff control passes and all 3 are detected
"""
import sys, os, re, subprocess, numpy as np
import tc_model as M, gen_tc

HERE = os.path.dirname(os.path.abspath(__file__))
npz, wd = sys.argv[1], os.path.abspath(sys.argv[2]); os.makedirs(wd, exist_ok=True)
q = M.clip_model(dict(np.load(npz)))
gen_tc.build(q, f'{wd}/rtl')
r = subprocess.run([f'{HERE}/synth_tc.sh', f'{wd}/rtl', f'{wd}/synth'], capture_output=True, text=True)
assert r.returncode == 0, r.stderr


def eq(rtl, gate):
    r = subprocess.run([f'{HERE}/equiv.sh', rtl, gate], capture_output=True, text=True)
    unp = re.findall(r"Found (\d+) unproven \$equiv cells in 'equiv_status", r.stdout) or \
        re.findall(r'and (\d+) are unproven', r.stdout)
    return r.returncode, (unp[-1] if unp else '?')


rows = []
rc, u = eq(f'{wd}/rtl', f'{wd}/synth_gate.v')
rows.append(('control (unchanged)', rc == 0, f'rc={rc}, unproven={u}'))

# 1. one gate changed (first NAND2 whose change is detected; a few tried in case it is dead logic)
net = open(f'{wd}/synth_gate.v').read()
cells = [m.start() for m in re.finditer(r'\n  NAND2 ', net)]
for k in (len(cells) // 2, len(cells) // 3, 5, 100, 1):
    if k >= len(cells): continue
    p = cells[k]
    mut = net[:p] + '\n  NOR2 ' + net[p + len('\n  NAND2 '):]
    open(f'{wd}/gate_changed.v', 'w').write(mut)
    rc, u = eq(f'{wd}/rtl', f'{wd}/gate_changed.v')
    if rc != 0: break
rows.append(('one gate changed (NAND2->NOR2)', rc != 0, f'rc={rc}, unproven={u}'))

# 2. threshold +1, 3. weight flip: RTL from changed model, netlist from original
import mutants_data as D
for name, fn in (('threshold +1', D.threshold_plus_one), ('one weight flipped', D.flip_one_weight)):
    d = f'{wd}/rtl_{name.replace(" ", "_").replace("+", "p")}'
    gen_tc.build(fn(q), d)
    rc, u = eq(d, f'{wd}/synth_gate.v')
    rows.append((name, rc != 0, f'rc={rc}, unproven={u}'))

bad = 0
for n, ok, s in rows:
    print(f"{'OK  ' if ok else 'BAD '} {n:34s} {s}"); bad += not ok
print(f"equiv self-test: {len(rows)} rows, {bad} problems (control must PASS, each planted bug must FAIL the step)")
raise SystemExit(1 if bad else 0)
