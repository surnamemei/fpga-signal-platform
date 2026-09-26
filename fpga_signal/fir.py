from __future__ import annotations
from .fixed import saturate_signed, round_shift

DEFAULT_COEFS_Q14 = [1024, 4096, 6144, 4096, 1024]  # symmetric low-pass-like taps; sum=1.0 in Q14


def fir_fixed(samples, coefs=DEFAULT_COEFS_Q14, sample_width=16, coef_frac_bits=14, output_width=16):
    delay = [0] * len(coefs)
    out = []
    for sample in samples:
        sample = saturate_signed(int(sample), sample_width)
        delay = [sample] + delay[:-1]
        acc = sum(int(x) * int(c) for x, c in zip(delay, coefs))
        y = round_shift(acc, coef_frac_bits)
        out.append(saturate_signed(y, output_width))
    return out
