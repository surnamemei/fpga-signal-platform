from fpga_signal.fixed import saturate_signed, round_shift

def test_saturation():
    assert saturate_signed(40000, 16) == 32767
    assert saturate_signed(-40000, 16) == -32768

def test_round_shift():
    assert round_shift(7, 1) == 4
    assert round_shift(-7, 1) == -4
