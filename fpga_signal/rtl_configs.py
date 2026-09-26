"""Coefficient sets the RTL regression is compiled with (one simulator build each).

"default" is the production filter. It is compiled WITHOUT parameter overrides, so the
regression also proves that the defaults written in rtl/fir_stream.sv equal
DEFAULT_COEFS_Q14. The others exist because the production taps
cannot reach several arithmetic paths, so a regression run only with them could
not detect bugs there:

* "stress": asymmetric (exposes tap-order bugs that symmetric taps hide), the
  +/-2.0 extremes (signed multiply and saturation in both directions), +/-1 LSB
  taps (every rounding residue, including exact +/-0.5 LSB ties) and a 1.0 tap.
* "acc_extreme": every tap at the most negative Q14 value, giving the largest
  accumulator magnitude any 16-bit coefficient set can produce (|acc| up to
  5 * 2**30, which needs 34 bits). This checks that ACC_W is wide enough and
  that nothing wraps before saturation.

Command-line use (from the Makefiles):
    python -m fpga_signal.rtl_configs names
    python -m fpga_signal.rtl_configs iverilog-args <config> [top]
    python -m fpga_signal.rtl_configs verilator-args <config>
    python -m fpga_signal.rtl_configs yosys-args <config>
"""
from __future__ import annotations

import sys

from .fir import COEF_W, DEFAULT_COEFS_Q14, NTAPS, validate_coefs

SOURCE_DEFAULTS = "default"  # built with the RTL's own parameter defaults

RTL_CONFIGS: dict[str, tuple[int, ...]] = {
    "default": DEFAULT_COEFS_Q14,
    "stress": (32767, -32768, 1, -1, 16384),
    "acc_extreme": (-32768,) * NTAPS,
}


def coefs_for(name: str) -> tuple[int, ...]:
    try:
        coefs = RTL_CONFIGS[name]
    except KeyError:
        raise KeyError(f"unknown FIR config {name!r}; known: {', '.join(RTL_CONFIGS)}") from None
    coefs = validate_coefs(coefs)
    if len(coefs) != NTAPS:
        raise ValueError(f"config {name!r} has {len(coefs)} taps; the RTL has {NTAPS}")
    return coefs


def iverilog_args(name: str, top: str = "fir_stream") -> list[str]:
    coefs = coefs_for(name)
    return [] if name == SOURCE_DEFAULTS else [f"-P{top}.C{i}={c}" for i, c in enumerate(coefs)]


def verilator_args(name: str) -> list[str]:
    # Sized two's-complement literals: Verilator warns (WIDTHTRUNC) when a plain 32-bit integer
    # overrides a 16-bit parameter, and rejects a negated sized literal such as -16'sd32768.
    coefs = coefs_for(name)
    if name == SOURCE_DEFAULTS:
        return []
    mask = (1 << COEF_W) - 1
    return [f"-GC{i}={COEF_W}'sh{c & mask:0{(COEF_W + 3) // 4}x}" for i, c in enumerate(coefs)]


def yosys_args(name: str, top: str = "fir_stream") -> list[str]:
    # Yosys chparam takes the same sized literals as Verilator (it cannot parse a negative decimal).
    return [f"chparam -set {g[2:].replace('=', ' ', 1)} {top};" for g in verilator_args(name)]


def main(argv: list[str]) -> int:
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
    elif argv[:1] == ["names"]:
        print(" ".join(RTL_CONFIGS))
    elif argv[:1] == ["iverilog-args"] and len(argv) in (2, 3):
        print(" ".join(iverilog_args(*argv[1:])))
    elif argv[:1] == ["verilator-args"] and len(argv) == 2:
        print(" ".join(verilator_args(argv[1])))
    elif argv[:1] == ["yosys-args"] and len(argv) == 2:
        print(" ".join(yosys_args(argv[1])))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (KeyError, ValueError) as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        sys.exit(1)
