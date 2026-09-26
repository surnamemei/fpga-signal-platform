# Gate 0 status — 26 September 2026

Executed in the build environment:

- Python fixed-point tests: **4 passed**
- deterministic vector generation: **10,000 samples generated**
- negative signed rounding contract was explicitly checked and aligned in the RTL design

The SystemVerilog + cocotb harness is present, but the current build environment has neither Icarus Verilog nor Verilator installed, so the HDL regression was not executed here. GitHub Actions is configured to install Icarus Verilog and run `make` automatically.

**FPGA purchase gate remains CLOSED** until a simulator completes all 10,000 sample comparisons with zero mismatches.
