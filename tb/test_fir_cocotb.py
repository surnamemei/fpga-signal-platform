"""RTL regression for fir_stream: every output is compared sample by sample with the golden model.

FIR_CONFIG (exported by the Makefile) names the coefficient set this simulator build was
compiled with; see fpga_signal/rtl_configs.py. All stimulus is seeded, so every run is
identical; cocotb's own global random seed is never used.
"""
import os
import random

import cocotb

from fpga_signal.fir import (ACC_W, COEF_FRAC, COEF_W, LATENCY, NTAPS, OUTPUT_W, SAMPLE_W, accumulator_range,
                             fir_fixed, worst_case_accumulator_width)
from fpga_signal.fixed import round_shift
from fpga_signal.rtl_configs import coefs_for
from fpga_signal.vectors import N_VECTORS, read_vectors
from tb.fir_bench import FirBench
from tb.fir_protocol import HALF, LSB, OMAX, OMIN, SMAX, SMIN, idle, reset, stream, with_bubbles

FIR_CONFIG = os.environ.get("FIR_CONFIG", "default")
COEFS = coefs_for(FIR_CONFIG)
GAP = [0] * (NTAPS + 1)  # zeros that flush every tap between directed patterns


def bench(dut) -> FirBench:
    return FirBench(dut, COEFS, FIR_CONFIG)


def saturation_reachable(coefs) -> bool:
    lo, hi = accumulator_range(coefs)
    return round_shift(hi, COEF_FRAC) > OMAX or round_shift(lo, COEF_FRAC) < OMIN


def ties_reachable(coefs) -> bool:
    """An exact +/-0.5 LSB accumulator needs a tap with at most COEF_FRAC-1 trailing zero bits."""
    return any(c and (abs(c) & -abs(c)) <= HALF for c in coefs)


def impulses(amplitudes) -> list[int]:
    xs = []
    for a in amplitudes:
        xs += [a] + GAP
    return xs


def rounding_probe_amplitudes(coefs) -> list[int]:
    """Impulse amplitudes whose product with some tap lands on, just below or just above +/-0.5 LSB,
    plus the largest-magnitude exact tie of each sign."""
    picks = set()
    for c in coefs:
        closest: dict[tuple, tuple] = {}
        largest_tie: dict[bool, int] = {}
        for a in range(SMIN, SMAX + 1):
            p = a * c
            if p == 0:
                continue
            rem = abs(p) % LSB
            side = "tie" if rem == HALF else "below" if rem < HALF else "above"
            score = (abs(rem - HALF), abs(a))  # closest to the tie, then smallest amplitude
            if (p > 0, side) not in closest or score < closest[(p > 0, side)][0]:
                closest[(p > 0, side)] = (score, a)
            if side == "tie" and abs(a) > abs(largest_tie.get(p > 0, 0)):
                largest_tie[p > 0] = a
        picks.update(a for _, a in closest.values())
        picks.update(largest_tie.values())
    return sorted(picks)


def saturation_probe_amplitudes(coefs) -> list[int]:
    """Impulse amplitudes whose single-tap result lands just inside and just outside each rail."""
    picks = set()
    for c in coefs:
        edges: dict[str, tuple] = {}
        for a in range(SMIN, SMAX + 1):
            y = round_shift(a * c, COEF_FRAC)
            for key, ok, dist in (("in_hi", y <= OMAX, OMAX - y), ("out_hi", y > OMAX, y - OMAX),
                                  ("in_lo", y >= OMIN, y - OMIN), ("out_lo", y < OMIN, OMIN - y)):
                if ok and (key not in edges or (dist, abs(a)) < edges[key][0]):
                    edges[key] = ((dist, abs(a)), a)
        picks.update(a for _, a in edges.values())
    return sorted(picks)


@cocotb.test()
async def test_rtl_parameters_match_model(dut):
    """The compiled RTL has the golden model's widths, Q format and latency, and this config's taps."""
    expected = {"SAMPLE_W": SAMPLE_W, "COEF_W": COEF_W, "COEF_FRAC": COEF_FRAC, "ACC_W": ACC_W,
                "LATENCY": LATENCY, **{f"C{i}": c for i, c in enumerate(COEFS)}}
    actual = {name: getattr(dut, name).value.to_signed() for name in expected}
    assert actual == expected, f"RTL parameters {actual} differ from golden model / FIR_CONFIG={FIR_CONFIG}"
    assert (len(dut.sample_in), len(dut.sample_out)) == (SAMPLE_W, OUTPUT_W)
    assert ACC_W >= worst_case_accumulator_width(), "accumulator can overflow for some 16-bit coefficient set"
    dut._log.info("[%s] taps %s, Q%d, ACC_W %d (worst case needs %d), latency %d, saturation %s, "
                  "+/-0.5 LSB ties %s", FIR_CONFIG, COEFS, COEF_FRAC, ACC_W, worst_case_accumulator_width(),
                  LATENCY, "reachable" if saturation_reachable(COEFS) else "unreachable with these taps",
                  "reachable" if ties_reachable(COEFS) else "unreachable with these taps")


@cocotb.test()
async def test_reset_clears_state_and_drops_samples(dut):
    """Samples offered while rst=1 are dropped, X on in_valid/sample_in during reset is overridden,
    and after reset the history is zero and the outputs are 0."""
    rng = random.Random(0x5EED02)
    stim = (reset(2, rng, valid=None) + reset(4, rng, valid=True) + stream([16384] + GAP)
            + reset(1, rng, valid=True) + stream([-16384] + GAP))
    rep = await bench(dut).run("reset clears state", stim, require={"dropped_in_reset": 5}, seed=2)
    # Model-independent known answer: an impulse of 2**14 reproduces the taps exactly.
    assert rep.outputs[:NTAPS] == list(COEFS), f"impulse 16384 gave {rep.outputs[:NTAPS]}, taps are {COEFS}"
    negated = [min(OMAX, max(OMIN, -c)) for c in COEFS]
    assert rep.outputs[len(GAP) + 1:][:NTAPS] == negated


@cocotb.test()
async def test_gate0_vectors_10000(dut):
    """The 10,000 deterministic Gate 0 vectors (seed 5305), streamed back to back."""
    rows = read_vectors()
    assert len(rows) == N_VECTORS, f"vectors.csv has {len(rows)} rows, expected {N_VECTORS}: run `make vectors`"
    xs = [x for x, _ in rows]
    if FIR_CONFIG == "default":
        stale = [i for i, ((_, y), m) in enumerate(zip(rows, fir_fixed(xs))) if y != m]
        assert not stale, f"vectors.csv disagrees with the golden model at rows {stale[:5]}: run `make vectors`"
    rep = await bench(dut).run("gate0 vectors 10000", stream(xs), seed=3)
    assert rep.accepted == N_VECTORS
    if FIR_CONFIG == "default":
        assert rep.outputs == [y for _, y in rows], "RTL differs from the expected_out column of vectors.csv"


@cocotb.test()
async def test_gate0_vectors_with_bubbles(dut):
    """The same 10,000 inputs with random in_valid gaps carrying X on sample_in: idle cycles must not
    disturb the delay line or let X reach the outputs."""
    xs = [x for x, _ in read_vectors()]
    rng = random.Random(0x5EED04)
    await bench(dut).run("gate0 vectors with bubbles", with_bubbles(xs, rng, x_data=True), require={"idle": 2000},
                         seed=4)


@cocotb.test()
async def test_impulse_response(dut):
    """Impulses of assorted amplitudes, including +/-full scale and +/-0.5 LSB ties."""
    amps = [16384, -16384, 1, -1, 2, -2, 8, -8, 16, -16, 8192, -8192, SMAX, SMIN, 12345, -12345]
    rep = await bench(dut).run("impulse response", stream(impulses(amps)), seed=5)
    got = {a: rep.outputs[k * (len(GAP) + 1):][:NTAPS] for k, a in enumerate(amps)}
    assert got[16384] == list(COEFS)
    if FIR_CONFIG == "default":
        # Hand-derived answers for taps [1,4,6,4,1]/16, independent of the Python model.
        assert got[16] == [1, 4, 6, 4, 1]
        assert got[8] == [1, 2, 3, 2, 1] and got[-8] == [-1, -2, -3, -2, -1]  # +/-0.5 rounds away from 0
        assert got[2] == [0, 1, 1, 1, 0] and got[-2] == [0, -1, -1, -1, 0]
        assert got[1] == [0] * NTAPS and got[-1] == [0] * NTAPS


@cocotb.test()
async def test_zero_input(dut):
    """Zero input gives exactly zero output, and a burst is fully flushed NTAPS samples after it ends."""
    rng = random.Random(0x5EED06)
    burst = [rng.choice([SMIN, SMAX, rng.randint(SMIN, SMAX)]) for _ in range(8)]
    xs = [0] * 64 + burst + [0] * 16
    rep = await bench(dut).run("zero input", stream(xs), seed=6)
    assert rep.outputs[:64] == [0] * 64
    assert rep.outputs[64 + len(burst) + NTAPS - 1:] == [0] * (16 - NTAPS + 1)


@cocotb.test()
async def test_full_scale(dut):
    """Sustained, stepped and single-sample full-scale and near-full-scale inputs."""
    levels = [SMAX, SMIN, SMAX - 1, SMIN + 1, 16384, -16384]
    runs = [[lvl] * (NTAPS + 3) for lvl in levels]
    xs = [v for run in runs for v in run]
    xs += [SMIN] * 8 + [SMAX] * 8 + [SMIN] * 8 + GAP + [SMAX] + GAP + [SMIN] + GAP
    xs += list(range(SMAX - 40, SMAX + 1)) + list(range(SMIN, SMIN + 41))
    rep = await bench(dut).run("full scale", stream(xs), seed=7)
    if FIR_CONFIG == "default":
        # Unity DC gain: once the window is full of one level, the output equals that level exactly.
        for k, run in enumerate(runs):
            settled = rep.outputs[k * len(run):][NTAPS - 1:len(run)]
            assert settled == run[NTAPS - 1:], f"DC level {run[0]} settled to {settled}"


@cocotb.test()
async def test_alternating_sign(dut):
    """Alternating-sign inputs: Nyquist-rate full scale, small values and fs/4 patterns."""
    blocks = [[SMAX, SMIN] * 12, [1, -1] * 12, [8, -8] * 12, [16384, -16384] * 12, [20000, -20000] * 12,
              [SMAX, SMAX, SMIN, SMIN] * 6, [SMIN, SMAX] * 12]
    rep = await bench(dut).run("alternating sign", stream([v for b in blocks for v in b]), seed=8)
    if FIR_CONFIG == "default":
        # [1,4,6,4,1]/16 has a zero at Nyquist: symmetric +/-A settles to exactly 0. For +32767/-32768
        # every full window sums to -8192 = -0.5 LSB, which must round away from zero to -1.
        base = 0
        for b in blocks:
            settled = rep.outputs[base + NTAPS - 1:base + len(b)]
            if b[:2] in ([1, -1], [8, -8], [16384, -16384], [20000, -20000]):
                assert settled == [0] * len(settled), f"{b[:2]} settled to {settled}"
            if b[:2] in ([SMAX, SMIN], [SMIN, SMAX]):
                assert settled == [-1] * len(settled), f"{b[:2]} settled to {settled}"
            base += len(b)


@cocotb.test()
async def test_rounding_boundaries(dut):
    """Products landing exactly on, just below and just above +/-0.5 LSB for every tap."""
    amps = rounding_probe_amplitudes(COEFS)
    require = {"ties_pos": 1, "ties_neg": 1} if ties_reachable(COEFS) else {}
    await bench(dut).run("rounding boundaries", stream(impulses(amps)), require=require, seed=9)


@cocotb.test()
async def test_saturation(dut):
    """Results just inside and just outside both rails, sustained extremes and a full-scale random run."""
    rng = random.Random(0x5EED0A)
    xs = impulses(saturation_probe_amplitudes(COEFS))
    for lvl in (SMAX, SMIN):
        xs += [lvl] * (NTAPS + 3) + GAP
    xs += [SMAX, SMIN] * 8 + [SMIN, SMAX] * 8 + GAP
    xs += [rng.randint(SMIN, SMAX) for _ in range(2000)]
    reachable = saturation_reachable(COEFS)
    require = {"sat_pos": 1, "sat_neg": 1} if reachable else {"rail_pos": 1, "rail_neg": 1}
    await bench(dut).run("saturation", stream(xs), require=require, seed=10)


@cocotb.test()
async def test_reset_during_stream(dut):
    """Resets mid-stream, directly after an accepted sample, during idle and during bubbles."""
    rng = random.Random(0x5EED0B)

    def rand(n):
        return [rng.randint(SMIN, SMAX) for _ in range(n)]

    stim = (stream(rand(40)) + reset(1, rng, valid=True)       # one-cycle reset, offered sample dropped
            + stream(rand(30)) + reset(3, rng, valid=True)     # multi-cycle reset
            + stream(rand(1)) + reset(1, rng)                  # reset on the edge after an accepted sample:
            + idle(5, rng) + reset(2, rng)                     #   that sample's output must still appear
            + with_bubbles(rand(40), rng) + reset(1, rng, valid=True)
            + stream(rand(NTAPS + 5)))
    await bench(dut).run("reset during stream", stim, require={"resets": 6, "dropped_in_reset": 5}, seed=11)


@cocotb.test()
async def test_random_soak(dut):
    """20,000 seeded cycles mixing full-scale data, extremes, small values, bubbles and rare resets."""
    rng = random.Random(0x5EED0C)
    stim = []
    while len(stim) < 20_000:
        u = rng.random()
        if u < 0.002:
            stim += reset(rng.randint(1, 3), rng, valid=rng.random() < 0.5)
        elif u < 0.2:
            stim += idle(rng.randint(1, 6), rng, x_data=rng.random() < 0.5)
        elif u < 0.3:
            stim += stream([rng.choice([SMIN, SMIN + 1, SMAX - 1, SMAX])])
        elif u < 0.4:
            stim += stream([rng.randint(-16, 16)])
        else:
            stim += stream([rng.randint(SMIN, SMAX)])
    require = {"resets": 3, "sat_pos": 1, "sat_neg": 1} if saturation_reachable(COEFS) else {"resets": 3}
    await bench(dut).run("random soak", stim, require=require, seed=12)
