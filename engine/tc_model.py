"""Golden model of the v2 ternary engine (tc_core) and the ESP32-side stream builder.

This file is the single definition of the byte protocol, the weight formats and the
engine arithmetic. The RTL generator (gen_tc.py) and the testbench generator
(mk_tests.py) both import it.

Byte protocol (one byte per clock on din[7:0], sampled when cs_n = 0)
  din[7:6] = 00  IDLE   no operation
  din[7:6] = 01  STEP   din[1:0] pixel (0..3), din[3:2] w1, din[5:4] w2
                         (w1/w2 used only in streamed mode; w2 only on the last
                          pixel step of each hidden neuron)
  din[7:6] = 10  THR    th_sr <= {th_sr[23:0], din[5:0]}   (30-bit shift register,
                         3 signed 10-bit thresholds t0,t1,t2, MSB first)
  din[7:6] = 11  CMD    din[5:4] = 00 control: din[3:0] = 0001 START, 0010 ABORT
                         din[5:4] = 01 CFG   : cfg_sr  <= {cfg_sr[11:0], din[3:0]}
                                     cfg_sr = {ni_last[5:0], h_last[5:0], c_last[3:0]}
                         din[5:4] = 10 BIAS  : bias_sr <= {bias_sr[5:0], din[3:0]}
                                     (10 bits; send 3 bytes, top 2 bits drop)
                         din[5:4] = 11 reserved (no operation)

Ternary 2-bit code: 01 = +1, 11 = -1, 00 and 10 = 0.

Modes (mode pin, latched at START)
  0 hardwired: built-in weights, thresholds and biases; fixed size NI x H x C.
  1 streamed : weights arrive in STEP bytes, thresholds in THR bytes, biases in
               BIAS bytes; sizes from cfg_sr (up to 64 x 64 x 16).

Run order: for c in classes, for j in hidden, for i in inputs: one STEP byte.
  - Thresholds of neuron j must be in th_sr before its last STEP (streamed mode).
  - acc2 starts at bias(class 0) at START and at bias(c+1) when class c ends;
    in streamed mode bias_sr must therefore hold the bias of class c+1 before the
    last STEP of class c (and the bias of class 0 before START).
Outputs: busy, result[3:0] (argmax, ties -> lowest class), score[9:0] (score of the
class that just finished), score_tgl (toggles each time score updates).
"""
import numpy as np

P, A, K = 2, 2, 3            # pixel bits, activation bits, thresholds per neuron
ZW = 10                      # width of acc1, thresholds, acc2, scores (signed)
NI_MAX, H_MAX, C_MAX = 64, 64, 16
ZMIN, ZMAX = -(1 << (ZW - 1)), (1 << (ZW - 1)) - 1

TERN_CODE = {1: 0b01, -1: 0b11, 0: 0b00}


def tern_dec(code):
    return 1 if code == 0b01 else (-1 if code == 0b11 else 0)


def to_s(v, w=ZW):
    v &= (1 << w) - 1
    return v - (1 << w) if v >> (w - 1) else v


def to_u(v, w=ZW):
    assert -(1 << (w - 1)) <= v < (1 << (w - 1)), f"value {v} does not fit {w} bits"
    return v & ((1 << w) - 1)


def clip_model(q, thr_lim=300):
    """Clip thresholds to +-thr_lim (default 300). Safe: |z1| <= 64*3 = 192 < 511, so
    a threshold beyond +-300 behaves the same as any larger one. Limit tests pass
    thr_lim=512 to keep streamed thresholds at the spec limits (+-511, -512)."""
    q = dict(q)
    q['thr'] = np.clip(np.asarray(q['thr'], dtype=int), -thr_lim, thr_lim - (thr_lim == 512))
    q['b2'] = np.asarray(q.get('b2', np.zeros(q['T2'].shape[1], int)), dtype=int)
    NI, H = q['T1'].shape
    C = q['T2'].shape[1]
    assert NI <= NI_MAX and H <= H_MAX and C <= C_MAX
    assert np.all(np.abs(q['b2']) + H * 3 <= ZMAX), "bias too large for 10-bit scores"
    return q


def reference(q, X):
    """Plain integer network (same as train_v2.infer), returns (pred, z2)."""
    z1 = X.astype(int) @ q['T1']
    a = (z1[:, :, None] >= q['thr'][None]).sum(2)
    z2 = a @ q['T2'] + q['b2']
    return np.argmax(z2, axis=1), z2


class TcModel:
    """Cycle-free model: processes one din byte at a time, exactly as tc_core does
    on the clock edge after the byte is registered."""

    def __init__(self, hw):
        self.hw = clip_model(hw)        # hardwired model
        self.reset()

    def reset(self):
        self.busy = 0; self.result = 0; self.score = 0; self.score_tgl = 0
        self.mode_r = 0; self.i = self.j = self.c = 0
        self.acc1 = 0; self.acc2 = 0; self.best = 0
        self.th_sr = 0; self.cfg_sr = 0; self.bias_sr = 0

    # hardwired lookups (what tc_wrom.v computes)
    def hw_w1(self, j, i):
        T1 = self.hw['T1']
        return TERN_CODE[int(T1[i, j])] if i < T1.shape[0] and j < T1.shape[1] else 0

    def hw_w2(self, c, j):
        T2 = self.hw['T2']
        return TERN_CODE[int(T2[j, c])] if j < T2.shape[0] and c < T2.shape[1] else 0

    def hw_th(self, j):
        thr = self.hw['thr']
        return [int(t) for t in thr[j]] if j < thr.shape[0] else [0, 0, 0]

    def hw_bias(self, c):
        b2 = self.hw['b2']
        return int(b2[c]) if c < len(b2) else 0

    def lasts(self):
        if self.mode_r:
            return (self.cfg_sr >> 10) & 63, (self.cfg_sr >> 4) & 63, self.cfg_sr & 15
        NI, H = self.hw['T1'].shape
        return NI - 1, H - 1, self.hw['T2'].shape[1] - 1

    def bias_of(self, mode, c):
        return to_s(self.bias_sr & 0x3FF) if mode else self.hw_bias(c)

    def byte(self, b, mode_pin=0, cs_n=0):
        if cs_n:
            return
        typ = (b >> 6) & 3
        if typ == 0b10:
            self.th_sr = ((self.th_sr << 6) | (b & 63)) & ((1 << 30) - 1)
        elif typ == 0b11:
            sub, arg = (b >> 4) & 3, b & 15
            if sub == 0b00:
                if arg == 0b0001 and not self.busy:
                    self.mode_r = mode_pin
                    self.busy = 1; self.i = self.j = self.c = 0
                    self.acc1 = 0; self.acc2 = self.bias_of(mode_pin, 0)
                    self.result = 0; self.best = 0
                elif arg == 0b0010:
                    self.busy = 0
            elif sub == 0b01:
                self.cfg_sr = ((self.cfg_sr << 4) | arg) & 0xFFFF
            elif sub == 0b10:
                self.bias_sr = ((self.bias_sr << 4) | arg) & 0x3FF
        elif typ == 0b01 and self.busy:
            self.step(b)

    def step(self, b):
        px = b & 3
        if self.mode_r:
            w1, w2 = (b >> 2) & 3, (b >> 4) & 3
            th = [to_s((self.th_sr >> s) & 0x3FF) for s in (20, 10, 0)]
        else:
            w1, w2 = self.hw_w1(self.j, self.i), self.hw_w2(self.c, self.j)
            th = self.hw_th(self.j)
        ni_l, h_l, c_l = self.lasts()
        n1 = to_s(self.acc1 + tern_dec(w1) * px)
        if self.i != ni_l:
            self.acc1 = n1; self.i = (self.i + 1) & 63
            return
        a = sum(1 for t in th if n1 >= t)
        n2 = to_s(self.acc2 + tern_dec(w2) * a)
        self.acc1 = 0; self.i = 0
        if self.j != h_l:
            self.acc2 = n2; self.j = (self.j + 1) & 63
            return
        self.score = n2; self.score_tgl ^= 1
        if self.c == 0 or n2 > self.best:
            self.best = n2; self.result = self.c
        self.j = 0
        if self.c == c_l:
            self.busy = 0; self.acc2 = 0
        else:
            self.c = (self.c + 1) & 15
            self.acc2 = self.bias_of(self.mode_r, self.c)


# ---------------------------------------------------------------- stream builder
def cmd(sub, arg):
    return 0xC0 | (sub << 4) | (arg & 15)

START, ABORT, IDLE = cmd(0, 1), cmd(0, 2), 0x00


def cfg_bytes(ni, h, c):
    v = ((ni - 1) << 10) | ((h - 1) << 4) | (c - 1)
    return [cmd(1, (v >> s) & 15) for s in (12, 8, 4, 0)]


def bias_bytes(b):
    v = to_u(int(b)) & 0xFFF
    return [cmd(2, (v >> s) & 15) for s in (8, 4, 0)]


def thr_bytes(ts):
    v = (to_u(int(ts[0])) << 20) | (to_u(int(ts[1])) << 10) | to_u(int(ts[2]))
    return [0x80 | ((v >> s) & 63) for s in (24, 18, 12, 6, 0)]


def step_byte(px, w1=0, w2=0):
    return 0x40 | (w2 << 4) | (w1 << 2) | (px & 3)


def stream_hardwired(x, NI, H, C):
    """Bytes for one symbol in hardwired mode (mode pin = 0). x: NI pixels 0..3."""
    s = [START]
    for c in range(C):
        for j in range(H):
            s += [step_byte(int(x[i])) for i in range(NI)]
    return s


def stream_streamed(x, q, thr_lim=300, start_first=False):
    """Bytes for one symbol in streamed mode (mode pin = 1) running model q.
    start_first: put START first, then CFG (needs bias(class 0) == 0 or already
    loaded). Used by the start-up tests, where START must be the first byte."""
    q = clip_model(q, thr_lim)
    T1, T2, thr, b2 = q['T1'], q['T2'], q['thr'], q['b2']
    NI, H = T1.shape; C = T2.shape[1]
    if start_first:
        assert int(b2[0]) == 0, "start_first needs bias(class 0) = 0"
        s = [START] + cfg_bytes(NI, H, C)
    else:
        s = cfg_bytes(NI, H, C) + bias_bytes(b2[0]) + [START]
    for c in range(C):
        if c + 1 < C:
            s += bias_bytes(b2[c + 1])          # bias of the next class, early
        for j in range(H):
            s += thr_bytes(thr[j])
            for i in range(NI):
                w2 = TERN_CODE[int(T2[j, c])] if i == NI - 1 else 0
                s.append(step_byte(int(x[i]), TERN_CODE[int(T1[i, j])], w2))
    return s


class TracedModel(TcModel):
    """TcModel plus min/max tracking of every signed field (test reporting only;
    behaviour of byte()/step() is unchanged)."""
    FIELDS = ('n1', 'acc1', 'n2', 'acc2', 'score', 'best', 'thr_stream', 'thr_hw',
              'bias_stream', 'bias_hw')

    def __init__(self, hw):
        self.rng = {k: [None, None] for k in self.FIELDS}
        super().__init__(hw)

    def rec(self, k, v):
        r = self.rng[k]
        r[0] = v if r[0] is None or v < r[0] else r[0]
        r[1] = v if r[1] is None or v > r[1] else r[1]

    def bias_of(self, mode, c):
        v = super().bias_of(mode, c)
        self.rec('bias_stream' if mode else 'bias_hw', v)
        return v

    def step(self, b):
        px = b & 3
        if self.mode_r:
            w1, w2 = (b >> 2) & 3, (b >> 4) & 3
            th = [to_s((self.th_sr >> s) & 0x3FF) for s in (20, 10, 0)]
        else:
            w1, w2 = self.hw_w1(self.j, self.i), self.hw_w2(self.c, self.j)
            th = self.hw_th(self.j)
        n1 = to_s(self.acc1 + tern_dec(w1) * px)
        self.rec('n1', n1)
        if self.i == self.lasts()[0]:
            for t in th:
                self.rec('thr_stream' if self.mode_r else 'thr_hw', t)
            n2 = to_s(self.acc2 + tern_dec(w2) * sum(1 for t in th if n1 >= t))
            self.rec('n2', n2)
        super().step(b)
        self.rec('acc1', self.acc1); self.rec('acc2', self.acc2)
        self.rec('score', self.score); self.rec('best', self.best)


class NoClearAcc1Model(TcModel):
    """Planted-bug model: START does not clear acc1 (the RTL mutant that deletes
    'acc1 <= 0' in the START branch). Used by mk_tests to choose abort points where
    that bug would change an output."""

    def byte(self, b, mode_pin=0, cs_n=0):
        keep = self.acc1
        will_start = (not cs_n) and (b >> 4) == 0xC and (b & 15) == 1 and not self.busy
        super().byte(b, mode_pin, cs_n)
        if will_start:
            self.acc1 = keep


def run(model, stream, mode_pin):
    """Feed a stream; return (result, list of class scores)."""
    scores = []; tgl = model.score_tgl
    for b in stream:
        model.byte(b, mode_pin)
        if model.score_tgl != tgl:
            tgl = model.score_tgl; scores.append(model.score)
    return model.result, scores


def rand_model(NI, H, C, rng, bias=True):
    T1 = rng.choice([-1, 0, 1], size=(NI, H), p=[.3, .4, .3])
    T2 = rng.choice([-1, 0, 1], size=(H, C), p=[.3, .4, .3])
    z = max(2, int(NI * 3 * 0.35))
    thr = np.sort(rng.integers(-z // 3, z, size=(H, K)), axis=1)
    b2 = rng.integers(-40, 41, size=C) if bias else np.zeros(C, int)
    return dict(T1=T1, T2=T2, thr=thr, b2=b2, P=P, A=A)


if __name__ == '__main__':
    # self-check: the byte-level model must equal the plain network in both modes
    rng = np.random.default_rng(7)
    fails = 0; checks = 0
    for trial in range(40):
        NI, H, C = int(rng.integers(1, 65)), int(rng.integers(1, 65)), int(rng.integers(1, 17))
        q = clip_model(rand_model(NI, H, C, rng))
        X = rng.integers(0, 4, size=(5, NI))
        pred, z2 = reference(q, X)
        for n in range(5):
            m = TcModel(q)
            r, sc = run(m, stream_hardwired(X[n], NI, H, C), 0)
            checks += 1; fails += (r != pred[n]) or (sc != list(z2[n]))
            m2 = TcModel(rand_model(64, 48, 14, rng))   # different built-in model
            r, sc = run(m2, stream_streamed(X[n], q), 1)
            checks += 1; fails += (r != pred[n]) or (sc != list(z2[n]))
    print(f"golden self-check: {checks} checks, {fails} failures")
    raise SystemExit(1 if fails else 0)
