"""Print the numbers quoted in v2-engine-spec.md, computed from the golden model,
so the spec never carries hand-added figures.  usage: python3 spec_numbers.py [clk_MHz]"""
import sys, numpy as np, tc_model as M
f = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
NI, H, C = 64, 48, 14
q = M.clip_model(M.rand_model(NI, H, C, np.random.default_rng(0)))
x = np.zeros(NI, int)
hwb = len(M.stream_hardwired(x, NI, H, C)); stb = len(M.stream_streamed(x, q))
print(f"{NI}->{H}->{C} at {f:g} MHz")
print(f"  hardwired: {hwb} bytes per symbol, {hwb / f / 1000:.1f} ms (+ >=1 idle byte to finish)")
print(f"  streamed : {stb} bytes per symbol, {stb / f / 1000:.1f} ms (+ >=1 idle byte to finish)")
print(f"  streamed overhead vs hardwired: {100 * (stb - hwb) / hwb:.1f}%")
print(f"  new class score every {NI * H / f / 1000:.2f} ms (hardwired)")
print(f"  bias limit: |bias| <= {M.ZMAX - 3 * H} for {H} hidden ({M.ZMAX} - 3 x hidden)")
