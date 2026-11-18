"""Directed images that put hidden-neuron sums exactly ON a threshold and just BELOW it.

A hardwired threshold that is off by one only changes behaviour when a neuron's
sum z1 lands exactly on t or t-1.  Random images rarely do that (review R14).
boundary_images() searches for a small set of images that together cover, for
every neuron j and threshold k, both z1_j == t_jk and z1_j == t_jk - 1.
Targets that no input can reach are reported: a wrong value there can never
change any output (an "equivalent" mutant, not a test hole)."""
import numpy as np


def reachable(T1col, target, P=2):
    vmax = (1 << P) - 1
    return -vmax * int((T1col < 0).sum()) <= target <= vmax * int((T1col > 0).sum())


def boundary_images(q, seed=0, max_images=200, steps=3000):
    T1, thr = np.asarray(q['T1']), np.asarray(q['thr'])
    NI, H = T1.shape; K = thr.shape[1]
    targets = set(); unreachable = []
    for j in range(H):
        for k in range(K):
            for side, v in (('on', int(thr[j, k])), ('below', int(thr[j, k]) - 1)):
                (targets.add((j, v)) if reachable(T1[:, j], v)
                 else unreachable.append((j, k, side, v)))
    want = {}                                   # value targets per neuron
    for j, v in targets:
        want.setdefault(j, set()).add(v)
    rng = np.random.default_rng(seed); left = set(targets); images = []
    while left and len(images) < max_images:
        aj, av = sorted(left)[int(rng.integers(len(left)))]   # anchor target
        x = rng.integers(0, 4, NI); z = x @ T1
        def score(z):
            hits = sum((j, int(z[j])) in left for j in range(H))
            return hits + (1000 if int(z[aj]) == av else -abs(int(z[aj]) - av))
        best = score(z)
        for _ in range(steps):
            i = int(rng.integers(NI)); old = x[i]; new = int(rng.integers(0, 4))
            if new == old: continue
            z2 = z + (new - old) * T1[i]; s2 = score(z2)
            if s2 >= best:
                x[i] = new; z = z2; best = s2
        hit = {(j, int(z[j])) for j in range(H)} & left
        if hit:
            left -= hit; images.append(x.copy())
    return np.array(images), left, unreachable


if __name__ == '__main__':
    import sys
    for f in sys.argv[1:]:
        q = dict(np.load(f))
        imgs, left, unr = boundary_images(q)
        print(f"{f}: {len(imgs)} images cover boundary targets; "
              f"{len(left)} reachable targets missed; {len(unr)} unreachable")
