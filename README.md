# FPGA Signal Platform

Simulation-first real-time DSP project. No hardware purchase is justified until the reference and RTL verification path is working.

## Gate 0 implemented

- 16-bit signed fixed-point arithmetic helpers;
- a five-tap symmetric FIR golden model using Q14 coefficients;
- deterministic 10,000-sample test-vector generation;
- board-independent SystemVerilog streaming FIR;
- cocotb sample-by-sample regression harness;
- Python unit tests for saturation, rounding, gain and determinism.

## Local setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python verification/generate_vectors.py
```

For RTL regression install **Icarus Verilog** or **Verilator**, then:

```bash
make
```

The purchase gate is not passed until the cocotb run completes all 10,000 vectors with zero mismatches.

## Planned gates

1. **Gate 0:** golden model + FIR RTL + sample-by-sample simulation.
2. **Gate 1:** inexpensive Artix-7 board only after Gate 0 is closed; UART loop and coefficient/config control.
3. **Gate 2:** Pmod I2S2 or equivalent only after board streaming is stable; real-time audio path.
4. **Gate 3:** OpenECE Lab host integration and automated hardware-vs-golden validation.

## Important arithmetic contract

- samples: signed 16-bit;
- coefficients: signed Q14;
- output: rounded then saturated to signed 16-bit;
- default taps sum to exactly 1.0 in Q14.
