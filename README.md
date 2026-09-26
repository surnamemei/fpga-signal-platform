# FPGA Signal Platform

Simulation-first real-time DSP project: a bit-accurate Python fixed-point golden model, a
board-independent SystemVerilog streaming FIR, and a sample-by-sample RTL regression. No hardware
purchase is justified until the verification path is complete; see
[docs/hardware_purchase_gate.md](docs/hardware_purchase_gate.md).

## What is here

| Path | Contents |
|---|---|
| `fpga_signal/` | golden model: `fixed.py` (rounding, saturation), `fir.py` (5-tap Q14 FIR, the numerical spec), `vectors.py` (frozen Gate 0 vectors), `rtl_configs.py` (coefficient sets the RTL is built with) |
| `rtl/fir_stream.sv` | streaming FIR, registered output, latency 1 |
| `tb/` | cocotb harness (`fir_bench.py`), cycle-level expected-output model (`fir_protocol.py`), cocotb tests (`test_fir_cocotb.py`), cocotb makefile (`cocotb.mk`), independent SystemVerilog testbench (`fir_stream_tb.sv`) |
| `verification/` | vector generator, strict results checker, cross-simulator runner, mutation tester |
| `tests/` | pytest suite: contract, independent oracle, vector fingerprint, verification tooling |
| `docs/fir_contract.md` | the fixed-point and timing contract, and which test checks each clause |

## Prerequisites

* Python 3.11 or newer.
* For RTL simulation: GNU make, bash, and **Icarus Verilog 12** (`sudo apt install iverilog` on
  Ubuntu 24.04, `brew install icarus-verilog` on macOS). Linux, macOS or WSL. The Python tests also
  run natively on Windows.
* For `make lint` and `make xsim` only: **Verilator 5.x** (`sudo apt install verilator`). CI uses
  Verilator 5.020, the Ubuntu 24.04 package.
* For `make synth` only: Yosys. `pip install -e ".[dev,synth]"` installs the YoWASP build, so no
  system package is needed.

cocotb names simulators differently from their executables: Icarus Verilog installs an `iverilog`
program, but the cocotb simulator name is **`SIM=icarus`**. `SIM=iverilog` fails with
`Couldn't find makefile for simulator: "iverilog"`.

## Local commands

From a fresh clone:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Then:

```bash
make test                # pytest: golden model, contract, frozen vectors, tooling (about 1 s)
make vectors             # writes verification/vectors.csv (10,000 samples, seed 5305)
make rtl SIM=icarus      # cocotb regression: 12 tests x 3 coefficient builds, strict pass/fail
make lint                # Verilator -Wall on the RTL, every build
make xsim                # plain SystemVerilog testbench on Icarus and Verilator
make mutation            # 34 injected RTL bugs; every one must make the regression fail
make synth               # generic Yosys synthesis, no FPGA part (needs: pip install -e ".[synth]")
make gate0               # test + vectors + rtl (the Gate 0 criterion; also plain `make`)
make ci                  # everything the GitHub Actions job runs
```

A passing `make rtl` ends with:

```text
RTL regression: PASS (12 tests expected per build)
  build                    tests  passed      sim time     wall
  icarus-default              12      12       492.4us     2.4s
  icarus-stress               12      12       492.0us     2.5s
  icarus-acc_extreme          12      12       491.0us     2.6s
```

Each test also logs its coverage (outputs checked, ±0.5 LSB ties, saturation events, largest
accumulator), for example:

```text
[default] gate0 vectors 10000: 10000 outputs checked, 0 mismatches, latency 1 cycle | ties +0.5:319 -0.5:279 | saturated +:0 -:0 | ...
```

One configuration by hand: `make -f tb/cocotb.mk SIM=icarus FIR_CONFIG=stress`. Waveforms: add
`WAVES=1` (FST file in `sim_build/icarus-<config>/`). All outputs go under `sim_build/` (ignored by
git) and `verification/vectors.csv`, which is regenerated identically on every run.

On a mismatch the failing test prints the sample index, input, expected value, RTL value, error,
the pre-saturation accumulator and the neighbouring samples, and `make rtl` exits non-zero.

## What the regression checks

Three RTL builds run the same 12 tests:

* `default`: the production taps, built **without** parameter overrides, so the defaults written in
  the RTL are what gets tested.
* `stress = (32767, -32768, 1, -1, 16384)` and `acc_extreme = (-32768,) * 5`: the production taps can
  never saturate and are symmetric, so these builds exist to exercise saturation, negative
  coefficients, tap order, every rounding residue and the worst-case accumulator.

Tests: RTL parameters match the model; reset clears state and drops samples offered during reset;
the 10,000 Gate 0 vectors back to back; the same vectors with random idle gaps; impulses; zero input;
full-scale and near-full-scale runs; alternating signs; ±0.5 LSB rounding boundaries; saturation
boundaries; resets mid-stream; a 20,000-cycle random soak. Every cycle is compared, including idle
and reset cycles, so dropped, duplicated, late or X outputs fail. Details are in
[docs/fir_contract.md](docs/fir_contract.md).

## Arithmetic contract (summary)

* samples: signed 16-bit; coefficients: signed 16-bit Q14; `C0` multiplies the newest sample;
* accumulator: exact (RTL 40 bits; any 16-bit tap set needs at most 34);
* output = saturate16(round(acc / 2^14)), rounding to nearest with ties away from zero
  (symmetric for negative values: -0.5 LSB -> -1);
* latency 1 clock; synchronous active-high reset with priority over `in_valid`;
* default taps [1, 4, 6, 4, 1] / 16 sum to exactly 1.0 in Q14.

## Planned gates

1. **Gate 0:** golden model + FIR RTL + sample-by-sample simulation (this repository).
2. **Gate 1:** inexpensive Artix-7 board only after Gate 0 is closed; UART loop and
   coefficient/config control, in a separate integration layer. The staged bring-up and the
   Cmod A7-35T versus Basys 3 comparison are in [docs/BOARD_BRINGUP_PLAN.md](docs/BOARD_BRINGUP_PLAN.md).
3. **Gate 2:** Pmod I2S2 or equivalent only after board streaming is stable; real-time audio path.
4. **Gate 3:** OpenECE Lab host integration and automated hardware-vs-golden validation.
