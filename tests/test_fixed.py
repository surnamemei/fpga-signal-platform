import math
from fractions import Fraction

import pytest

from fpga_signal.fixed import round_shift, saturate_signed, signed_range


def round_half_away_oracle(value: int, shift: int) -> int:
    """Independent definition: exact rational value, ties rounded away from zero."""
    q = Fraction(value, 1 << shift)
    magnitude = math.floor(abs(q) + Fraction(1, 2))
    return magnitude if q >= 0 else -magnitude


def test_saturation():
    assert saturate_signed(40000, 16) == 32767
    assert saturate_signed(-40000, 16) == -32768


def test_saturation_boundaries():
    assert [saturate_signed(v, 16) for v in (32766, 32767, 32768)] == [32766, 32767, 32767]
    assert [saturate_signed(v, 16) for v in (-32767, -32768, -32769)] == [-32767, -32768, -32768]
    assert signed_range(16) == (-32768, 32767)
    with pytest.raises(ValueError):
        signed_range(0)


def test_round_shift():
    assert round_shift(7, 1) == 4
    assert round_shift(-7, 1) == -4


def test_round_shift_ties_go_away_from_zero():
    lsb = 1 << 14
    for k in range(4):
        tie = (2 * k + 1) * (lsb // 2)  # (k + 0.5) LSB
        assert round_shift(tie, 14) == k + 1
        assert round_shift(-tie, 14) == -(k + 1)  # not banker's rounding, not round-half-up
        assert round_shift(tie - 1, 14) == k and round_shift(-(tie - 1), 14) == -k


def test_round_shift_matches_oracle_exhaustively_near_zero():
    for value in range(-(1 << 17), (1 << 17) + 1):
        assert round_shift(value, 14) == round_half_away_oracle(value, 14), value


@pytest.mark.parametrize("base", [5 * 2**30, 5 * 32767 * 32768, 2**33 - 1, 2**39 - 2**20])
def test_round_shift_matches_oracle_at_accumulator_extremes(base):
    for value in range(base - 20000, base + 20000, 7):
        for v in (value, -value):
            assert round_shift(v, 14) == round_half_away_oracle(v, 14), v


def test_round_shift_is_odd_symmetric():
    for value in range(0, 1 << 16, 3):
        assert round_shift(-value, 14) == -round_shift(value, 14)


@pytest.mark.parametrize("bad", [1.5, 1000.0, float("nan"), float("inf"), float("-inf")])
def test_floats_are_rejected_not_truncated(bad):
    with pytest.raises(TypeError):
        round_shift(bad, 14)
    with pytest.raises(TypeError):
        saturate_signed(bad, 16)
