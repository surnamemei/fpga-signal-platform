"""Bit-accurate fixed-point primitives (the numerical specification).

Every function takes exact integers. Floats are rejected with ``TypeError``
instead of being silently truncated, so a float can never leak into the
golden model or the generated vectors.
"""
from operator import index


def signed_range(width: int) -> tuple[int, int]:
    """Inclusive ``(min, max)`` of a two's-complement integer of ``width`` bits."""
    width = index(width)
    if width < 1:
        raise ValueError(f"width must be >= 1, got {width}")
    return -(1 << (width - 1)), (1 << (width - 1)) - 1


def saturate_signed(value: int, width: int) -> int:
    """Clamp ``value`` to the signed ``width``-bit range."""
    lo, hi = signed_range(width)
    return min(hi, max(lo, index(value)))


def round_shift(value: int, shift: int) -> int:
    """Return ``value / 2**shift`` rounded to nearest, ties away from zero.

    Negative values round symmetrically: ``round_shift(-v, s) == -round_shift(v, s)``,
    so -0.5 LSB becomes -1 and +0.5 LSB becomes +1.
    """
    value = index(value)
    shift = index(shift)
    if shift <= 0:
        return value << (-shift)
    half = 1 << (shift - 1)
    if value >= 0:
        return (value + half) >> shift
    return -(((-value) + half) >> shift)
