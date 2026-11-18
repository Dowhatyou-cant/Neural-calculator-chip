"""Writes the tiny model for check_all.sh --quick: 8 -> 4 -> 3, random ternary
weights, small non-zero thresholds and biases (so the bias and threshold paths
are live). usage: python3 quick_model.py out.npz"""
import sys, numpy as np
rng = np.random.default_rng(7)
T1 = rng.integers(-1, 2, (8, 4)); T2 = rng.integers(-1, 2, (4, 3))
thr = np.sort(rng.integers(-8, 9, (4, 3)), axis=1)
np.savez(sys.argv[1], T1=T1, T2=T2, thr=thr, b2=np.array([3, -2, 5]), P=2, A=2)
