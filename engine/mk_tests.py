"""Build test vectors for tb_tc.v from the golden model.

usage: python3 mk_tests.py model.npz outdir [seed] [n_img] [n_boundary]
  n_boundary: max threshold-boundary images in hardwired mode (default 40)
Writes outdir/stream.hex, exp_res.hex, exp_score.hex, tb_params.vh.

stream.hex words are 12 bits {op[3:0], data[7:0]}:
  0 drive din=data, cs_n=0 for one clock
  1 drive din=data, cs_n=1 for one clock (must be ignored)
  2 set mode pin = data[0] (no clock)
  3 checkpoint: compare {busy, result} with the next exp_res word (no clock)
  4 reset pulse: rst_n low for one clock, then high
  5 stop the clock (after the next falling edge)
  6 restart the clock
  7 checkpoint with the clock stopped (compare without waiting for an edge)
  f end of test
Every class score the RTL produces (score_tgl toggles) is compared, in order,
with exp_score.hex.
"""
import sys, os, numpy as np
import tc_model as M



def must_import_train_v2():
    """Digit images need train_v2 (scikit-learn). No silent fallback (review R19b)."""
    try:
        import train_v2 as T
    except ImportError as e:
        sys.exit(f"ERROR: cannot load the digits dataset: {e}\n"
                 "mk_tests.py needs scikit-learn (pip install scikit-learn) for NI == 64 "
                 "models. Refusing to fall back to random images silently.")
    return T


class Builder:
    def __init__(self, hw, powerup_idle=2):
        self.m = M.TracedModel(hw); self.words = []; self.res = []; self.scores = []
        self.mode = 0; self.tgl = 0; self.checks = 0; self.semantic_fail = 0
        self.first_pending = True          # power-up with no clock: next byte is op 9
        self.sec = {}; self.cur = None; self.runs_total = 0
        self.begin('powerup'); self.idle(powerup_idle)

    def begin(self, name):
        self.cur = self.sec.setdefault(name, [0, 0, 0])   # words, scores, completed runs

    def _after(self):
        if self.m.score_tgl != self.tgl:
            self.tgl = self.m.score_tgl; self.scores.append(self.m.score); self.cur[1] += 1

    def byte(self, b, cs_n=0):
        if self.first_pending:
            assert not cs_n, "first byte after a clock restart must have cs_n = 0"
            self.words.append((9 << 8) | b); self.first_pending = False
        else:
            self.words.append(((1 if cs_n else 0) << 8) | b)
        self.cur[0] += 1
        was_busy = self.m.busy
        self.m.byte(b, self.mode, cs_n); self._after()
        if was_busy and not self.m.busy and not cs_n and b != M.ABORT:
            self.cur[2] += 1; self.runs_total += 1                  # run completed

    def bytes(self, bs, rng=None, idle_p=0.0):
        for b in bs:
            if rng is not None and idle_p and rng.random() < idle_p:
                for _ in range(int(rng.integers(1, 4))):
                    if rng.random() < 0.5:
                        self.byte(int(rng.integers(0, 256)), cs_n=1)   # ignored junk
                    else:
                        self.byte(M.IDLE)
            self.byte(b)

    def idle(self, n):
        for _ in range(n): self.byte(M.IDLE)

    def set_mode(self, v):
        self.mode = v; self.words.append((2 << 8) | v); self.idle(4)

    def check(self):
        self.idle(2)
        self.words.append(3 << 8)
        self.res.append((self.m.busy << 4) | self.m.result); self.checks += 1

    def stopped_clock_symbol(self, stream, mode, n_idle):
        if self.mode != mode: self.set_mode(mode)
        self.bytes(stream[:-1])
        before = (self.m.busy << 4) | self.m.result
        self.byte(stream[-1])
        after = (self.m.busy << 4) | self.m.result
        self.idle(n_idle)
        self.words += [5 << 8, 7 << 8, 6 << 8]       # clock off, check, clock on
        self.res.append(before if n_idle == 0 else after); self.checks += 1
        self.check()                                  # clock running again: final state

    def reset(self):
        self.words.append(4 << 8); self.m.reset(); self.tgl = 0; self.idle(4)

    # ---- real-host start-up helpers (review R18). The clock is stopped; the next
    # byte is emitted as op 9 and is sampled by the very first clock edge.
    def stop_clock(self):
        self.words.append(5 << 8); self.first_pending = True

    def reset_stopped(self):
        self.words.append(8 << 8); self.m.reset(); self.tgl = 0; self.first_pending = True

    def mode_pin_stopped(self, v):
        assert self.first_pending, "clock must be stopped"
        self.mode = v; self.words.append((2 << 8) | v)

    def symbol(self, stream, mode, expect=None, exp_scores=None, rng=None, idle_p=0.0):
        if self.mode != mode: self.set_mode(mode)
        n0 = len(self.scores)
        self.bytes(stream, rng, idle_p); self.check()
        if expect is not None:
            ok = (self.m.result == expect) and (self.scores[n0:] == list(exp_scores))
            self.semantic_fail += (not ok)

    def symbol_noset(self, stream, mode, expect, exp_scores):
        """symbol() that must not insert idle bytes for a mode change (boundary tests)."""
        assert self.mode == mode, "mode pin must already be set"
        self.symbol(stream, mode, expect, exp_scores)


# ------------------------------------------------------------ R16 limit models
def thr_triple(rng, kind, ni):
    LO = [-512, -511, -400, -300, -256, -200, -193]      # always satisfied: |z1| <= 192
    HI = [193, 200, 255, 256, 300, 400, 511]             # never satisfied
    if kind == 'lo': return sorted(int(v) for v in rng.choice(LO, 3))
    if kind == 'hi': return sorted(int(v) for v in rng.choice(HI, 3))
    return sorted(int(v) for v in rng.integers(-(3 * ni) // 2, 3 * ni + 1, 3))


def limit_model(rng, ni, h, c, t1kind, t2kind, thr_mix, offsets=None, signs=None):
    """Streamed model at the spec limits: |bias| <= 511 - 3h, thresholds up to +-511,
    all-(+-1) weights. t2kind 'ext': class column = sign*ones, bias = sign*(lim - d)."""
    lim = 511 - 3 * h
    if t1kind == 'pos': T1 = np.ones((ni, h), int)
    elif t1kind == 'neg': T1 = -np.ones((ni, h), int)
    elif t1kind == 'mixed': T1 = np.tile(np.where(np.arange(h) % 2 == 0, 1, -1), (ni, 1))
    else: T1 = rng.choice([-1, 0, 1], size=(ni, h))
    T2 = np.zeros((h, c), int); b2 = np.zeros(c, int)
    for k in range(c):
        if t2kind == 'ext':
            sg = signs[k] if signs is not None else int(rng.choice([-1, 1]))
            d = offsets[k] if offsets is not None else int(rng.choice([0, 0, 0, 1, 5, 50]))
            T2[:, k] = sg
            b2[k] = (sg if rng.random() < 0.8 or offsets is not None else -sg) * max(0, lim - d)
        else:
            T2[:, k] = rng.choice([-1, 0, 1], size=h)
            b2[k] = int(rng.choice([lim, -lim, lim - 1, 1 - lim, 0, int(rng.integers(-lim, lim + 1))]))
    thr = np.array([thr_triple(rng, str(rng.choice(thr_mix)), ni) for _ in range(h)])
    return dict(T1=T1, T2=T2, thr=thr, b2=b2, P=M.P, A=M.A)


def limit_tests(B, rng):
    """Streamed models at the limits; golden model tracks the ranges reached."""
    B.begin('limits')
    specs = []                                            # (model, images)
    all3 = lambda ni: np.full(ni, 3)
    # full size, all-+-1 weights, all-3 pixels: acc1 reaches +-192, scores +-511
    for t1, mix in [('pos', ['lo']), ('neg', ['lo']), ('mixed', ['lo', 'hi']), ('rand', ['lo'])]:
        q = limit_model(rng, 64, 48, 4, t1, 'ext', mix, offsets=[0, 0, 0, 70],
                        signs=[1, -1, 1, 1] if t1 != 'neg' else [-1, 1, -1, -1])
        specs.append((q, [all3(64), rng.integers(0, 4, 64)]))
    # ties at large positive / large negative scores (earliest and later classes)
    for h in (48, 8, 2):
        for signs, offs in [([1, 1, 1, 1, 1], [0, 0, 9, 0, 0]), ([1, 1, 1, 1, 1], [5, 0, 3, 0, 8]),
                            ([-1] * 5, [0, 0, 0, 0, 0]), ([-1] * 5, [7, 0, 7, 0, 7]),
                            ([1, -1, -1, 1, 1], [0, 0, 0, 0, 0])]:
            ni = 64 if h == 48 else 12
            q = limit_model(rng, ni, h, 5, 'pos', 'ext', ['lo'], offsets=offs, signs=signs)
            specs.append((q, [all3(ni)]))
    # smaller hidden layers allow larger biases (|bias| <= 511 - 3H)
    for h in (1, 2, 3, 5, 8, 13, 24, 32, 40):
        for rep in range(2):
            ni = int(rng.integers(3, 65)); c = int(rng.integers(2, 7))
            q = limit_model(rng, ni, h, c, str(rng.choice(['pos', 'neg', 'mixed', 'rand'])),
                            'ext', ['lo', 'hi', 'lo', 'mid'])
            specs.append((q, [all3(ni), rng.integers(0, 4, ni), np.zeros(ni, int)]))
    # random models with extreme biases/thresholds, image-sensitive (mid thresholds)
    for rep in range(30):
        h = int(rng.choice([1, 2, 4, 7, 12, 20, 33, 48])); ni = int(rng.integers(2, 65))
        c = int(rng.integers(2, 7))
        q = limit_model(rng, ni, h, c, str(rng.choice(['pos', 'mixed', 'rand'])),
                        str(rng.choice(['ext', 'rand'])), ['lo', 'hi', 'mid', 'mid'])
        specs.append((q, [all3(ni), rng.integers(0, 4, ni), rng.integers(0, 4, ni)]))
    for q, imgs in specs:
        q = M.clip_model(q, 512)
        for x in imgs:
            pred, z2 = M.reference(q, x[None, :])
            B.symbol(M.stream_streamed(x, q, 512), 1, pred[0], z2[0])
    return len(specs)


# ------------------------------------------------------------ R25 abort / restart
def run_scratch(model, stream, mode):
    for b in stream: model.byte(b, mode)
    return model


def abort_tests(B, rng, hw, X, pred, z2, NI, H, C):
    """Abort at a point, then START at once. acc1 must be non-zero at the abort point
    (asserted with the golden model). 'directed' points are additionally chosen so that
    the no-clear-acc1 planted-bug model gives a different score/result (asserted)."""
    info = dict(hw_rand=0, hw_dir=0, st_rand=0, st_dir=0, min_stale_dir=999, bug_hit=0, bug_total=0)
    n_img = len(X)
    T1 = hw['T1']

    def pair():
        a = int(rng.integers(0, n_img)); b = int(rng.integers(0, n_img))
        return a, b

    # ---- hardwired
    B.begin('abort_hw'); B.set_mode(0)
    full_left = 1
    for t in range(8):                                    # random points over the whole run
        for _try in range(200):
            a, b = pair(); sa = M.stream_hardwired(X[a], NI, H, C)
            k = int(rng.integers(2, len(sa)))
            g = run_scratch(M.TcModel(hw), sa[:k], 0)
            if g.busy and g.acc1 != 0: break
        else: raise SystemExit("no non-zero abort point found")
        info['hw_rand'] += 1
        sb = M.stream_hardwired(X[b], NI, H, C)
        B.bytes(sa[:k]);
        if t % 2: B.check()
        B.byte(M.ABORT)
        if t % 3 == 1: B.check()
        if full_left:
            full_left -= 1; B.symbol(sb, 0, pred[b], z2[b])
        else:
            B.bytes(sb[:1 + NI * H]); B.byte(M.ABORT); B.check()
        bad = run_scratch(M.NoClearAcc1Model(hw), sa[:k] + [M.ABORT] + sb[:1 + NI * H], 0)
        gd = run_scratch(M.TcModel(hw), sa[:k] + [M.ABORT] + sb[:1 + NI * H], 0)
        info['bug_total'] += 1; info['bug_hit'] += (bad.score != gd.score)
    for t in range(12):                                   # directed: large stale partial sum
        for _try in range(4000):
            a, b = pair(); sa = M.stream_hardwired(X[a], NI, H, C)
            nrn = int(rng.integers(0, min(2 * H, H + 8))); r = int(rng.integers(1, NI))
            k = 1 + nrn * NI + r
            j = nrn % H
            stale = int(sum(int(T1[i, j]) * int(X[a][i]) for i in range(r)))
            if abs(stale) < 20: continue
            sb = M.stream_hardwired(X[b], NI, H, C)
            body = sa[:k] + [M.ABORT] + sb[:1 + NI * H]
            g = run_scratch(M.TcModel(hw), sa[:k], 0)
            assert g.busy and g.acc1 == stale and stale != 0, "golden acc1 != analytic stale"
            gd = run_scratch(M.TcModel(hw), body, 0)
            bad = run_scratch(M.NoClearAcc1Model(hw), body, 0)
            if (bad.score, bad.result) != (gd.score, gd.result): break
        else: raise SystemExit("no detectable directed abort point found")
        info['hw_dir'] += 1; info['min_stale_dir'] = min(info['min_stale_dir'], abs(stale))
        info['bug_total'] += 1; info['bug_hit'] += 1
        B.bytes(sa[:k]); B.byte(M.ABORT)
        B.bytes(sb[:1 + NI * H]); B.byte(M.ABORT); B.check()
    # ---- streamed (small models, whole second symbol)
    B.begin('abort_streamed'); B.set_mode(1)
    for t in range(20):
        directed = t >= 10
        for _try in range(4000):
            ni, h, c = int(rng.integers(6, 30)), int(rng.integers(3, 9)), int(rng.integers(2, 5))
            q = M.rand_model(ni, h, c, rng)
            if directed: q['T1'] = rng.choice([-1, 0, 1], size=(ni, h), p=[.1, .2, .7])
            q = M.clip_model(q)
            xa, xb = rng.integers(0, 4, ni), rng.integers(0, 4, ni)
            if directed: xa = rng.integers(2, 4, ni)
            sa = M.stream_streamed(xa, q); sb = M.stream_streamed(xb, q)
            k = int(rng.integers(sa.index(M.START) + 2, len(sa)))
            g = run_scratch(M.TcModel(hw), sa[:k], 1)
            if not (g.busy and g.acc1 != 0): continue
            if directed and abs(g.acc1) < 8: continue
            body = sa[:k] + [M.ABORT] + sb
            gd = run_scratch(M.TcModel(hw), body, 1)
            bad = run_scratch(M.NoClearAcc1Model(hw), body, 1)
            hit = (bad.score, bad.result) != (gd.score, gd.result)
            if directed and not hit: continue
            break
        else: raise SystemExit("no streamed abort point found")
        info['st_dir' if directed else 'st_rand'] += 1
        if directed: info['min_stale_dir'] = min(info['min_stale_dir'], abs(g.acc1))
        info['bug_total'] += 1; info['bug_hit'] += hit
        B.bytes(sa[:k]); B.byte(M.ABORT)
        if t % 2: B.check()
        pr, zr = M.reference(q, xb[None, :])
        B.symbol(sb, 1, pr[0], zr[0])
    return info


# ------------------------------------------------------------ R18 start-up cases
def hw_class0(B, sb, NI, H):
    """START + the first class only, then ABORT (keeps the start-up tests short;
    a lost START shows as busy=0 / missing scores)."""
    assert B.mode == 0
    B.bytes(sb[:1 + NI * H]); B.byte(M.ABORT); B.check()


def startup_cases(B, rng, hw, X, pred, z2, NI, H, C, n_hw, n_st, n_mode, only=None):
    """Stopped-clock reset and mode change at the idle-byte boundary (real-host model:
    the first clock edge samples byte 1). Edges after rst_n rises: in_q is live from
    edge 3 (rsync), mode_s only from edge 4 (dsync also held in reset), so START is
    byte 3 in hardwired mode (2 idle) and byte 4 in streamed mode (3 idle).
    only: subset of {'rst_hw','rst_stream','mode_h2s','mode_s2h'} (default all)."""
    want = lambda n: only is None or n in only
    if want('rst_hw'):          # partial run, reset with the clock stopped, n_hw idle, START
        B.set_mode(0)
        s = M.stream_hardwired(X[0], NI, H, C); B.bytes(s[:len(s) // 3])
        B.reset_stopped(); B.idle(n_hw)
        hw_class0(B, M.stream_hardwired(X[1], NI, H, C), NI, H)
    if want('rst_stream'):      # mode pin held at 1 across the reset, START first (b2[0] = 0)
        q = M.rand_model(10, 4, 3, rng); q['b2'][0] = 0; q = M.clip_model(q)
        xr = rng.integers(0, 4, 10); pr, zr = M.reference(q, xr[None, :])
        B.set_mode(1)
        s = M.stream_streamed(xr, q); B.bytes(s[:len(s) // 2])
        B.reset_stopped(); B.idle(n_st)
        B.symbol_noset(M.stream_streamed(xr, q, start_first=True), 1, pr[0], zr[0])
    if want('mode_h2s'):        # hardwired -> streamed, clock stopped, no reset
        q = M.clip_model(M.rand_model(12, 5, 4, rng)); xr = rng.integers(0, 4, 12)
        pr, zr = M.reference(q, xr[None, :])
        s = M.stream_streamed(xr, q); i0 = s.index(M.START)   # CFG+BIAS loaded earlier
        B.set_mode(0); B.bytes(s[:i0]); B.idle(2); B.stop_clock(); B.mode_pin_stopped(1)
        B.idle(n_mode); B.symbol_noset(s[i0:], 1, pr[0], zr[0])
    if want('mode_s2h'):        # streamed -> hardwired
        B.set_mode(1); B.idle(2); B.stop_clock(); B.mode_pin_stopped(0); B.idle(n_mode)
        hw_class0(B, M.stream_hardwired(X[2], NI, H, C), NI, H)


# ------------------------------------------------------------ fuzz
def fuzz_short(B, rng):
    for blk in range(30):
        B.set_mode(int(rng.integers(0, 2)))
        for _ in range(3000):
            r = rng.random()
            if r < 0.6: b = M.step_byte(int(rng.integers(0, 4)), int(rng.integers(0, 4)), int(rng.integers(0, 4)))
            elif r < 0.7: b = M.START
            elif r < 0.72: b = M.ABORT
            elif r < 0.85: b = 0x80 | int(rng.integers(0, 64))
            elif r < 0.92: b = M.cmd(1, int(rng.integers(0, 16)))
            else: b = int(rng.integers(0, 256))
            B.byte(b, cs_n=int(rng.random() < 0.1))
        B.check()


def fuzz_hw_long(B, rng, steps_per_run, n_blocks=3):
    """Hardwired fuzz that can finish a run: ~1 ABORT per block (placed early), no
    random ABORT bytes, 5 percent cs_n. Each block runs until a run completes."""
    B.begin('fuzz_hw_long'); B.set_mode(0)
    for blk in range(n_blocks):
        abort_at = int(rng.integers(100, 3000)); n = 0; done_before = B.cur[2]; done_at = None
        limit = int(steps_per_run / 0.8 * 3) + 5000
        while n < limit:
            r = rng.random()
            if r < 0.86: b = M.step_byte(int(rng.integers(0, 4)), int(rng.integers(0, 4)), int(rng.integers(0, 4)))
            elif r < 0.88: b = M.START
            elif r < 0.92: b = 0x80 | int(rng.integers(0, 64))
            elif r < 0.95: b = M.cmd(1, int(rng.integers(0, 16)))
            elif r < 0.97: b = M.cmd(2, int(rng.integers(0, 16)))
            else:
                b = int(rng.integers(0, 256))
                if b == M.ABORT: b = M.IDLE
            if n == abort_at: b = M.ABORT
            B.byte(b, cs_n=int(rng.random() < 0.05)); n += 1
            if n > abort_at and B.cur[2] > done_before:
                done_at = n if done_at is None else done_at
            if done_at is not None and n > done_at + 200: break
        B.check()
    assert B.cur[2] > 0, "hardwired fuzz completed no run"


def main():
    npz, out = sys.argv[1], sys.argv[2]
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    n_img = int(sys.argv[4]) if len(sys.argv) > 4 else 40
    n_bnd = int(sys.argv[5]) if len(sys.argv) > 5 else 40
    assert n_img >= 3, "n_img must be >= 3 (sections 4-6 reuse images 0-2)"
    rng = np.random.default_rng(seed)
    hw = M.clip_model(dict(np.load(npz)))
    NI, H = hw['T1'].shape; C = hw['T2'].shape[1]
    B = Builder(hw, powerup_idle=2)      # power-up reset with no clock, 2 idle bytes

    # images: digits test split when the model has 64 inputs, else random. No silent
    # fallback: a missing scikit-learn is an error (review R19b).
    if NI == 64:
        T = must_import_train_v2()
        try:
            _, _, _, _, Xte, yte = T.data(2, 0)
        except Exception as e:
            sys.exit(f"ERROR: cannot load the digits dataset ({type(e).__name__}: {e})")
        if len(Xte) < n_img:
            sys.exit(f"ERROR: digits test split has {len(Xte)} images, n_img={n_img}")
        X = Xte[:n_img].astype(int); image_set = f"digits test split ({n_img} images)"
    else:
        X = rng.integers(0, 4, (n_img, NI)); image_set = f"random pixels ({n_img} images, NI={NI})"
    print(f"image set: {image_set}")
    pred, z2 = M.reference(hw, X)

    # 1. hardwired mode
    B.begin('1_hw_images')
    for n in range(n_img):
        B.symbol(M.stream_hardwired(X[n], NI, H, C), 0, pred[n], z2[n])
    # 1b. hardwired mode with random pixels, so every hardwired weight is exercised
    #     (real digit images leave ~13 corner pixels always 0, hiding their weights)
    B.begin('1b_hw_random')
    Xr = rng.integers(0, 4, (max(8, n_img // 3), NI)); pr, zr = M.reference(hw, Xr)
    for n in range(len(Xr)):
        B.symbol(M.stream_hardwired(Xr[n], NI, H, C), 0, pr[n], zr[n])
    # 1c. threshold-boundary images: neuron sums exactly ON and just BELOW each
    #     hardwired threshold (review R14). Stored values are checked exhaustively
    #     by wrom_check.py; these runs prove the datapath compares are right there.
    B.begin('1c_hw_boundary')
    import boundary
    Xb, missed, unreach = boundary.boundary_images(hw, seed=seed)
    Xb = Xb[:n_bnd]
    if len(Xb):
        pb, zb = M.reference(hw, Xb)
        for n in range(len(Xb)):
            B.symbol(M.stream_hardwired(Xb[n], NI, H, C), 0, pb[n], zb[n])
    B.boundary_info = (len(Xb), len(missed), len(unreach))
    # 2. streamed mode running the same model (must agree with hardwired)
    B.begin('2_streamed_same_model')
    for n in range(n_img // 2):
        B.symbol(M.stream_streamed(X[n], hw), 1, pred[n], z2[n])
    # 3. streamed mode, random models and sizes, incl. edge sizes, idle/junk bytes
    B.begin('3_streamed_random')
    shapes = [(1, 1, 1), (64, 64, 16), (64, 1, 16), (1, 64, 2), (7, 5, 3)]
    shapes += [(int(rng.integers(1, 65)), int(rng.integers(1, 33)), int(rng.integers(1, 17)))
               for _ in range(15)]
    for (ni, h, c) in shapes:
        q = M.clip_model(M.rand_model(ni, h, c, rng))
        Xr = rng.integers(0, 4, (2, ni)); pr, zr = M.reference(q, Xr)
        for n in range(2):
            B.symbol(M.stream_streamed(Xr[n], q), 1, pr[n], zr[n], rng, idle_p=0.05)
    # 3b. directed ties: models whose class columns repeat, so scores tie exactly
    B.begin('3b_ties')
    for (ni, h, c) in [(16, 8, 6), (64, 12, 16), (5, 3, 4)]:
        q = M.rand_model(ni, h, c, rng)
        base = q['T2'][:, :max(1, c // 3)]
        q['T2'] = np.tile(base, (1, c))[:, :c]
        q['b2'] = np.tile(q['b2'][:base.shape[1]], c)[:c]
        q = M.clip_model(q)
        Xr = rng.integers(0, 4, (3, ni)); pr, zr = M.reference(q, Xr)
        for n in range(3):
            B.symbol(M.stream_streamed(Xr[n], q), 1, pr[n], zr[n])
    # 3c. R16: streamed models AT the spec limits (biases, thresholds, scores)
    n_lim = limit_tests(B, rng)
    # 4. hardwired with idle/junk bytes and stray THR/CFG/BIAS bytes mid-run
    B.begin('4_hw_junk')
    for n in range(3):
        s = M.stream_hardwired(X[n], NI, H, C)
        s2 = []
        for b in s:
            s2.append(b)
            if rng.random() < 0.01:
                s2.append(int(rng.choice([0x80 | int(rng.integers(0, 64)),
                                          M.cmd(1, int(rng.integers(0, 16))),
                                          M.cmd(2, int(rng.integers(0, 16))),
                                          M.START, 0xF5])))
        B.symbol(s2, 0, pred[n], z2[n], rng, idle_p=0.05)
    # 5. abort mid-run, checkpoint busy, then a clean run; STEP bytes while idle
    B.begin('5_abort_basic')
    s = M.stream_hardwired(X[0], NI, H, C)
    B.set_mode(0); B.bytes(s[:len(s) // 3]); B.check()            # busy = 1
    B.byte(M.ABORT); B.check()                                     # busy = 0
    B.bytes([M.step_byte(3, 1, 1)] * 50); B.check()                # ignored
    B.symbol(M.stream_hardwired(X[1], NI, H, C), 0, pred[1], z2[1])
    # 5b. R25: abort at many points, START at once (stale acc1 must be cleared)
    ab = abort_tests(B, rng, hw, X, pred, z2, NI, H, C)
    # 6. reset mid-run, then a clean run
    B.begin('6_reset_midrun')
    B.set_mode(0)
    B.bytes(s[:len(s) // 2]); B.reset(); B.check()
    B.symbol(M.stream_hardwired(X[2], NI, H, C), 0, pred[2], z2[2])
    # 6b. stopped clock: the host stops clocking after the last STEP plus n idle bytes.
    #     n = 0 -> last STEP never executes (busy stays 1); n >= 1 -> result is final.
    B.begin('6b_stopped_clock')
    for n_idle in (0, 1, 2):
        B.stopped_clock_symbol(M.stream_hardwired(X[n_idle], NI, H, C), 0, n_idle)
    q = M.clip_model(M.rand_model(10, 4, 3, rng)); xr = rng.integers(0, 4, 10)
    B.stopped_clock_symbol(M.stream_streamed(xr, q), 1, 1)
    # 6c. R18: reset / mode change with the clock stopped, at the idle-byte boundary
    #     (min: 2 idle hardwired, 3 idle streamed, 1 idle for a mode change), then
    #     one more case with a margin of +1 idle byte.
    B.begin('6c_startup_boundary')
    startup_cases(B, rng, hw, X, pred, z2, NI, H, C, n_hw=2, n_st=3, n_mode=1)
    startup_cases(B, rng, hw, X, pred, z2, NI, H, C, n_hw=3, n_st=4, n_mode=2)
    #     reset with the clock stopped, state check (busy=0, result=0) after many idles
    s = M.stream_hardwired(X[0], NI, H, C); B.set_mode(0); B.bytes(s[:len(s) // 3])
    B.reset_stopped(); B.idle(6); B.check()
    B.symbol_noset(M.stream_hardwired(X[1], NI, H, C), 0, pred[1], z2[1])
    # 7. fuzz: random bytes, random mode and cs_n (golden vs RTL only)
    B.begin('7_fuzz_short'); fuzz_short(B, rng)
    fuzz_hw_long(B, rng, NI * H * C)

    B.idle(2); B.words.append(0xF << 8)
    os.makedirs(out, exist_ok=True)
    open(f'{out}/stream.hex', 'w').write("\n".join(f"{w:03x}" for w in B.words) + "\n")
    open(f'{out}/exp_res.hex', 'w').write("\n".join(f"{w:02x}" for w in B.res) + "\n")
    open(f'{out}/exp_score.hex', 'w').write("\n".join(f"{M.to_u(s):03x}" for s in B.scores) + "\n")
    open(f'{out}/tb_params.vh', 'w').write(
        f"localparam N_WORDS = {len(B.words)};\nlocalparam N_RES = {len(B.res)};\n"
        f"localparam N_SCORE = {len(B.scores)};\nlocalparam POWERUP_NOCLK = 1;\n")
    print("section                   words   scores  completed_runs")
    for k, (w, sc, ru) in B.sec.items():
        print(f"  {k:24s}{w:8d}{sc:8d}{ru:8d}")
    r = B.m.rng
    print("ranges (golden model, min..max): " + "  ".join(
        f"{k}[{v[0]}..{v[1]}]" for k, v in r.items() if v[0] is not None))
    print(f"limit models: {n_lim}; abort tests: hw random {ab['hw_rand']}, hw directed {ab['hw_dir']}, "
          f"streamed random {ab['st_rand']}, streamed directed {ab['st_dir']}; "
          f"planted no-clear-acc1 bug changes the output in {ab['bug_hit']}/{ab['bug_total']} "
          f"(min |stale acc1| in directed tests: {ab['min_stale_dir']})")
    assert ab['bug_hit'] >= 10 and ab['min_stale_dir'] != 0
    print(f"words={len(B.words)} checkpoints={len(B.res)} scores={len(B.scores)} "
          f"semantic_failures={B.semantic_fail} boundary_images={B.boundary_info[0]} "
          f"(reachable targets left uncovered by the search: {B.boundary_info[1]}, "
          f"unreachable: {B.boundary_info[2]})")
    raise SystemExit(1 if B.semantic_fail else 0)


if __name__ == '__main__':
    main()
