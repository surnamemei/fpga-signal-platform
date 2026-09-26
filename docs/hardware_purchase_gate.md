# Hardware purchase gate (26 September 2026)

## GATE CLOSED

One blocker remains: **GitHub Actions has not yet run with these changes**, so "CI is green" is
unproven. Every CI step passes locally on the same OS image and tool versions, replayed under GitHub's
`bash -eo pipefail` shell, but a local replay is not the CI run. No correctness blocker is open.

To open the gate: push these changes, confirm the `verify` workflow is green in every step, record
the run URL below, and change the heading to GATE OPEN.

CI run: _pending_

## Criteria

| Criterion | Status | Evidence |
|---|---|---|
| Python reference behaviour is well specified | met | [fir_contract.md](fir_contract.md); exhaustive rounding check against an exact rational oracle; FIR checked against an independent convolution oracle on 43 coefficient sets; frozen vector hash |
| RTL matches the reference | met | 36 of 36 cocotb tests; every cycle compared, including idle and reset cycles; an independent SV testbench agrees on Icarus and Verilator |
| Directed edge cases pass | met | impulse, zero, full scale, near full scale, alternating sign, ±0.5 LSB boundaries, saturation boundaries, resets mid-stream, X on ignored inputs |
| 10,000-sample regression, zero unexpected mismatches | met | 10,000 of 10,000, 0 mismatches; also 0 with random idle gaps and on the two stress builds |
| CI is green | **not met** | workflow fixed, not yet run on GitHub |
| No unresolved correctness issue | met | every finding below is fixed; no RTL arithmetic defect was found |

## Falsification attempts

The RTL arithmetic survived every attack. The weaknesses were in the verification, and each is fixed.

| Attack | Finding | Fix |
|---|---|---|
| CI simulator configuration | `SIM=iverilog` does not exist in cocotb | `SIM ?= icarus`, explicit `make rtl SIM=icarus`, clear error for `SIM=iverilog` |
| Testbench sampling time | Reading after `RisingEdge` returns pre-edge values, so comparisons were one sample off | inputs and outputs on the falling edge; explicit `LATENCY`; per-cycle scoreboard; falling-edge times asserted |
| Saturation path | The production taps can never saturate, so the saturation logic was untestable | added the `stress` and `acc_extreme` RTL builds; coverage asserts saturation happened |
| Tap order | Symmetric production taps hide a reversed delay line | `stress` taps are asymmetric (the `taps_reversed` mutant is caught only there) |
| Accumulator width | 10,000 vectors never exceed 30 bits | `acc_extreme` reaches the 34-bit worst case (5·2^30); 32- and 33-bit mutants are caught |
| RTL parameter defaults | The flow overrode every coefficient, so the defaults in the RTL were never tested | the `default` build uses no overrides; parameters are read back from the simulator |
| Stale or shared builds | One build directory would silently reuse other coefficients | one build per config; the test asserts the elaborated taps |
| Result checking | cocotb's own check passes when 0 tests run, ignores skips, and exits with the failure count (256 failures give exit 0) | strict checker: every test must run once and pass |
| Stimulus range | cocotb silently drives 40000 into a 16-bit port as -25536 | driver rejects out-of-range stimulus |
| Output timing | A change between clock edges (for example an asynchronous reset) is invisible to edge sampling | watcher fails any output change not on a rising edge |
| Vacuous coverage | "tests ±0.5 LSB rounding" cannot hold for `acc_extreme` (accumulator always a multiple of 2^15) | coverage requirements depend on reachability; the harness caught its own false claim |
| X propagation | Idle cycles carried only valid numbers | X on `sample_in` during idle cycles and X on `in_valid` during reset; none reaches the outputs |
| Parameter guard | Icarus 12 silently ignores elaboration-time `$error` | guard moved to a time-0 `$fatal` and proven to fire for `ACC_W=34` |
| Simulator dependence | Results could depend on Icarus event ordering or 4-state init | independent SV testbench agrees on Verilator with randomised power-up state |
| Signed arithmetic, rounding, reset, valid alignment | no RTL defect found | 34 mutants (rounding, signedness, saturation, accumulator, taps, delay line, valid, hold, reset) all caught |
| CI diagnostics | `iverilog -V \| head -n 1` exits 141 (SIGPIPE) under GitHub's `pipefail` shell | `sed -n 1p` |

## Residual risks (Gate 1 integration, not purchase blockers)

* **Timing closure is unknown.** Five multiplies, an adder tree, rounding and saturation are all in one
  cycle. Generic Yosys synthesis gives 645 cells and 81 flip-flops for the production taps, but no part
  or clock has been targeted. Pipelining changes `LATENCY` and needs contract v2.
* **Reset** is synchronous. The board layer must provide a synchronised reset held for at least one clock.
* **Vendor tools are untested.** Vivado's handling of the `initial $fatal` guard is unverified. Yosys
  stops on it when the guard fires, which is the intended outcome, but with a generic message.
* **Coefficients are fixed at elaboration.** Runtime coefficient loading (planned for Gate 1) needs a
  new contract and tests.
