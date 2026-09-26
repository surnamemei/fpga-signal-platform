import math
import random
from fractions import Fraction

import numpy as np
import pytest

from fpga_signal.fir import (ACC_W, COEF_FRAC, COEF_W, DEFAULT_COEFS_Q14, NTAPS, SAMPLE_W, accumulator_range,
                             fir_fixed, fir_fixed_steps, signed_width_for, validate_coefs,
                             worst_case_accumulator_width)
from fpga_signal.fixed import round_shift
from fpga_signal.rtl_configs import RTL_CONFIGS


def fir_oracle(samples, coefs):
    """Independent reference: numpy convolution + exact rational rounding + clamp."""
    acc = np.convolve(np.asarray(samples, dtype=object), np.asarray(coefs, dtype=object))[:len(samples)]
    out = []
    for a in acc:
        q = Fraction(int(a), 1 << COEF_FRAC)
        y = math.floor(abs(q) + Fraction(1, 2)) * (1 if q >= 0 else -1)
        out.append(min(32767, max(-32768, y)))
    return out


def test_dc_gain_approximately_one():
    x = [1000] * 50
    y = fir_fixed(x)
    assert abs(y[-1] - 1000) <= 1


def test_10000_samples_deterministic():
    rng = np.random.default_rng(5305)
    x = rng.integers(-20000, 20001, size=10000).tolist()
    a = fir_fixed(x)
    b = fir_fixed(x)
    assert a == b
    assert len(a) == 10000
    assert sum(DEFAULT_COEFS_Q14) == (1 << 14)


def test_default_taps_are_exact_binomial_q14():
    # No quantisation error: [1, 4, 6, 4, 1] / 16 is exactly representable in Q14.
    assert [Fraction(c, 1 << COEF_FRAC) for c in DEFAULT_COEFS_Q14] == [Fraction(b, 16) for b in (1, 4, 6, 4, 1)]


def test_known_answers_hand_derived():
    gap = [0] * NTAPS
    assert fir_fixed([16384] + gap)[:NTAPS] == list(DEFAULT_COEFS_Q14)   # impulse of 1.0 reproduces the taps
    assert fir_fixed([16] + gap)[:NTAPS] == [1, 4, 6, 4, 1]
    assert fir_fixed([8] + gap)[:NTAPS] == [1, 2, 3, 2, 1]                # 0.5 LSB rounds away from zero
    assert fir_fixed([-8] + gap)[:NTAPS] == [-1, -2, -3, -2, -1]
    assert fir_fixed([2] + gap)[:NTAPS] == [0, 1, 1, 1, 0]
    assert fir_fixed([32767] * 8)[NTAPS - 1:] == [32767] * 4              # unity DC gain at full scale
    assert fir_fixed([-32768] * 8)[NTAPS - 1:] == [-32768] * 4
    assert fir_fixed([20000, -20000] * 8)[NTAPS - 1:] == [0] * 12         # zero at Nyquist
    assert fir_fixed([32767, -32768] * 8)[NTAPS - 1:] == [-1] * 12        # window sum -0.5 LSB -> -1


def test_first_output_uses_zero_history():
    assert fir_fixed([16000]) == [1000]  # only c0 * x[0]: the reset state is all zeros


@pytest.mark.parametrize("name", sorted(RTL_CONFIGS))
def test_model_matches_independent_oracle(name):
    coefs = RTL_CONFIGS[name]
    rng = random.Random(7)
    x = [rng.choice([-32768, 32767, rng.randint(-32768, 32767), rng.randint(-40, 40)]) for _ in range(5000)]
    assert fir_fixed(x, coefs) == fir_oracle(x, coefs)


def test_model_matches_oracle_for_random_coefficient_sets():
    rng = random.Random(11)
    for _ in range(40):
        coefs = [rng.randint(-32768, 32767) for _ in range(NTAPS)]
        x = [rng.randint(-32768, 32767) for _ in range(300)]
        assert fir_fixed(x, coefs) == fir_oracle(x, coefs)


def test_steps_expose_accumulator_rounding_and_saturation():
    steps = fir_fixed_steps([20000, 20000], (32767, 32767, 0, 0, 0))
    assert steps[1].acc == 20000 * 32767 * 2
    assert steps[1].rounded == 79998 and steps[1].out == 32767 and steps[1].saturated
    assert steps[0].rounded == 39999 and steps[0].saturated
    assert not fir_fixed_steps([16384])[0].saturated


def test_coefficient_validation():
    with pytest.raises(ValueError):
        validate_coefs([32768])
    with pytest.raises(ValueError):
        validate_coefs([-32769])
    with pytest.raises(ValueError):
        validate_coefs([])
    with pytest.raises(TypeError):
        validate_coefs([0.5])
    with pytest.raises(TypeError):
        fir_fixed([1.5])
    with pytest.raises(TypeError):
        fir_fixed([float("nan")])


def test_out_of_range_integer_inputs_saturate():
    # Model-only behaviour: the RTL port is 16 bits wide and cannot receive such inputs.
    assert fir_fixed([40000]) == fir_fixed([32767])
    assert fir_fixed([-40000]) == fir_fixed([-32768])


def test_accumulator_width_is_sufficient():
    assert accumulator_range(DEFAULT_COEFS_Q14) == (-32768 * 16384, 32767 * 16384)
    assert signed_width_for(*accumulator_range(DEFAULT_COEFS_Q14)) == 30
    assert accumulator_range([-32768] * NTAPS) == (-5 * 32768 * 32767, 5 * 2**30)
    assert worst_case_accumulator_width() == 34
    assert ACC_W >= worst_case_accumulator_width()
    assert ACC_W >= SAMPLE_W + COEF_W + math.ceil(math.log2(NTAPS))  # the RTL's own conservative check


def test_saturation_reachability_per_config():
    # With the production taps the rounded result always fits 16 bits, so only the "stress" and
    # "acc_extreme" RTL builds can exercise the saturation logic.
    lo, hi = accumulator_range(DEFAULT_COEFS_Q14)
    assert (round_shift(lo, COEF_FRAC), round_shift(hi, COEF_FRAC)) == (-32768, 32767)
    for name in ("stress", "acc_extreme"):
        lo, hi = accumulator_range(RTL_CONFIGS[name])
        assert round_shift(hi, COEF_FRAC) > 32767 and round_shift(lo, COEF_FRAC) < -32768
