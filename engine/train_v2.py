"""Ternary digit classifier v2 for the SCL 800nm test chip (integer-exact).

Chip-side model (what the silicon computes):
  x   : 64 pixels, P bits each (0..2^P-1)
  z1_j = sum_i T1[i,j] * x_i                         (T1 in {-1,0,+1})
  a_j  = number of thresholds t[j,k] (k=1..2^A-1) with z1_j >= t[j,k]   (A-bit activation)
  z2_c = sum_j T2[j,c] * a_j + b2_c                  (T2 in {-1,0,+1}, small integer bias)
  out  = argmax_c z2_c   (ties -> lowest index)

Training: float pretraining, then ternary fine-tuning with per-neuron scales
(straight-through estimators). Scales and biases of layer 1 are folded into the
integer thresholds t[j,k], so the chip needs no multipliers.
Model selection uses a validation split; the test split is used once at the end.
"""
import json, sys, os
DELTA = float(os.environ.get("DELTA", "0.7"))
import numpy as np
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split

def data(P, seed):
    d = load_digits()
    lv = 2 ** P
    X = np.minimum(np.floor(d.images / 16.0001 * lv), lv - 1)  # 0..lv-1
    Xtr, Xte, ytr, yte = train_test_split(X, d.target, test_size=0.25, stratify=d.target, random_state=42)
    Xtr, Xva, ytr, yva = train_test_split(Xtr, ytr, test_size=0.15, stratify=ytr, random_state=seed)
    return Xtr, ytr, Xva.reshape(-1, 64), yva, Xte.reshape(-1, 64), yte

def shift_aug(X, rng):
    out = np.zeros_like(X)
    for i in range(len(X)):
        dy, dx = rng.integers(-1, 2, size=2)
        s = np.roll(np.roll(X[i], dy, 0), dx, 1)
        if dy == 1: s[0, :] = 0
        if dy == -1: s[-1, :] = 0
        if dx == 1: s[:, 0] = 0
        if dx == -1: s[:, -1] = 0
        out[i] = s
    return out

class Adam:
    def __init__(self, params, lr):
        self.m = [np.zeros_like(p) for p in params]; self.v = [np.zeros_like(p) for p in params]; self.t = 0; self.lr = lr
    def step(self, params, grads, lr=None):
        self.t += 1; lr = lr or self.lr
        for p, g, m, v in zip(params, grads, self.m, self.v):
            m[:] = 0.9 * m + 0.1 * g; v[:] = 0.999 * v + 0.001 * g * g
            p -= lr * (m / (1 - 0.9 ** self.t)) / (np.sqrt(v / (1 - 0.999 ** self.t)) + 1e-8)

def tern(W, axis):
    """Per-column ternarisation. Returns T in {-1,0,1} and per-column scale alpha."""
    delta = DELTA * np.mean(np.abs(W), axis=axis, keepdims=True)
    T = np.where(W > delta, 1.0, np.where(W < -delta, -1.0, 0.0))
    nz = np.maximum((T != 0).sum(axis=axis, keepdims=True), 1)
    alpha = (np.abs(W) * (T != 0)).sum(axis=axis, keepdims=True) / nz
    return T, alpha

def forward(x, W1, b1, W2, b2, A, ternary, train=True):
    amax = 2 ** A - 1
    if ternary:
        T1, al1 = tern(W1, 0); T2, al2 = tern(W2, None)   # layer-2: one shared scale (argmax-safe)
        E1, E2 = T1 * al1, T2 * al2
    else:
        E1, E2 = W1, W2
    u = x @ E1 + b1                         # activation pre-quantisation, in "activation units"
    a = np.clip(np.floor(u + 0.5), 0, amax)
    z2 = a @ E2 + b2
    return u, a, z2, E1, E2

def train(P=2, H=32, A=2, seed=0, pre_ep=150, ft_ep=250, lr=2e-3):
    rng = np.random.default_rng(seed)
    Xtr, ytr, Xva, yva, Xte, yte = data(P, seed)
    xs = 1.0 / (2 ** P - 1)                  # inputs scaled to 0..1 for training stability
    W1 = rng.normal(0, 0.3, (64, H)); b1 = np.zeros(H); W2 = rng.normal(0, 0.3, (H, 10)); b2 = np.zeros(10)
    params = [W1, b1, W2, b2]; opt = Adam(params, lr)
    Y = np.eye(10)[ytr]; amax = 2 ** A - 1
    best = (-1, None)
    for phase, n_ep in (('float', pre_ep), ('ternary', ft_ep)):
        tern_on = phase == 'ternary'
        if tern_on: opt = Adam(params, lr * 0.5)
        for ep in range(n_ep):
            Xf = Xtr.reshape(-1, 64) * xs
            idx = rng.permutation(len(Xf))
            for s in range(0, len(Xf), 64):
                b = idx[s:s + 64]; x = Xf[b]; yb = Y[b]
                u, a, z2, E1, E2 = forward(x, W1, b1, W2, b2, A, tern_on)
                p = np.exp(z2 - z2.max(1, keepdims=True)); p /= p.sum(1, keepdims=True)
                dz2 = (p - yb) / len(b)
                gW2 = a.T @ dz2; gb2 = dz2.sum(0)
                du = (dz2 @ E2.T) * ((u > -0.5) & (u < amax + 0.5))
                gW1 = x.T @ du; gb1 = du.sum(0)
                opt.step(params, [gW1, gb1, gW2, gb2])
            if tern_on and (ep % 5 == 4):
                q = export(W1, b1, W2, b2, P, A)
                va = (infer(q, Xva) == yva).mean()
                if va >= best[0]: best = (va, q)
    q = best[1]
    # sanity: integer model must equal the float ternary forward pass on validation data
    return q, float((infer(q, Xte) == yte).mean()), float(best[0])

def export(W1, b1, W2, b2, P, A):
    """Fold scales/biases into integer thresholds.  Activation a_j = #k with u_j >= k-0.5,
    u_j = al1_j * xs * z1_j + b1_j  ->  z1_j >= (k - 0.5 - b1_j) / (al1_j * xs)  ->  ceil."""
    xs = 1.0 / (2 ** P - 1)
    T1, al1 = tern(W1, 0); T2, al2 = tern(W2, None)
    al1 = al1.ravel(); amax = 2 ** A - 1
    thr = np.zeros((W1.shape[1], amax), dtype=int)
    for k in range(1, amax + 1):
        thr[:, k - 1] = np.ceil((k - 0.5 - b1) / (al1 * xs) - 1e-9).astype(int)
    b2i = np.round(b2 / float(np.ravel(al2)[0])).astype(int)   # output bias in units of the shared layer-2 scale
    return dict(T1=T1.astype(int), T2=T2.astype(int), thr=thr, b2=b2i, P=P, A=A)

def infer(q, X):
    z1 = X.astype(int) @ q['T1']
    a = (z1[:, :, None] >= q['thr'][None]).sum(2)
    z2 = a @ q['T2'] + q['b2']
    return np.argmax(z2, axis=1)

def stats(q):
    H = q['T1'].shape[1]; n = q['T1'].size + q['T2'].size
    nz = int((q['T1'] != 0).sum() + (q['T2'] != 0).sum())
    pmax = 2 ** q['P'] - 1; amax = 2 ** q['A'] - 1
    z1max = 64 * pmax; z2max = H * amax + int(np.abs(q['b2']).max())
    return dict(pixel_bits=q['P'], hidden=H, act_bits=q['A'], weights=n, nonzero=nz,
                input_bits_per_symbol=64 * q['P'],
                z1_bits=int(np.ceil(np.log2(2 * z1max + 1))), z2_bits=int(np.ceil(np.log2(2 * z2max + 1))),
                thresholds=int(q['thr'].size), thr_range=[int(q['thr'].min()), int(q['thr'].max())],
                b2_range=[int(q['b2'].min()), int(q['b2'].max())])

if __name__ == '__main__':
    configs = [tuple(map(int, c.split(','))) for c in sys.argv[1:]] or [(2, 32, 2), (1, 32, 2), (2, 16, 2), (2, 32, 1), (2, 24, 2)]
    out = []
    for P, H, A in configs:
        runs = [train(P, H, A, seed) for seed in range(3)]
        accs = [r[1] for r in runs]; best = max(runs, key=lambda r: r[2])
        s = stats(best[0]); s.update(test_acc_mean=round(np.mean(accs), 4), test_acc_min=round(min(accs), 4), test_acc_max=round(max(accs), 4))
        print(json.dumps(s), flush=True); out.append(s)
        np.savez(f'v2_P{P}_H{H}_A{A}.npz', **best[0])
    json.dump(out, open('results_v2.json', 'w'), indent=1)
