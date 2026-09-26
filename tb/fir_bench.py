"""Cycle-accurate cocotb harness for rtl/fir_stream.sv: driver, monitor and scoreboard.

Timing discipline (independent of simulator event ordering)
    Inputs are written and outputs are read on the FALLING clock edge, half a period
    away from the rising edge that samples inputs and updates outputs. ``prog[j]`` is
    sampled by rising edge ``j + 1``. The outputs read after rising edge ``e`` are what
    a downstream register captures at edge ``e + 1``. The original test read outputs
    directly after ``RisingEdge``, which returns pre-edge values under Icarus, and so
    compared every RTL sample with the next sample's expectation.

Scoreboard
    The expected value of every cycle comes from the timing contract plus the golden
    model: a sample accepted at edge ``e`` must be captured (out_valid=1, exact value)
    at edge ``e + LATENCY``; out_valid is 0 on every other cycle; sample_out holds
    while out_valid=0 and is 0 after reset. Dropped, duplicated, early, late and X/Z
    outputs therefore all fail, and the report lists sample index, input, expected,
    RTL value, error and neighbouring samples. A watcher also fails any output
    change that is not exactly on a rising clock edge (an asynchronous reset or a
    combinational output path), which falling-edge sampling alone could not see.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import cocotb
from cocotb.clock import Clock
from cocotb.simtime import get_sim_time
from cocotb.triggers import FallingEdge, Timer, ValueChange
from cocotb.types import Logic, LogicArray

from fpga_signal.fir import LATENCY, SAMPLE_W, FirStep
from tb.fir_protocol import HALF, LSB, OMAX, OMIN, SMAX, SMIN, Drive, Expect, expected_trace, idle, reset

CLK_PERIOD_NS = 10
CLK_PERIOD_PS = CLK_PERIOD_NS * 1000
MAX_REPORTED = 10
CONTEXT = 3


@dataclass
class Report:
    name: str
    config: str
    cycles: int = 0
    accepted: int = 0
    idle: int = 0
    reset_cycles: int = 0
    resets: int = 0
    dropped_in_reset: int = 0
    ties_pos: int = 0
    ties_neg: int = 0
    sat_pos: int = 0
    sat_neg: int = 0
    rail_pos: int = 0
    rail_neg: int = 0
    max_abs_acc: int = 0
    outputs: list[int | None] = field(default_factory=list)  # RTL value per accepted sample
    errors: list[dict] = field(default_factory=list)

    def coverage(self) -> str:
        return (f"ties +0.5:{self.ties_pos} -0.5:{self.ties_neg} | saturated +:{self.sat_pos} -:{self.sat_neg}"
                f" | exact rails +:{self.rail_pos} -:{self.rail_neg} | max|acc| {self.max_abs_acc}"
                f" ({self.max_abs_acc.bit_length() + 1} bits signed)")


class FirBench:
    def __init__(self, dut, coefs, config: str):
        self.dut = dut
        self.coefs = tuple(coefs)
        self.config = config

    async def run(self, name: str, stimulus: list[Drive], *, require: dict[str, int] | None = None,
                  reset_cycles: int = 2, drain: int = 4, seed: int = 0) -> Report:
        """Reset, drive ``stimulus`` one entry per clock, drain, then check every captured cycle."""
        rng = random.Random(seed)
        prog = reset(reset_cycles, rng) + list(stimulus) + idle(LATENCY + drain, rng)
        for j, d in enumerate(prog):
            if d.sample is not None and not SMIN <= d.sample <= SMAX:
                # cocotb would silently wrap e.g. 40000 into a 16-bit port; that is a testbench bug.
                raise ValueError(f"stimulus {j} sample {d.sample} outside [{SMIN}, {SMAX}]")
            if (d.valid is None and not d.rst) or (d.sample is None and d.valid and not d.rst):
                raise ValueError(f"stimulus {j} drives X on an input the contract does not let the DUT ignore")
        captured = await self._execute(prog)
        report = self._check(name, prog, captured)
        self._require(report, require or {})
        self.dut._log.info("[%s] %s: %d outputs checked, 0 mismatches, latency %d cycle | %s",
                           self.config, name, report.accepted, LATENCY, report.coverage())
        return report

    def _apply(self, d: Drive) -> None:
        self.dut.rst.value = int(d.rst)
        self.dut.in_valid.value = Logic("X") if d.valid is None else int(d.valid)
        self.dut.sample_in.value = LogicArray("X" * SAMPLE_W) if d.sample is None else d.sample

    @staticmethod
    async def _watch(signal, changes: list) -> None:
        while True:
            await ValueChange(signal)
            changes.append((int(get_sim_time("ps")), signal._name, str(signal.value)))

    async def _execute(self, prog: list[Drive]) -> dict[int, tuple]:
        dut = self.dut
        dut.clk.value = 0
        self._apply(prog[0])                 # sampled by the first rising edge
        await Timer(1, "ns")
        t0 = int(get_sim_time("ps"))
        changes: list[tuple] = []
        watchers = [cocotb.start_soon(self._watch(sig, changes)) for sig in (dut.out_valid, dut.sample_out)]
        clock = Clock(dut.clk, CLK_PERIOD_NS, unit="ns")
        clock.start(start_high=False)        # rising edges at t0 + (k - 1/2) T, falling at t0 + k T
        captured = {}
        for edge in range(1, len(prog) + 1):
            await FallingEdge(dut.clk)
            now = int(get_sim_time("ps"))
            if now != t0 + edge * CLK_PERIOD_PS:
                raise RuntimeError(f"bench lost cycle alignment: falling edge {edge} at {now} ps, "
                                   f"expected {t0 + edge * CLK_PERIOD_PS} ps")
            captured[edge + 1] = (dut.out_valid.value, dut.sample_out.value)
            if edge < len(prog):
                self._apply(prog[edge])      # sampled by rising edge edge+1
        clock.stop()
        for w in watchers:
            w.cancel()
        off_edge = [c for c in changes if (c[0] - t0 + CLK_PERIOD_PS // 2) % CLK_PERIOD_PS]
        if off_edge:
            detail = ", ".join(f"{name}={value} at {(t - t0) / 1000:g} ns" for t, name, value in off_edge[:5])
            raise AssertionError(f"[{self.config}] outputs changed {len(off_edge)} times away from a rising "
                                 f"clock edge (edges at {CLK_PERIOD_NS / 2:g} ns + k*{CLK_PERIOD_NS} ns): {detail}")
        return captured

    def _check(self, name: str, prog: list[Drive], captured: dict[int, tuple]) -> Report:
        trace = expected_trace(prog, self.coefs)
        r = Report(name, self.config, cycles=len(prog))
        inputs: list[int] = []
        expected: list[int] = []
        steps: list[FirStep] = []
        edge_of: list[int] = []
        prev_rst = False
        for d in prog:
            r.accepted += bool(d.valid and not d.rst)
            r.idle += bool(not d.valid and not d.rst)
            r.reset_cycles += bool(d.rst)
            r.resets += bool(d.rst and not prev_rst)
            r.dropped_in_reset += bool(d.rst and d.valid)
            prev_rst = d.rst
        r.outputs = [None] * r.accepted

        for capture in sorted(trace):
            exp = trace[capture]
            valid, data = captured[capture]
            if exp.kind == "out":
                inputs.append(exp.x)
                expected.append(exp.data)
                steps.append(exp.step)
                edge_of.append(capture - LATENCY)
            err = None
            if not valid.is_resolvable:
                err = ("X/Z out_valid", None)
            elif int(valid) != exp.valid:
                err = ("dropped sample" if exp.valid else "unexpected out_valid", None)
            elif exp.data is not None:
                if not data.is_resolvable:
                    err = ("X/Z sample_out", None)
                else:
                    got = data.to_signed()
                    if exp.kind == "out":
                        r.outputs[exp.index] = got
                    if got != exp.data:
                        err = ({"out": "value mismatch", "hold": "sample_out not held",
                                "reset": "sample_out not cleared by reset"}[exp.kind], got)
            if err:
                kind, got = err
                r.errors.append({"kind": kind, "capture": capture, "exp": exp, "got": got, "valid": str(valid),
                                 "data": data.to_signed() if data.is_resolvable else str(data)})

        for s in steps:
            rem = abs(s.acc) % LSB
            r.ties_pos += s.acc > 0 and rem == HALF
            r.ties_neg += s.acc < 0 and rem == HALF
            r.sat_pos += s.rounded > OMAX
            r.sat_neg += s.rounded < OMIN
            r.rail_pos += s.rounded == OMAX
            r.rail_neg += s.rounded == OMIN
            r.max_abs_acc = max(r.max_abs_acc, abs(s.acc))

        if r.errors:
            text = self._format_errors(r, inputs, expected, steps, edge_of)
            self.dut._log.error("%s", text)
            raise AssertionError(text)
        if r.outputs.count(None) or len(r.outputs) != r.accepted:
            raise AssertionError(f"[{self.config}] {name}: only {len(r.outputs) - r.outputs.count(None)} of "
                                 f"{r.accepted} accepted samples were compared")
        return r

    def _format_errors(self, r: Report, inputs, expected, steps, edge_of) -> str:
        kinds: dict[str, int] = {}
        for e in r.errors:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        lines = [f"[{self.config}] {r.name}: {len(r.errors)} wrong cycles out of {r.cycles} "
                 f"({r.accepted} samples accepted, {r.accepted - sum(o is None for o in r.outputs)} RTL outputs "
                 f"collected)",
                 "  by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))]
        for e in r.errors[:MAX_REPORTED]:
            exp: Expect = e["exp"]
            if exp.kind == "out":
                i = exp.index
                got = e["got"]
                error = "n/a" if got is None else f"{got - exp.data:+d}"
                lines.append(f"  sample #{i} (accepted at edge {edge_of[i]}, captured at edge {e['capture']}): "
                             f"{e['kind']}: input={exp.x} expected={exp.data} "
                             f"rtl={got if got is not None else e['data']} out_valid={e['valid']} error={error}")
                s = exp.step
                lines.append(f"      acc={s.acc} rounded={s.rounded}{' (saturated)' if s.saturated else ''}")
                for k in range(max(0, i - CONTEXT), min(len(inputs), i + CONTEXT + 1)):
                    rtl = r.outputs[k]
                    lines.append(f"    {'>' if k == i else ' '} #{k}: input={inputs[k]} expected={expected[k]} "
                                 f"rtl={'?' if rtl is None else rtl}")
            else:
                lines.append(f"  captured edge {e['capture']}: {e['kind']}: expected out_valid={exp.valid} "
                             f"sample_out={exp.data} ({exp.kind}), got out_valid={e['valid']} sample_out={e['data']}")
        if len(r.errors) > MAX_REPORTED:
            lines.append(f"  ... {len(r.errors) - MAX_REPORTED} more")
        return "\n".join(lines)

    def _require(self, r: Report, require: dict[str, int]) -> None:
        holes = [f"{k} {getattr(r, k)} < {v}" for k, v in require.items() if getattr(r, k) < v]
        if holes:
            raise AssertionError(f"[{self.config}] {r.name}: coverage hole, the stimulus did not exercise "
                                 f"what the test claims: {'; '.join(holes)}")
