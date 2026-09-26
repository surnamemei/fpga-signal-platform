# Gate 0 status (26 September 2026)

Executed locally on Ubuntu 24.04 with the tool versions CI uses: Python 3.12, cocotb 2.1.0,
numpy 2.5.3, Icarus Verilog 12.0 (Ubuntu package 12.0-2build2), Verilator 5.020, Yosys 0.69 (YoWASP).

| Gate 0 criterion | Result |
|---|---|
| Python tests | **PASS**: 101 tests (`make test`) |
| 10,000 deterministic vectors | generated, byte-identical to the v0.1 set (sha256 `7b8508e6...`, pinned in `tests/test_vectors.py`) |
| RTL compilation | **PASS**: Icarus `-Wall` with 0 warnings; Verilator `-Wall` lint clean; Yosys synthesis clean, no latches |
| Deterministic 10,000-sample regression | **0 mismatches** (10,000 of 10,000 outputs, latency 1 cycle, 319 +0.5 and 279 -0.5 LSB rounding ties) |
| Directed edge-case tests | **PASS**: 12 cocotb tests x 3 coefficient builds = 36 of 36 |
| Cross-simulator check | **PASS**: SystemVerilog testbench, 18,437 cycles per build, identical on Icarus and Verilator |
| Test strength | **34 of 34** injected RTL bugs caught (`make mutation`) |
| GitHub Actions | **not yet observed**: the workflow is fixed and every step was replayed locally under GitHub's shell; it needs a push |

## What was wrong in v0.1

1. `Makefile` set `SIM ?= iverilog`. cocotb's simulator name for Icarus Verilog is `icarus`, so CI
   stopped with `Couldn't find makefile for simulator: "iverilog"`.
2. Behind that error, the testbench read `sample_out` directly after `RisingEdge`, which returns the
   pre-edge value under Icarus. Every comparison was one sample late and the first vector already
   failed (`got 0, expected 114`).
3. The test used three APIs deprecated in cocotb 2.x (`units=`, `signed_integer`, `MODULE`), and it
   could not detect dropped, duplicated or late samples.

The hardware purchase decision and the full falsification audit are in
[docs/hardware_purchase_gate.md](docs/hardware_purchase_gate.md).
