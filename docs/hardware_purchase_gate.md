# Hardware purchase gate

## GATE OPEN — FPGA BOARD ONLY

Opened on 26 September 2026 by the final Gate 0 verification event: the `verify` workflow passed
on commit `9c523b6` in GitHub Actions
[run 36228797521](https://github.com/surnamemei/fpga-signal-platform/actions/runs/36228797521).

**This authorizes the purchase of the first FPGA development board only.** That means one board:
the Cmod A7-35T as the primary choice, or the Basys 3 as the alternative (see
[Purchase recommendation](#purchase-recommendation)).

**It does not authorize** any of the following. Each needs its own gate decision, based on
evidence from board bring-up:

- Analog Discovery 3
- Pmod I2S2
- any additional instrumentation
- a custom PCB
- larger FPGA boards

## Verification record

| Item | Value |
|---|---|
| CI run | [`verify` #2, run 36228797521](https://github.com/surnamemei/fpga-signal-platform/actions/runs/36228797521): push to `main`, first attempt, conclusion **success** |
| Commit | `9c523b60f946074324a13861f055a70194aa692f` |
| Job | `Gate 0 - golden model and RTL regression` (job 108367833018) on `ubuntu-24.04`, 08:06:41-08:11:57 UTC, every step successful |
| Artifact | `gate0-results`: results XML, cross-simulator, mutation and synthesis logs |
| Earlier run | #1 (run 36225726422) on the v0.1 commit `edf6712` failed at its `make` step, the `SIM=iverilog` fault that started this work |
| Recorded | 26 September 2026, from the GitHub API |

The table below maps each required item to the step of the green run that establishes it. Every
step is unconditional and fails the job on any error; only the artifact upload runs with
`if: always()`.

| Required | Step in the run | Why its success proves the item |
|---|---|---|
| Python tests | 8, `make test` | pytest exits non-zero on any failure: 101 tests, including the pinned vector fingerprint |
| Deterministic vector generation | 9, `make vectors` | writes the seed-5305 set. The fingerprint test (step 8) and the stale-vector check (step 11) tie it to the frozen hash `7b8508e6...` |
| RTL compilation | 10 `make lint`, 11 `make rtl`, 12 `make xsim`, 14 `make synth` | Verilator `-Wall`, Icarus `-Wall` for three coefficient builds, both simulators' testbench builds, and Yosys; any error or lint warning fails the step |
| Directed cocotb tests | 11, `make rtl` | the strict checker fails the step unless all 12 tests ran once and passed in each of the three builds |
| 10,000-sample regression | 11, `make rtl` | `test_gate0_vectors_10000` is one of those 12 tests in every build |
| Zero unexpected mismatches | 11, `make rtl` | the scoreboard fails a test on any mismatch, or on any dropped, duplicated or X sample |
| Beyond the required list | 12 `make xsim`, 13 `make mutation` | the two simulators agree, and 34 of 34 injected RTL bugs are caught |

GitHub serves the job log and the artifact only to logged-in users. The counts above therefore come
from two sources. The first is the workflow and Makefile at this commit. The second is an independent
reproduction on a clean checkout of `9c523b6` with a fresh environment, using the CI tool versions
(Icarus 12.0, Verilator 5.020, cocotb 2.1.0, numpy 2.5.3, Yosys 0.69). There, `make ci` passes 101
Python tests and 36 of 36 cocotb tests, 10,000 of 10,000 vectors with 0 mismatches, 6 of 6
cross-simulator runs and 34 of 34 mutants, with 0 warnings.

## Frozen contract

FIR contract v1 is frozen at commit `9c523b6`; [fir_contract.md](fir_contract.md) holds its numerical
and timing clauses. `rtl/fir_stream.sv` must not be modified unless the change introduces a new
contract version with matching reference-model tests (AGENTS.md). Board bring-up happens in the
integration layer described in [BOARD_BRINGUP_PLAN.md](BOARD_BRINGUP_PLAN.md).

## Recommended tag

Mark the verified simulation milestone with an annotated tag on the commit the green run tested:

```bash
git tag -a gate0-simulation-verified 9c523b60f946074324a13861f055a70194aa692f -m "Gate 0: FIR contract v1 verified in simulation (CI run 36228797521)"
```

```bash
git push origin gate0-simulation-verified
```

## Purchase recommendation

- **Primary: Cmod A7-35T**
- **Alternative: Basys 3**

Both boards carry the same FPGA (`xc7a35tcpg236-1`), so resources and Vivado support are
identical. The Cmod A7-35T is primary for three reasons:

- Its clock, LEDs, button, USB-UART and single Pmod cover every pin the bring-up plan and the later
  Pmod I2S2 need.
- Its 12 MHz clock lets the unchanged single-cycle FIR run as verified.
- It costs less.

The Basys 3 is the alternative for when standalone debugging (switches, LEDs, display) or spare Pmods
alongside the I2S2 matter more than cost. The full comparison and its sources are in
[BOARD_BRINGUP_PLAN.md](BOARD_BRINGUP_PLAN.md#board-comparison-for-this-repository-cmod-a7-35t-or-basys-3).

## Gate 0 audit

### Criteria

| Criterion | Status | Evidence |
|---|---|---|
| Python reference behaviour is well specified | met | [fir_contract.md](fir_contract.md); exhaustive rounding check against an exact rational oracle; FIR checked against an independent convolution oracle on 43 coefficient sets; frozen vector hash |
| RTL matches the reference | met | 36 of 36 cocotb tests; every cycle compared, including idle and reset cycles; an independent SV testbench agrees on Icarus and Verilator |
| Directed edge cases pass | met | impulse, zero, full scale, near full scale, alternating sign, ±0.5 LSB boundaries, saturation boundaries, resets mid-stream, X on ignored inputs |
| 10,000-sample regression, zero unexpected mismatches | met | 10,000 of 10,000, 0 mismatches; also 0 with random idle gaps and on the two stress builds |
| CI is green | met | run 36228797521 on `9c523b6`, all steps successful |
| No unresolved correctness issue | met | every finding below is fixed; no RTL arithmetic defect was found |

### Falsification attempts

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

### Residual risks (Gate 1 bring-up, not purchase blockers)

* **Timing closure is unknown.** Five multiplies, an adder tree, rounding and saturation are all in
  one cycle. Generic Yosys synthesis gives 645 cells and 81 flip-flops for the production taps, but no
  part or clock has been targeted. Pipelining changes `LATENCY` and needs contract v2.
* **Reset** is synchronous. The board layer must provide a synchronised reset held for at least one
  clock.
* **Vendor tools are untested.** Vivado's handling of the `initial $fatal` guard is unverified. Yosys
  stops on it when the guard fires, which is the intended outcome, but with a generic message.
* **Coefficients are fixed at elaboration.** Runtime coefficient loading (planned for Gate 1) needs a
  new contract and tests.
