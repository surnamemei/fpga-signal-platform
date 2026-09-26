"""Golden fixed-point FIR model: the numerical specification for rtl/fir_stream.sv.

Contract v1 (docs/fir_contract.md):

    acc[n] = sum_k c[k] * x[n-k]                exact, c[0] multiplies the newest sample
    y[n]   = sat16(round_half_away(acc[n] / 2**14))

with x[n-k] = 0 before the first sample (the state after reset).
"""
from __future__ import annotations

from dataclasses import dataclass
from operator import index

from .fixed import round_shift, saturate_signed, signed_range

SAMPLE_W = 16    # signed input sample width
COEF_W = 16      # signed coefficient width
COEF_FRAC = 14   # coefficients are Q14 (Q2.14): 16384 == 1.0
OUTPUT_W = 16    # signed output width
NTAPS = 5
ACC_W = 40       # RTL accumulator width; must be >= worst_case_accumulator_width()
LATENCY = 1      # RTL clock cycles from the accepting edge to out_valid (timing contract)

DEFAULT_COEFS_Q14 = (1024, 4096, 6144, 4096, 1024)  # binomial [1,4,6,4,1]/16 low-pass; sum=1.0 in Q14


@dataclass(frozen=True)
class FirStep:
    """One output sample with the intermediate values that produced it."""

    acc: int      # full-precision accumulator (exact integer)
    rounded: int  # round_shift(acc, COEF_FRAC), before saturation
    out: int      # saturated output sample

    @property
    def saturated(self) -> bool:
        return self.out != self.rounded


def validate_coefs(coefs, coef_width=COEF_W) -> tuple[int, ...]:
    """Return ``coefs`` as a tuple of ints, rejecting values that do not fit ``coef_width`` bits."""
    lo, hi = signed_range(coef_width)
    checked = tuple(index(c) for c in coefs)
    if not checked:
        raise ValueError("at least one coefficient is required")
    bad = [c for c in checked if not lo <= c <= hi]
    if bad:
        raise ValueError(f"coefficients {bad} do not fit a signed {coef_width}-bit word [{lo}, {hi}]")
    return checked


def fir_fixed_steps(samples, coefs=DEFAULT_COEFS_Q14, sample_width=SAMPLE_W,
                    coef_frac_bits=COEF_FRAC, output_width=OUTPUT_W, coef_width=COEF_W):
    """Run the golden model and return a :class:`FirStep` per input sample."""
    coefs = validate_coefs(coefs, coef_width)
    delay = [0] * len(coefs)
    steps = []
    for sample in samples:
        sample = saturate_signed(index(sample), sample_width)
        delay = [sample] + delay[:-1]
        acc = sum(x * c for x, c in zip(delay, coefs))
        rounded = round_shift(acc, coef_frac_bits)
        steps.append(FirStep(acc, rounded, saturate_signed(rounded, output_width)))
    return steps


def fir_fixed(samples, coefs=DEFAULT_COEFS_Q14, sample_width=SAMPLE_W,
              coef_frac_bits=COEF_FRAC, output_width=OUTPUT_W, coef_width=COEF_W):
    """Filter ``samples`` from the reset state and return the output samples."""
    steps = fir_fixed_steps(samples, coefs, sample_width, coef_frac_bits, output_width, coef_width)
    return [s.out for s in steps]


def accumulator_range(coefs, sample_width=SAMPLE_W) -> tuple[int, int]:
    """Exact ``(min, max)`` accumulator value over every possible input history."""
    xmin, xmax = signed_range(sample_width)
    lo = sum(min(c * xmin, c * xmax) for c in coefs)
    hi = sum(max(c * xmin, c * xmax) for c in coefs)
    return lo, hi


def signed_width_for(lo: int, hi: int) -> int:
    """Smallest two's-complement width that holds every integer in ``[lo, hi]``."""
    width = 1
    while True:
        wlo, whi = signed_range(width)
        if wlo <= lo and hi <= whi:
            return width
        width += 1


def worst_case_accumulator_width(ntaps=NTAPS, sample_width=SAMPLE_W, coef_width=COEF_W) -> int:
    """Accumulator width needed for *any* ``coef_width``-bit coefficient set.

    The most negative coefficient gives the largest product magnitude of both signs
    (-2**15 * -2**15 = +2**30 and -2**15 * (2**15 - 1)), so it bounds every tap.
    """
    cmin, _ = signed_range(coef_width)
    return signed_width_for(*accumulator_range([cmin] * ntaps, sample_width))
