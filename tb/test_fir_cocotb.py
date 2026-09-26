import csv
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

@cocotb.test()
async def vectors_match(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst.value = 1; dut.in_valid.value = 0; dut.sample_in.value = 0
    for _ in range(3): await RisingEdge(dut.clk)
    dut.rst.value = 0
    rows = list(csv.DictReader(Path("verification/vectors.csv").open()))
    for i, row in enumerate(rows):
        dut.in_valid.value = 1
        dut.sample_in.value = int(row["sample_in"]) & 0xFFFF
        await RisingEdge(dut.clk)
        got = dut.sample_out.value.signed_integer
        expected = int(row["expected_out"])
        assert got == expected, f"mismatch at {i}: got {got}, expected {expected}"
