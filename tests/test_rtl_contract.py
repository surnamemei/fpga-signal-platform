"""Cross-checks between rtl/fir_stream.sv and the golden model that need no simulator.

The cocotb regression checks the same things on the elaborated design; these fail
earlier (plain `pytest`) when the two sources drift apart.
"""
import re
from pathlib import Path

import pytest

from fpga_signal.fir import ACC_W, COEF_FRAC, COEF_W, DEFAULT_COEFS_Q14, LATENCY, NTAPS, SAMPLE_W
from fpga_signal.rtl_configs import RTL_CONFIGS, coefs_for, iverilog_args, main, verilator_args, yosys_args

RTL = (Path(__file__).resolve().parents[1] / "rtl" / "fir_stream.sv").read_text()


def rtl_param(name):
    m = re.search(rf"\b(?:parameter|localparam)\b[^;,)]*?\b{name}\s*=\s*([^,;\n]+)", RTL)
    assert m, f"{name} not found in fir_stream.sv"
    value = m.group(1).strip()
    sized = re.fullmatch(r"(-?)\d+'sd(\d+)", value)
    return int(sized.group(1) + sized.group(2)) if sized else int(value)


def test_rtl_widths_and_format_match_model():
    assert (rtl_param("SAMPLE_W"), rtl_param("COEF_W"), rtl_param("COEF_FRAC"), rtl_param("ACC_W"),
            rtl_param("LATENCY"), rtl_param("NTAPS")) == (SAMPLE_W, COEF_W, COEF_FRAC, ACC_W, LATENCY, NTAPS)


def test_rtl_default_taps_match_model():
    assert tuple(rtl_param(f"C{i}") for i in range(NTAPS)) == DEFAULT_COEFS_Q14


def test_rtl_has_no_board_specific_content():
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", RTL, flags=re.S).lower()
    for word in ("ibuf", "bufg", "mmcm", "pll", "uart", "i2s", "package_pin", "iostandard"):
        assert word not in code, word


@pytest.mark.parametrize("name", sorted(RTL_CONFIGS))
def test_configs_are_valid_five_tap_q14_sets(name):
    coefs = coefs_for(name)
    assert len(coefs) == NTAPS and all(-32768 <= c <= 32767 for c in coefs)


def test_default_config_uses_rtl_source_defaults():
    assert coefs_for("default") == DEFAULT_COEFS_Q14
    assert iverilog_args("default") == [] and verilator_args("default") == []


def test_stress_config_can_expose_tap_order_bugs():
    coefs = coefs_for("stress")
    assert coefs != coefs[::-1]
    assert {1, -1, 16384, 32767, -32768} <= set(coefs)


def test_override_argument_formats():
    assert iverilog_args("stress")[1] == "-Pfir_stream.C1=-32768"
    assert verilator_args("stress")[1] == "-GC1=16'sh8000"
    assert verilator_args("stress")[3] == "-GC3=16'shffff"
    assert yosys_args("stress")[1] == "chparam -set C1 16'sh8000 fir_stream;"
    assert yosys_args("default") == []


def test_unknown_config_is_an_error():
    with pytest.raises(KeyError, match="unknown FIR config"):
        coefs_for("nope")


def test_cli(capsys):
    assert main(["names"]) == 0
    assert capsys.readouterr().out.split() == list(RTL_CONFIGS)
    assert main([]) == 2
