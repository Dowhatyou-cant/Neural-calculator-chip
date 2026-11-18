"""Generate docs/chip-overview.svg (and PNG via rsvg-convert): an original block diagram of the test chip."""
W, H = 1280, 640
BG, INK, MUTED, ACCENT, CHIP, DIE, PAD, OK = ("#0B1626", "#E8EEF7", "#8FA3BF", "#4FC3F7",
                                               "#16263D", "#1D3352", "#C9A94E", "#6FD39A")
o = []
a = o.append
a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
  f'font-family="Inter, Helvetica, Arial, sans-serif">')
a(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
# faint grid
for x in range(0, W, 40):
    a(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" stroke="#13233A" stroke-width="1"/>')
for y in range(0, H, 40):
    a(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="#13233A" stroke-width="1"/>')
a('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
  f'<path d="M0,0 L10,5 L0,10 z" fill="{ACCENT}"/></marker></defs>')

# title
a(f'<text x="64" y="78" fill="{INK}" font-size="40" font-weight="700">Neural-Calculator Test Chip</text>')
a(f'<text x="64" y="114" fill="{MUTED}" font-size="20">A tiny neural network built from logic gates · '
  f'eChipHub–SCL 0.8 µm MPW shuttle</text>')

# 1) handwritten input, 8x8 pixels with 2-bit levels (a hand-drawn "7")
seven = ["00000000",
         "03333320",
         "00000330",
         "00003300",
         "00033000",
         "00230000",
         "00330000",
         "00320000"]
gx, gy, c = 64, 230, 22
shade = {"0": "#1A2B44", "1": "#3E5675", "2": "#8FB4D9", "3": "#E8EEF7"}
for r, row in enumerate(seven):
    for k, v in enumerate(row):
        a(f'<rect x="{gx + k*c}" y="{gy + r*c}" width="{c-2}" height="{c-2}" rx="2" fill="{shade[v]}"/>')
a(f'<text x="{gx}" y="{gy-16}" fill="{INK}" font-size="18" font-weight="600">Handwritten symbol</text>')
a(f'<text x="{gx}" y="{gy + 8*c + 26}" fill="{MUTED}" font-size="15">8×8 pixels, 2-bit grey</text>')
a(f'<text x="{gx}" y="{gy + 8*c + 46}" fill="{MUTED}" font-size="15">0–9  +  −  ×  ÷</text>')

# 2) ESP32 host
ex, ey, ew, eh = 300, 250, 190, 140
a(f'<rect x="{ex}" y="{ey}" width="{ew}" height="{eh}" rx="12" fill="{CHIP}" stroke="{MUTED}" stroke-width="2"/>')
a(f'<text x="{ex+ew/2}" y="{ey+52}" fill="{INK}" font-size="22" font-weight="700" text-anchor="middle">ESP32-S3</text>')
a(f'<text x="{ex+ew/2}" y="{ey+82}" fill="{MUTED}" font-size="15" text-anchor="middle">host on our own PCB</text>')
a(f'<text x="{ex+ew/2}" y="{ey+108}" fill="{MUTED}" font-size="15" text-anchor="middle">does the arithmetic</text>')
a(f'<line x1="{gx+8*c+14}" y1="{gy+4*c}" x2="{ex-8}" y2="{gy+4*c}" stroke="{ACCENT}" stroke-width="3" marker-end="url(#ar)"/>')

# 3) the chip: package with pads, die inside
cx, cy, cs = 640, 170, 300
a(f'<rect x="{cx}" y="{cy}" width="{cs}" height="{cs}" rx="14" fill="{CHIP}" stroke="#2C4466" stroke-width="2"/>')
n = 13  # 13 pads per side = 52 pads
step = cs / (n + 1)
for i in range(1, n + 1):
    p = i * step
    a(f'<rect x="{cx + p - 6}" y="{cy - 14}" width="12" height="18" rx="2" fill="{PAD}"/>')
    a(f'<rect x="{cx + p - 6}" y="{cy + cs - 4}" width="12" height="18" rx="2" fill="{PAD}"/>')
    a(f'<rect x="{cx - 14}" y="{cy + p - 6}" width="18" height="12" rx="2" fill="{PAD}"/>')
    a(f'<rect x="{cx + cs - 4}" y="{cy + p - 6}" width="18" height="12" rx="2" fill="{PAD}"/>')
dx, dy, ds = cx + 30, cy + 30, cs - 60
a(f'<rect x="{dx}" y="{dy}" width="{ds}" height="{ds}" rx="8" fill="{DIE}" stroke="{ACCENT}" stroke-width="1.5"/>')
# network layers inside the die
layers = [(64, 8, "64 in"), (48, 7, "48 hidden"), (14, 5, "14 out")]
lx = [dx + 45, dx + ds/2, dx + ds - 45]
pts = []
for (cnt, shown, lab), x in zip(layers, lx):
    ys = [dy + 40 + j * (ds - 110) / (shown - 1) for j in range(shown)]
    pts.append((x, ys, lab))
for (x1, ys1, _), (x2, ys2, _) in zip(pts, pts[1:]):
    for y1 in ys1:
        for y2 in ys2:
            a(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{ACCENT}" stroke-opacity="0.16" stroke-width="1"/>')
for x, ys, lab in pts:
    for y in ys:
        a(f'<circle cx="{x}" cy="{y}" r="6" fill="{ACCENT}"/>')
    a(f'<text x="{x}" y="{dy + ds - 42}" fill="{INK}" font-size="13" text-anchor="middle">{lab}</text>')
a(f'<text x="{dx + ds/2}" y="{dy + ds - 16}" fill="{MUTED}" font-size="13" text-anchor="middle">'
  f'weights −1 / 0 / +1 · no multipliers</text>')
a(f'<text x="{cx + cs/2}" y="{cy + cs + 50}" fill="{INK}" font-size="18" font-weight="600" text-anchor="middle">'
  f'~4,000 gates · ≤5 MHz · 52 pads</text>')

# bus arrows between ESP32 and chip
a(f'<line x1="{ex+ew+6}" y1="{ey+45}" x2="{cx-24}" y2="{ey+45}" stroke="{ACCENT}" stroke-width="3" marker-end="url(#ar)"/>')
a(f'<text x="{(ex+ew+cx)/2 - 8}" y="{ey+33}" fill="{MUTED}" font-size="14" text-anchor="middle">8-bit byte bus</text>')
a(f'<line x1="{cx-24}" y1="{ey+100}" x2="{ex+ew+6}" y2="{ey+100}" stroke="{ACCENT}" stroke-width="3" marker-end="url(#ar)"/>')
a(f'<text x="{(ex+ew+cx)/2 - 8}" y="{ey+124}" fill="{MUTED}" font-size="14" text-anchor="middle">class scores</text>')

# 4) result
rx = 1010
a(f'<text x="{rx}" y="{gy-16}" fill="{INK}" font-size="18" font-weight="600">Result</text>')
a(f'<rect x="{rx}" y="{gy}" width="210" height="80" rx="12" fill="{CHIP}" stroke="{MUTED}" stroke-width="2"/>')
a(f'<text x="{rx+105}" y="{gy+52}" fill="{INK}" font-size="32" font-weight="700" text-anchor="middle">7 + 3 = 10</text>')
a(f'<text x="{rx}" y="{gy+112}" fill="{MUTED}" font-size="15">chip reads each symbol,</text>')
a(f'<text x="{rx}" y="{gy+134}" fill="{MUTED}" font-size="15">ESP32 works out the sum</text>')

# status strip
sy = 575
items = [("RTL design", True), ("Verification", True), ("Formal equivalence", True),
         ("Synthesis", True), ("Layout", False), ("Tape-out", False)]
xs = [64, 232, 401, 645, 801, 930]
for (lab, done), x in zip(items, xs):
    col = OK if done else MUTED
    mark = "✓" if done else "○"
    a(f'<text x="{x}" y="{sy}" fill="{col}" font-size="19" font-weight="600">{mark}  {lab}</text>')
o.append('</svg>')
open(__file__.replace("make_banner.py", "chip-overview.svg"), "w").write("\n".join(o))
