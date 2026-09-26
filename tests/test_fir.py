import numpy as np
from fpga_signal.fir import fir_fixed, DEFAULT_COEFS_Q14

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
