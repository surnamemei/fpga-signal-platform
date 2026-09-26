"""Cross-check the RTL on Icarus Verilog and Verilator with the plain-SystemVerilog testbench.

For each coefficient config this writes a per-cycle stimulus/expectation file (the 10,000
Gate 0 vectors, the same inputs with idle bubbles, directed extremes, resets with samples
offered during reset, and a full-scale random run), then builds tb/fir_stream_tb.sv with
both simulators and runs it. Expected values come from the golden model through
tb/fir_protocol.py. Verilator starts from randomised register state (--x-initial unique,
+verilator+rand+reset+2), which also shows that nothing depends on power-up values.

    python verification/xsim.py [config ...]      (make xsim)
"""
from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fpga_signal.rtl_configs import RTL_CONFIGS, coefs_for, iverilog_args, verilator_args  # noqa: E402
from fpga_signal.vectors import read_vectors  # noqa: E402
from tb.fir_protocol import SMAX, SMIN, expected_trace, idle, reset, stream, with_bubbles  # noqa: E402

TB = ROOT / "tb" / "fir_stream_tb.sv"
RTL = ROOT / "rtl" / "fir_stream.sv"
WORK = ROOT / "sim_build" / "xsim"
TOP = "fir_stream_tb"


def program(seed: int = 0x5EED) -> list:
    rng = random.Random(seed)
    xs = [x for x, _ in read_vectors()]
    gap = [0] * 6
    directed = []
    for a in (16384, -16384, 8, -8, 1, -1, SMAX, SMIN):
        directed += [a] + gap
    directed += [SMAX] * 8 + [SMIN] * 8 + [SMAX, SMIN] * 12 + gap
    return (reset(2, rng) + stream(xs) + with_bubbles(xs[:2000], rng) + stream(directed)
            + reset(1, rng, valid=True) + stream([rng.randint(SMIN, SMAX) for _ in range(40)])
            + reset(3, rng, valid=True) + stream([rng.randint(SMIN, SMAX)]) + reset(1, rng)
            + with_bubbles([rng.randint(SMIN, SMAX) for _ in range(3000)], rng) + idle(4, rng))


def write_vectors(prog, coefs, path: Path) -> int:
    trace = expected_trace(prog, coefs)
    lines = []
    for j, d in enumerate(prog):
        assert d.sample is not None and d.valid is not None, "the SV testbench is 2-state; no X stimulus"
        exp = trace[j + 2]  # the outputs registered by the edge that samples prog[j]
        lines.append(f"{int(d.rst)} {int(d.valid)} {d.sample} {exp.valid} {exp.data}\n")
    path.write_text("".join(lines))
    return len(lines)


def run(cmd: list[str], log: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    with log.open("a") as f:
        f.write("$ " + " ".join(cmd) + "\n" + out + "\n")
    return proc.returncode, out


def simulate(sim: str, config: str, vectors: Path, cycles: int) -> tuple[bool, str]:
    build = WORK / f"{sim}-{config}"
    build.mkdir(parents=True, exist_ok=True)
    log = build / "run.log"
    log.write_text("")
    plusargs = [f"+vectors={vectors}"]
    if sim == "icarus":
        params = iverilog_args(config, top=TOP)
        params += [f"-P{TOP}.OVERRIDE=1"] if params else []
        compile_cmd = ["iverilog", "-g2012", "-Wall", "-s", TOP, "-o", str(build / "tb.vvp"), *params,
                       str(TB), str(RTL)]
        run_cmd = ["vvp", "-n", str(build / "tb.vvp"), *plusargs]
    else:
        params = verilator_args(config)
        params += ["-GOVERRIDE=1'b1"] if params else []
        compile_cmd = ["verilator", "--binary", "--timing", "-Wall", "-j", "0", "--x-assign", "unique",
                       "--x-initial", "unique", "--top-module", TOP, "-Mdir", str(build / "obj"), "-o", "Vtb",
                       *params, str(TB), str(RTL)]
        run_cmd = [str(build / "obj" / "Vtb"), *plusargs, "+verilator+rand+reset+2", "+verilator+seed+5305"]
    rc, out = run(compile_cmd, log)
    if rc != 0:
        return False, f"compile failed (see {log})"
    rc, out = run(run_cmd, log)
    passed = [line for line in out.splitlines() if line.startswith("PASS:")]
    expected = f"PASS: {cycles} cycles,"
    if rc != 0 or len(passed) != 1 or not passed[0].startswith(expected):
        detail = next((line for line in out.splitlines() if "FAIL" in line or "MISMATCH" in line), out[-200:])
        return False, detail.strip()
    return True, passed[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("configs", nargs="*", default=list(RTL_CONFIGS), help="coefficient configs")
    args = parser.parse_args(argv)
    prog = program()
    ok = True
    print("SystemVerilog cross-check (tb/fir_stream_tb.sv)")
    for config in args.configs:
        vectors = WORK / f"{config}.txt"
        vectors.parent.mkdir(parents=True, exist_ok=True)
        cycles = write_vectors(prog, coefs_for(config), vectors)
        for sim in ("icarus", "verilator"):
            passed, detail = simulate(sim, config, vectors, cycles)
            ok &= passed
            print(f"  {'PASS' if passed else 'FAIL'}  {sim:9} {config:12} {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
