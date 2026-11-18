"""Model-level (data) mutations shared by mutants.py and equiv_selftest.py.
Each returns a changed copy of the quantised model; the hardwired-weight block
generated from it differs from the true one in exactly one place (or one group)."""
import boundary


def reachable_threshold(q):
    for j in range(q['thr'].shape[0]):
        for k in range(q['thr'].shape[1]):
            t = int(q['thr'][j, k])
            if boundary.reachable(q['T1'][:, j], t) and boundary.reachable(q['T1'][:, j], t - 1):
                return j, k
    raise SystemExit("no reachable threshold")


def _corners(q):
    NI = q['T1'].shape[0]
    return sorted({0, min(7, NI - 1), max(NI - 8, 0), NI - 1})   # [0, 7, 56, 63] at NI = 64


def wipe_corner_weights(q):
    q = dict(q); T1 = q['T1'].copy(); T1[_corners(q)] = 0; q['T1'] = T1; return q


def flip_corner_weights(q):
    q = dict(q); T1 = q['T1'].copy(); T1[_corners(q)] *= -1; q['T1'] = T1; return q


def flip_one_layer2_weight(q):
    import numpy as np
    q = dict(q); T2 = q['T2'].copy(); j, c = np.argwhere(T2 != 0)[0]; T2[j, c] *= -1
    q['T2'] = T2; return q


def flip_one_weight(q):
    """one layer-1 weight, sign flipped"""
    import numpy as np
    q = dict(q); T1 = q['T1'].copy(); i, j = np.argwhere(T1 != 0)[len(np.argwhere(T1 != 0)) // 2]
    T1[i, j] *= -1; q['T1'] = T1; return q


def threshold_plus_one(q):
    q = dict(q); th = q['thr'].copy(); j, k = reachable_threshold(q); th[j, k] += 1
    q['thr'] = th; return q


def threshold_minus_one(q):
    q = dict(q); th = q['thr'].copy(); j, k = reachable_threshold(q); th[j, k] -= 1
    q['thr'] = th; return q


DATA = [('wipe_corner_weights', wipe_corner_weights),
        ('flip_corner_weights', flip_corner_weights),
        ('flip_one_layer2_weight', flip_one_layer2_weight),
        ('threshold_plus_one', threshold_plus_one),
        ('threshold_minus_one', threshold_minus_one)]
