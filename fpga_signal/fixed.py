def saturate_signed(value: int, width: int) -> int:
    lo = -(1 << (width - 1))
    hi = (1 << (width - 1)) - 1
    return min(hi, max(lo, int(value)))


def round_shift(value: int, shift: int) -> int:
    if shift <= 0:
        return int(value) << (-shift)
    half = 1 << (shift - 1)
    if value >= 0:
        return (int(value) + half) >> shift
    return -(((-int(value)) + half) >> shift)
