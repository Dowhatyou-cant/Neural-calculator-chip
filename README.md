# Neural-Calculator Test Chip: v2 Inference Engine

An independent, AI-assisted chip design project.

## Why I built this

I started by exploring how computers work through code. The deeper I went, the clearer it became that every line of software ends up as electrical signals switching transistors on and off, and that a chip is simply that circuit made physical. I wanted to understand that layer properly, not just read about it, so I set out to design a small chip myself: from the model and the Verilog, through verification and synthesis, aiming for a real shuttle run at SCL.

## In plain words

This is a very small neural network built directly out of logic gates, for a test chip. An ESP32 microcontroller sends the chip an 8×8 image of a handwritten digit or symbol (0–9, + − × ÷). The chip says which one it is, and the ESP32 does the arithmetic. Together they make a handwritten calculator.

- **Target:** eChipHub–SCL 0.8 µm multi-project wafer (MPW) shuttle, run by NIELIT and the Semi-Conductor Laboratory (SCL), Mohali.
- **Status (Nov 2026):** front-end design and verification are done. Synthesis on the foundry's own cells, place and route, the chip top level and tape-out are next. **The chip has not been fabricated yet.**

## What was done

| Stage | What | Where |
|---|---|---|
| Model | Weights are only −1, 0 or +1, so the chip needs no multipliers. Integer thresholds, 2-bit pixels. 96.0% accuracy on digits (64 → 48 → 10 network) | `engine/train_v2.py` |
| RTL design | Verilog core with an 8-bit byte bus, a chip-select pin, and reset and mode synchronisers | `engine/rtl/` |
| Golden model | A Python reference that matches the chip bit for bit and defines the protocol | `engine/tc_model.py` |
| Design verification | Lint (Verilator `-Wall`); RTL simulation; gate-level simulation of the synthesised netlist; an exhaustive check of every stored weight and threshold; mutation testing (planted bugs that the tests must catch); and a formal equivalence proof that the netlist matches the RTL (Yosys) | `engine/check_all.sh` |
| Synthesis | Synthesis with a generic gate library and a latch check: about 3,600–4,000 gate equivalents | `engine/synth_tc.sh` |
| Reviews | Three review rounds. Every finding and failure was logged with its root cause, how it was found, the fix and the check | `engine/FIXLOG_*.md`, `engine/OPUS_LOG.md` |

## Results (package v0.4, 17 Nov 2026)

One command (`./check_all.sh`), run from a freshly unpacked copy, gives **ALL CHECKS PASS** in 10 min 52 s on a 2-core machine.

| Check | Digits 64→48→10 (trained) | 64→48→14 (random stand-in) |
|---|---|---|
| Lint, synthesis | Clean, 3,622 gate equivalents | Clean, 3,978 gate equivalents, 131 flip-flops |
| Formal equivalence, RTL = netlist | Proven | Proven |
| Exhaustive stored-value check | 5,200 / 0 failures | 5,200 / 0 failures |
| RTL simulation | 2,732 checks, 0 failures | 3,193 checks, 0 failures |
| Gate-level simulation | 2,732 checks, 0 failures | 3,193 checks, 0 failures |
| Core mutants (planted bugs) | 10 caught, 1 proven equivalent | 11 / 11 caught |

## How it was built

The design and code were written with an AI agent (Claude, by Anthropic) doing the engineering work. I set the requirements and made the trade-off decisions: 48 hidden neurons, a clock of 5 MHz or less, an 8-bit byte bus instead of one pin per signal, a chip-select pin, and an ESP32 carrier board. Independent review rounds checked the work. 

## Run it

Needs Verilator 5, Yosys, Icarus Verilog and Python 3 with numpy and scikit-learn.

```bash
cd engine
python3 tc_model.py              # golden self-check: 400 checks, 0 failures
./check_all.sh --quick /tmp/q    # about 2 min smoke run
./check_all.sh /tmp/checks       # full run, about 11 min: "ALL CHECKS PASS"
```

`engine/README.md` explains what each check proves. It mentions a spec and a build log that are kept in the private project; the results above come from them.

## Not included

- The foundry PDK and cell libraries, which are used under SCL's terms. All synthesis here uses a generic gate library (`engine/ge.lib`).

## Next

1. Synthesis and slow-corner timing on SCL cells.
2. The chip top level: pads, self-test, a ring oscillator.
3. Place and route.
4. The ESP32 carrier board.
5. MPW submission.
