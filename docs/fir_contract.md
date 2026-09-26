# fir_stream contract, v1

`fpga_signal/fir.py` (`fir_fixed`) is the numerical specification. `rtl/fir_stream.sv` must match it
sample for sample. Any change to a clause below changes the contract version and needs a matching
reference-model test (AGENTS.md).

## Fixed-point contract

| Item | Contract | RTL | Checked by |
|---|---|---|---|
| Input | signed 16-bit two's complement, [-32768, 32767] | `SAMPLE_W = 16` | `test_rtl_parameters_match_model`, `test_rtl_widths_and_format_match_model` |
| Coefficients | signed 16-bit, Q14 (Q2.14): 16384 = 1.0, range [-2.0, +1.99994] | `COEF_W = 16`, `COEF_FRAC = 14`, `C0..C4` | same, plus `test_rtl_default_taps_match_model` |
| Default taps | `(1024, 4096, 6144, 4096, 1024)` = [1, 4, 6, 4, 1] / 16 exactly (no quantisation error), sum = 1.0 | parameter defaults | `test_default_taps_are_exact_binomial_q14`, `default` build (no overrides) |
| Tap order | `C0` multiplies the newest sample x[n], `C4` the oldest x[n-4] | `sample_in*C0 + d0*C1 + ... + d3*C4` | asymmetric `stress` build (`taps_reversed` mutant) |
| Products | exact signed 16 x 16 -> 32-bit products | signed operands, ACC_W context | `stress`, `acc_extreme` builds; signedness mutants |
| Accumulator | exact sum of 5 products. Worst case over *all* 16-bit taps: [-5·32768·32767, 5·2^30], needs 34 bits | `ACC_W = 40`; t=0 `$fatal` if `ACC_W < SAMPLE_W + COEF_W + clog2(5)` = 35 | `test_accumulator_width_is_sufficient`, `acc_extreme` build reaches 5·2^30 |
| Scaling | y = acc / 2^14 | `>>> COEF_FRAC` | known-answer tests (impulse of 16384 reproduces the taps) |
| Rounding | to nearest, ties **away from zero**: +0.5 LSB -> +1, +1.5 -> +2 | `(|acc| + 2^13) >> 14` with the sign restored | `test_round_shift_*` (exhaustive vs. an exact rational oracle) |
| Negative rounding | symmetric: round(-v) = -round(v); -0.5 LSB -> -1 (not 0) | same expression on `-acc` | 279 exact -0.5 ties in the Gate 0 vectors; `round_half_up_negative` mutant |
| Order | round **then** saturate | same | `test_steps_expose_accumulator_rounding_and_saturation` |
| Saturation | clamp the rounded value to [-32768, 32767]; never wraps | compare against `MAX_OUT`/`MIN_OUT` | `stress`/`acc_extreme` builds, `test_saturation` |
| Output | signed 16-bit | `sample_out[15:0]` | `test_rtl_parameters_match_model` |

Reachability with the production taps: the rounded output always lies in [-32768, 32767], so the
saturation logic **cannot be exercised by the default filter**. Exact ±0.5 LSB ties are reachable (the
Gate 0 vectors contain 319 positive and 279 negative ties). This is why the RTL regression also builds:

* `stress = (32767, -32768, 1, -1, 16384)`: asymmetric, ±2.0 extremes, ±1 LSB taps, saturation both ways.
* `acc_extreme = (-32768,) * 5`: the largest possible accumulator magnitude (5·2^30). Its accumulator is
  always a multiple of 2^15, so rounding ties cannot occur in this build.

Model-only behaviour (not reachable through the 16-bit RTL port): out-of-range integer inputs are
saturated to 16 bits; non-integer inputs (floats, NaN, Inf) raise `TypeError`.

## Timing contract

Signals: `clk`, `rst`, `in_valid`, `sample_in[15:0]`, `out_valid`, `sample_out[15:0]`. All registers
are clocked on the rising edge of `clk`.

1. **Acceptance.** A sample is accepted on a rising edge where `rst == 0` and `in_valid == 1`. There is
   no ready/backpressure: the core accepts one sample every clock if offered.
2. **Latency = 1 cycle.** The result for a sample accepted at edge *k* is registered at edge *k*:
   `out_valid == 1` and `sample_out == y` for exactly the following cycle, so a downstream register
   captures it at edge *k + 1*.
3. **Invalid cycles.** An edge with `in_valid == 0` leaves the delay line unchanged, gives
   `out_valid == 0` for the following cycle and holds `sample_out`. `sample_in` is ignored. The valid
   output stream is therefore exactly `fir_fixed(accepted samples)`, independent of gaps.
4. **Reset.** `rst` is synchronous, active high, and has priority over `in_valid`. At an edge with
   `rst == 1`, the delay line, `out_valid` and `sample_out` are cleared to 0 and a sample offered on that
   edge is dropped. After reset the filter state equals the model's initial state (zero history). A
   sample accepted on the edge before reset still produces its output in the following cycle.
5. **Outputs change only on rising clock edges** (no combinational path from inputs to outputs, no
   asynchronous reset).
6. **Power-up.** Outputs are undefined until the first reset edge. Integration layers must assert
   `rst` for at least one clock edge after configuration.

How the testbench applies this without depending on simulator event ordering: inputs are driven and
outputs are sampled on the falling edge (half a period from the active edge), every cycle is compared,
including idle and reset cycles, and a watcher fails any output change that is not exactly on a rising
edge. See `tb/fir_bench.py`.

## Verification evidence

| Check | Command | What it proves |
|---|---|---|
| Golden model | `make test` | contract clauses, independent rational oracle, frozen vector fingerprint, tooling |
| Gate 0 regression | `make rtl` | 12 cocotb tests x 3 builds, 10,000-vector stream and directed edge cases, zero mismatches |
| Lint | `make lint` | Verilator `-Wall` clean for every build |
| Cross-simulator | `make xsim` | an independent SystemVerilog testbench agrees on Icarus 12 and Verilator 5.020 (randomised power-up state) |
| Test strength | `make mutation` | 34 injected RTL bugs (rounding, signedness, saturation, accumulator width, tap order, valid timing, reset) are all caught |
| Synthesizability | `make synth` | generic Yosys synthesis of every build: no latches, no warnings, 81 flip-flops (4 x 16 delay line, 16 output, 1 valid) |
| Parameter guard | `make lint` | the RTL refuses an undersized accumulator (`ACC_W=34`) with `$fatal` |
