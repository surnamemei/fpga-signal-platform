"""Mutation testing: inject known RTL bugs and require the cocotb regression to catch every one.

A surviving mutant means the regression can pass on incorrect RTL. Each mutant is a list of
exact text substitutions in rtl/fir_stream.sv; the script stops with an error if a substitution
does not match exactly the expected number of times, so an RTL edit cannot silently turn a
mutant into a no-op. A mutant that fails to compile, or that stops the simulator before any
test runs, is reported as INVALID rather than counted as killed.

    python verification/mutation_test.py            # all mutants (make mutation)
    python verification/mutation_test.py --list
    python verification/mutation_test.py taps_reversed no_saturation -j 2
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verification"))
from check_results import check_file, expected_tests  # noqa: E402

RTL = ROOT / "rtl" / "fir_stream.sv"
WORK = ROOT / "sim_build" / "mutants"
CONFIGS = ("default", "stress", "acc_extreme")


@dataclass(frozen=True)
class Mutant:
    name: str
    bug: str
    edits: tuple  # (old, new) or (old, new, count)


NEG_ROUND = "            shifted = -((abs_acc + HALF_LSB) >>> COEF_FRAC);"
POS_ROUND = "            shifted = (abs_acc + HALF_LSB) >>> COEF_FRAC;"
SATURATE = ("                if (shifted > MAX_OUT)\n"
            "                    sample_out <= MAX_OUT[SAMPLE_W-1:0];\n"
            "                else if (shifted < MIN_OUT)\n"
            "                    sample_out <= MIN_OUT[SAMPLE_W-1:0];\n"
            "                else\n"
            "                    sample_out <= shifted[SAMPLE_W-1:0];")
SHIFT_IN = "                d3 <= d2; d2 <= d1; d1 <= d0; d0 <= sample_in;\n"

MUTANTS = [
    # Rounding
    Mutant("round_half_up_negative", "negative results use floor(x+0.5): -0.5 LSB gives 0, not -1",
           ((NEG_ROUND, "            shifted = (acc + HALF_LSB) >>> COEF_FRAC;"),)),
    Mutant("round_half_toward_zero_negative", "only negative ties round toward zero",
           ((NEG_ROUND, "            shifted = -((abs_acc + HALF_LSB - ONE) >>> COEF_FRAC);"),)),
    Mutant("truncate_toward_zero", "rounding constant missing: both signs truncate toward zero",
           (("(abs_acc + HALF_LSB) >>> COEF_FRAC", "abs_acc >>> COEF_FRAC", 2),)),
    Mutant("floor_shift", "plain arithmetic shift (round toward -infinity)",
           ((POS_ROUND, "            shifted = acc >>> COEF_FRAC;"),
            (NEG_ROUND, "            shifted = acc >>> COEF_FRAC;"))),
    Mutant("round_negative_toward_zero", "negative results truncated, positive results rounded",
           ((NEG_ROUND, "            shifted = -(abs_acc >>> COEF_FRAC);"),)),
    Mutant("half_lsb_wrong", "rounding constant 0.25 LSB instead of 0.5 LSB",
           (("HALF_LSB = ONE <<< (COEF_FRAC - 1);", "HALF_LSB = ONE <<< (COEF_FRAC - 2);"),)),
    Mutant("missing_negation", "negative branch forgets to negate the magnitude",
           (("            abs_acc = -acc;", "            abs_acc = acc;"),)),
    Mutant("q15_scaling", "result scaled as Q15 instead of Q14",
           ((">>> COEF_FRAC", ">>> (COEF_FRAC + 1)", 2),)),
    # Signedness
    Mutant("unsigned_accumulator", "acc unsigned: `acc >= 0` always true, negatives take the positive branch",
           (("    logic signed [ACC_W-1:0] acc;", "    logic [ACC_W-1:0] acc;"),)),
    Mutant("unsigned_operand_poisons_sum", "unsigned delay line with one $signed() cast missing: whole sum unsigned",
           (("    logic signed [SAMPLE_W-1:0] d0, d1, d2, d3;", "    logic [SAMPLE_W-1:0] d0, d1, d2, d3;"),
            ("            + $signed(d0) * $signed(C1)", "            + d0 * $signed(C1)"))),
    Mutant("unsigned_coefficient", "C1 declared unsigned and used without $signed(): sum becomes unsigned",
           (("    parameter signed [COEF_W-1:0] C1 = 16'sd4096,", "    parameter [COEF_W-1:0] C1 = 16'sd4096,"),
            ("            + $signed(d0) * $signed(C1)", "            + $signed(d0) * C1"))),
    Mutant("unsigned_saturation_compare", "saturation compares unsigned: negative results clamp to +full scale",
           (("if (shifted > MAX_OUT)", "if ($unsigned(shifted) > $unsigned(MAX_OUT))"),
            ("else if (shifted < MIN_OUT)", "else if ($unsigned(shifted) < $unsigned(MIN_OUT))"))),
    # Saturation
    Mutant("no_saturation", "saturation removed: out-of-range results wrap",
           ((SATURATE, "                sample_out <= shifted[SAMPLE_W-1:0];"),)),
    Mutant("max_rail_off_by_one", "positive rail 32766",
           (("MAX_OUT = (ONE <<< (SAMPLE_W - 1)) - ONE;", "MAX_OUT = (ONE <<< (SAMPLE_W - 1)) - ONE - ONE;"),)),
    Mutant("min_rail_off_by_one", "negative rail -32767",
           (("MIN_OUT = -(ONE <<< (SAMPLE_W - 1));", "MIN_OUT = -(ONE <<< (SAMPLE_W - 1)) + ONE;"),)),
    Mutant("rails_swapped", "overflow clamps to the opposite rail",
           (("sample_out <= MAX_OUT[SAMPLE_W-1:0];", "sample_out <= @RAIL@;"),
            ("sample_out <= MIN_OUT[SAMPLE_W-1:0];", "sample_out <= MAX_OUT[SAMPLE_W-1:0];"),
            ("@RAIL@", "MIN_OUT[SAMPLE_W-1:0]"))),
    # Accumulator width (ACC_W still reads 40, so only the arithmetic tests can notice)
    Mutant("accumulator_33_bits", "33-bit accumulator: wraps above 2**32 (worst case is 5 * 2**30)",
           (("    logic signed [ACC_W-1:0] acc;", "    logic signed [32:0] acc;"),)),
    Mutant("accumulator_32_bits", "32-bit accumulator: wraps above 2**31",
           (("    logic signed [ACC_W-1:0] acc;", "    logic signed [31:0] acc;"),)),
    # Taps and delay line
    Mutant("taps_reversed", "C0 multiplies the oldest sample (invisible with symmetric taps)",
           (("$signed(sample_in) * $signed(C0)", "$signed(sample_in) * $signed(C4)"),
            ("$signed(d3) * $signed(C4)", "$signed(d3) * $signed(C0)"),
            ("$signed(d0) * $signed(C1)", "$signed(d0) * $signed(C3)"),
            ("$signed(d2) * $signed(C3)", "$signed(d2) * $signed(C1)"))),
    Mutant("tap_dropped", "oldest tap missing from the sum",
           (("\n            + $signed(d3) * $signed(C4);", ";"),)),
    Mutant("coefficient_off_by_one", "RTL default C2 = 6143 instead of 6144 (a quantisation slip)",
           (("C2 = 16'sd6144", "C2 = 16'sd6143"),)),
    Mutant("delay_line_skips_stage", "x[n-3] register loads x[n-1]",
           (("d2 <= d1;", "d2 <= d0;"),)),
    Mutant("delay_line_shifts_when_idle", "delay line advances on in_valid=0 cycles",
           (("            if (in_valid) begin\n" + SHIFT_IN, "            " + SHIFT_IN.lstrip() + "            if (in_valid) begin\n"),)),
    # Valid, timing and hold
    Mutant("out_valid_stuck_high", "out_valid asserted on every cycle after reset (duplicates)",
           (("            out_valid <= in_valid;", "            out_valid <= 1'b1;"),)),
    Mutant("out_valid_one_cycle_late", "out_valid one cycle behind sample_out",
           (("    logic signed [ACC_W-1:0] abs_acc;", "    logic signed [ACC_W-1:0] abs_acc;\n    logic in_valid_q;"),
            ("            out_valid <= in_valid;", "            in_valid_q <= in_valid;\n            out_valid <= in_valid_q;"))),
    Mutant("drops_back_to_back_samples", "out_valid drops every second sample of a burst",
           (("            out_valid <= in_valid;", "            out_valid <= in_valid & ~out_valid;"),)),
    Mutant("sample_out_not_held", "sample_out cleared on idle cycles instead of held",
           (("            out_valid <= in_valid;", "            out_valid <= in_valid;\n            if (!in_valid) sample_out <= '0;"),)),
    Mutant("output_updates_when_idle", "sample_out recomputed on idle cycles",
           (("            if (in_valid) begin\n" + SHIFT_IN, "            if (in_valid) begin\n" + SHIFT_IN + "            end\n            begin\n"),)),
    # Reset
    Mutant("reset_keeps_history", "reset does not clear the delay line",
           (("            d0 <= '0; d1 <= '0; d2 <= '0; d3 <= '0;\n", ""),)),
    Mutant("reset_keeps_oldest_tap", "reset clears d0..d2 but not d3",
           ((" d3 <= '0;", ""),)),
    Mutant("sample_accepted_during_reset", "a sample offered while rst=1 enters the delay line",
           (("d0 <= '0; d1 <= '0;", "d0 <= in_valid ? sample_in : '0; d1 <= '0;"),)),
    Mutant("out_valid_during_reset", "out_valid follows in_valid while rst=1",
           (("            out_valid <= 1'b0;", "            out_valid <= in_valid;"),)),
    Mutant("sample_out_not_reset", "sample_out keeps its value through reset",
           (("            sample_out <= '0;\n", ""),)),
    Mutant("asynchronous_reset", "reset acts asynchronously instead of on the clock edge",
           (("always_ff @(posedge clk)", "always_ff @(posedge clk or posedge rst)"),)),
]


def mutate(text: str, m: Mutant) -> str:
    for edit in m.edits:
        old, new, count = (*edit, 1) if len(edit) == 2 else edit
        found = text.count(old)
        if found != count:
            raise SystemExit(f"mutant {m.name}: {old!r} found {found} times, expected {count}; update the mutant")
        text = text.replace(old, new)
    return text


def run_config(rtl: Path, work: Path, config: str) -> tuple[str, str]:
    """Return ("pass" | "fail" | "invalid", detail) for one config."""
    build = work / f"icarus-{config}"
    cmd = ["make", "--no-print-directory", "-f", "tb/cocotb.mk", "SIM=icarus", f"FIR_CONFIG={config}",
           f"RTL_SOURCES={rtl}", f"SIM_BUILD={build}", f"PYTHON={sys.executable}", "sim"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (work / f"{config}.log").write_text(proc.stdout + proc.stderr)
    results = build / "results.xml"
    if not results.is_file():
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
        return "invalid", f"{config}: no results ({' | '.join(tail)})"
    problems, summary = check_file(results, expected_tests())
    if summary["tests"] == 0:
        return "invalid", f"{config}: no tests ran"
    if problems:
        return "fail", problems[0].split(": ", 1)[1][:160]
    return "pass", config


def evaluate(m: Mutant | None) -> tuple[str, str, str]:
    name = m.name if m else "baseline"
    work = WORK / name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rtl = work / "fir_stream.sv"
    rtl.write_text(mutate(RTL.read_text(), m) if m else RTL.read_text())
    for config in CONFIGS:
        status, detail = run_config(rtl, work, config)
        if status != "pass":
            return name, status, detail
    return name, "pass", "all configs passed"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="mutants to run (default: all)")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2, help="parallel simulations")
    parser.add_argument("--list", action="store_true", help="list the mutants and exit")
    args = parser.parse_args(argv)

    if args.list:
        for m in MUTANTS:
            print(f"{m.name:34} {m.bug}")
        return 0
    unknown = set(args.names) - {m.name for m in MUTANTS}
    if unknown:
        parser.error(f"unknown mutants: {', '.join(sorted(unknown))}")
    selected = [m for m in MUTANTS if not args.names or m.name in args.names]
    for m in selected:
        mutate(RTL.read_text(), m)  # validate every substitution before simulating anything

    start = time.monotonic()
    _, status, detail = evaluate(None)
    if status != "pass":
        print(f"baseline RTL does not pass the regression ({detail}); mutation results would be meaningless")
        return 1
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(evaluate, selected))

    labels = {"fail": "KILLED", "pass": "SURVIVED", "invalid": "INVALID"}
    killed = sum(status == "fail" for _, status, _ in results)
    print(f"Mutation testing: {len(results)} mutants, {killed} killed, "
          f"{len(results) - killed} not killed ({time.monotonic() - start:.0f}s)")
    bug = {m.name: m.bug for m in MUTANTS}
    for name, status, detail in results:
        print(f"  {labels[status]:8} {name:34} {bug[name]}")
        print(f"  {'':8} {'':34} -> {detail}")
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
