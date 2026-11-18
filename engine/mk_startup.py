"""Single start-up case with a chosen number of idle bytes (review R18). Used to show
where the boundary is and that too few idle bytes FAIL (planted-bug check).

usage: python3 mk_startup.py model.npz outdir case n_idle
  case: pwr_hw   power-up reset with no clock, n_idle idle bytes, hardwired START
        rst_hw   mid-run reset with the clock stopped, n_idle, hardwired START
        rst_stream  same, mode pin 1, streamed symbol with START first
        mode_h2s / mode_s2h  mode pin change with the clock stopped, n_idle, START
Real-host model: the first clock edge samples byte 1 (tb op 9)."""
import sys, os, numpy as np
import tc_model as M, mk_tests as T


def main():
    npz, out, case, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    rng = np.random.default_rng(3)
    hw = M.clip_model(dict(np.load(npz)))
    NI, H = hw['T1'].shape; C = hw['T2'].shape[1]
    X = rng.integers(0, 4, (3, NI)); pred, z2 = M.reference(hw, X)
    B = T.Builder(hw, powerup_idle=(n if case == 'pwr_hw' else 3))
    B.begin(case)
    if case == 'pwr_hw':
        T.hw_class0(B, M.stream_hardwired(X[0], NI, H, C), NI, H)
    else:
        T.startup_cases(B, rng, hw, X, pred, z2, NI, H, C, n, n, n, only=[case])
    B.idle(2); B.words.append(0xF << 8)
    os.makedirs(out, exist_ok=True)
    open(f'{out}/stream.hex', 'w').write("\n".join(f"{w:03x}" for w in B.words) + "\n")
    open(f'{out}/exp_res.hex', 'w').write("\n".join(f"{w:02x}" for w in B.res) + "\n")
    open(f'{out}/exp_score.hex', 'w').write("\n".join(f"{M.to_u(s):03x}" for s in B.scores) + "\n")
    open(f'{out}/tb_params.vh', 'w').write(
        f"localparam N_WORDS = {len(B.words)};\nlocalparam N_RES = {len(B.res)};\n"
        f"localparam N_SCORE = {len(B.scores)};\nlocalparam POWERUP_NOCLK = 1;\n")


if __name__ == '__main__':
    main()
