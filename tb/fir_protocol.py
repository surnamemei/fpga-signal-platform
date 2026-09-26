"""Cycle-level stimulus and expected-output model for fir_stream (no cocotb dependency).

Shared by the cocotb harness (tb/fir_bench.py) and the SystemVerilog cross-check
(verification/xsim.py). ``prog[j]`` is the input set sampled by rising edge ``j + 1``;
``expected_trace`` gives what a downstream register must capture at each edge.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from fpga_signal.fir import COEF_FRAC, LATENCY, OUTPUT_W, SAMPLE_W, FirStep, fir_fixed_steps
from fpga_signal.fixed import signed_range

SMIN, SMAX = signed_range(SAMPLE_W)
OMIN, OMAX = signed_range(OUTPUT_W)
LSB = 1 << COEF_FRAC          # accumulator counts per output LSB
HALF = 1 << (COEF_FRAC - 1)   # accumulator remainder of an exact 0.5 LSB tie


@dataclass(frozen=True)
class Drive:
    """Inputs presented to one rising clock edge. ``None`` drives X (cocotb only): allowed for
    ``sample`` whenever it must be ignored, and for ``valid`` only while ``rst`` is high."""

    rst: bool = False
    valid: bool | None = False
    sample: int | None = 0


def stream(xs) -> list[Drive]:
    return [Drive(valid=True, sample=int(x)) for x in xs]


def idle(n: int, rng: random.Random, x_data: bool = False) -> list[Drive]:
    """``n`` cycles with in_valid=0. sample_in carries random data (or X) that must be ignored."""
    return [Drive(sample=None if x_data else rng.randint(SMIN, SMAX)) for _ in range(n)]


def reset(n: int, rng: random.Random, valid: bool | None = False) -> list[Drive]:
    """``n`` reset cycles. With ``valid=True`` a random sample is offered each cycle and must be
    dropped; with ``valid=None`` in_valid and sample_in are X, which reset must override."""
    sample = (lambda: None) if valid is None else (lambda: rng.randint(SMIN, SMAX))
    return [Drive(rst=True, valid=valid, sample=sample()) for _ in range(n)]


def with_bubbles(xs, rng: random.Random, p_gap=0.25, max_gap=4, x_data: bool = False) -> list[Drive]:
    """``xs`` as valid samples with random idle gaps between them."""
    prog = []
    for x in xs:
        if rng.random() < p_gap:
            prog += idle(rng.randint(1, max_gap), rng, x_data)
        prog.append(Drive(valid=True, sample=int(x)))
    return prog


@dataclass
class Expect:
    valid: int
    data: int | None                # None only before the first reset
    kind: str                       # "out", "hold" or "reset"
    index: int | None = None        # index of the accepted sample (kind == "out")
    x: int | None = None
    step: FirStep | None = None


def expected_trace(prog: list[Drive], coefs) -> dict[int, Expect]:
    """Expected (out_valid, sample_out) captured at each edge, from the contract and golden model."""
    assert LATENCY == 1, "hold/reset expectations model a single output register; update for deeper pipelines"
    # The golden model runs once per reset-delimited segment, each starting from the reset state.
    results: dict[int, tuple[int, FirStep]] = {}
    segment: list[tuple[int, int]] = []

    def flush():
        for (j, x), step in zip(segment, fir_fixed_steps([x for _, x in segment], coefs)):
            results[j] = (x, step)
        segment.clear()

    for j, d in enumerate(prog):
        if d.rst:
            flush()
        elif d.valid:
            segment.append((j, d.sample))
    flush()

    trace: dict[int, Expect] = {}
    held = None
    n = 0
    for j, d in enumerate(prog):
        capture = j + 1 + LATENCY  # sampled at edge j+1, captured downstream LATENCY edges later
        if d.rst:
            held = 0
            trace[capture] = Expect(0, 0, "reset")
        elif d.valid:
            x, step = results[j]
            held = step.out
            trace[capture] = Expect(1, step.out, "out", n, x, step)
            n += 1
        else:
            trace[capture] = Expect(0, held, "hold")
    return trace
