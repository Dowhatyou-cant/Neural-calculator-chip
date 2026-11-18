"""Exhaustive check of the generated hardwired-weight block (tc_wrom.v).

Every stored layer-1 weight, layer-2 weight, threshold and bias is read back
through the block's ports, for every index (out-of-range indices must read 0),
and compared with the model. Runs on the RTL and on a gate netlist of tc_wrom.
NOTE (review R17): the "gate" half synthesises tc_wrom SEPARATELY (its own yosys
run, tc_wrom as top). It is NOT the netlist synth_tc.sh measures; that exact
netlist is proven equal to the RTL by equiv.sh. This half is a sanity check only.
This catches ANY wrong hardwired value, including thresholds no input can
reach (review R14).

usage: python3 wrom_check.py model.npz work_dir [rtl_dir]
  rtl_dir: check this tc_wrom.v instead of one generated from model.npz
           (mutants.py uses this to check mutated data against the true model)
Exit code != 0 on any mismatch.
"""
import sys, os, subprocess, numpy as np
import tc_model as M, gen_tc

HERE = os.path.dirname(os.path.abspath(__file__))


def expected(q):
    m = M.TcModel(q); v = []
    for j in range(64):
        for i in range(64):
            v.append(m.hw_w1(j, i))
    for c in range(16):
        for j in range(64):
            v.append(m.hw_w2(c, j))
    for j in range(64):
        t = m.hw_th(j)
        v.append((M.to_u(t[0]) << 20) | (M.to_u(t[1]) << 10) | M.to_u(t[2]))
    for c in range(16):
        v.append(M.to_u(m.hw_bias(c)))
    return v


def sim(wd, src, tag):
    out = subprocess.run(['iverilog', '-g2005', '-o', f'{wd}/{tag}.vvp', f'{HERE}/tb/tb_wrom.v'] + src,
                         capture_output=True, text=True)
    if out.returncode:
        return 2, out.stderr[-300:]
    r = subprocess.run(['vvp', '-n', f'{tag}.vvp'], cwd=wd, capture_output=True, text=True)
    s = [l for l in r.stdout.splitlines() if l.startswith('SUMMARY')]
    return r.returncode, (s[-1] if s else r.stdout[-200:])


def check(q, wd, rtl_dir=None, gate=True):
    wd = os.path.abspath(wd); os.makedirs(wd, exist_ok=True)
    open(f'{wd}/wrom_exp.hex', 'w').write("\n".join(f"{x:08x}" for x in expected(q)) + "\n")
    if rtl_dir is None:
        rtl_dir = f'{wd}/rtl'; gen_tc.build(q, rtl_dir)
    results = [('rtl',) + sim(wd, [f'{rtl_dir}/tc_wrom.v'], 'wrom_rtl')]
    if gate:
        lib = f'{HERE}/ge.lib'
        y = subprocess.run(['yosys', '-q', '-p',
                            f"read_verilog {rtl_dir}/tc_wrom.v; synth -top tc_wrom -flatten; "
                            f"abc -liberty {lib}; opt_clean; write_verilog -noattr -noexpr {wd}/wrom_gate.v"],
                           capture_output=True, text=True)
        if y.returncode:
            results.append(('gate', 2, y.stderr[-300:]))
        else:
            results.append(('gate',) + sim(wd, [f'{wd}/wrom_gate.v', f'{HERE}/ge_cells.v'], 'wrom_gate'))
    return results


if __name__ == '__main__':
    q = M.clip_model(dict(np.load(sys.argv[1])))
    res = check(q, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    bad = 0
    for kind, rc, s in res:
        print(f"wrom {kind}{' (separately synthesised tc_wrom, not the measured netlist)' if kind == 'gate' else ''}: {s}"); bad += rc != 0
    raise SystemExit(1 if bad else 0)
