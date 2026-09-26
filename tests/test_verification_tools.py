"""Tests of the verification tooling itself: the testbench reference model, the strict
results checker and the mutation catalogue. A bug here could let incorrect RTL pass."""
import random

import pytest

from fpga_signal.fir import DEFAULT_COEFS_Q14, fir_fixed
from tb.fir_protocol import expected_trace, idle, reset, stream, with_bubbles
from verification import check_results, mutation_test


@pytest.fixture(autouse=True)
def no_ci_summary(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def outputs(trace):
    return [e.data for _, e in sorted(trace.items()) if e.kind == "out"]


def test_trace_follows_the_timing_contract():
    rng = random.Random(1)
    prog = reset(1, rng) + stream([16384, 0]) + idle(2, rng) + reset(1, rng, valid=True) + stream([16])
    trace = expected_trace(prog, DEFAULT_COEFS_Q14)
    got = [(cap, e.valid, e.data, e.kind) for cap, e in sorted(trace.items())]
    assert got == [
        (2, 0, 0, "reset"),       # prog[0] reset, sampled at edge 1, captured at edge 2
        (3, 1, 1024, "out"),      # impulse accepted at edge 2, output captured one edge later
        (4, 1, 4096, "out"),
        (5, 0, 4096, "hold"),     # idle: out_valid low, sample_out held
        (6, 0, 4096, "hold"),
        (7, 0, 0, "reset"),       # reset clears sample_out; the offered sample is dropped
        (8, 1, 1, "out"),         # fresh history after reset: 16 * 1024 / 16384 = 1
    ]


def test_trace_matches_golden_model_across_bubbles_and_resets():
    rng = random.Random(2)
    a = [rng.randint(-32768, 32767) for _ in range(300)]
    b = [rng.randint(-32768, 32767) for _ in range(300)]
    prog = reset(2, rng) + with_bubbles(a, rng) + reset(3, rng, valid=True) + with_bubbles(b, rng)
    assert outputs(expected_trace(prog, DEFAULT_COEFS_Q14)) == fir_fixed(a) + fir_fixed(b)


JUNIT = """<testsuites><testsuite name="tb.test_fir_cocotb" tests="{n}">{cases}</testsuite></testsuites>"""


def junit(tmp_path, cases, name="icarus-x"):
    body = "".join(f'<testcase classname="tb.test_fir_cocotb" name="{n}" time="0.1">{extra}</testcase>'
                   for n, extra in cases)
    path = tmp_path / name / "results.xml"
    path.parent.mkdir()
    path.write_text(JUNIT.format(n=len(cases), cases=body))
    return path


def test_checker_finds_every_cocotb_test():
    names = check_results.expected_tests()
    assert "test_gate0_vectors_10000" in names and len(names) == len(set(names)) >= 12


def test_checker_passes_only_complete_green_results(tmp_path):
    names = check_results.expected_tests()
    good = junit(tmp_path, [(n, "") for n in names])
    assert check_results.main([str(good)]) == 0


@pytest.mark.parametrize("mutate", [
    lambda names: [(n, "") for n in names[1:]],                                     # a test did not run
    lambda names: [],                                                               # nothing ran
    lambda names: [(n, "") for n in names] + [(names[0], "")],                      # duplicated
    lambda names: [(n, '<failure message="x"/>') for n in names],                  # 256 failures must not exit 0
    lambda names: [(names[0], '<error message="x"/>')] + [(n, "") for n in names[1:]],
    lambda names: [(names[0], '<skipped message="x"/>')] + [(n, "") for n in names[1:]],
])
def test_checker_rejects_incomplete_or_failing_results(tmp_path, mutate):
    path = junit(tmp_path, mutate(check_results.expected_tests()))
    assert check_results.main([str(path)]) == 1


def test_checker_rejects_missing_and_corrupt_files(tmp_path):
    assert check_results.main([str(tmp_path / "missing.xml")]) == 1
    bad = tmp_path / "bad.xml"
    bad.write_text("<testsuites><testsuite>")
    assert check_results.main([str(bad)]) == 1


@pytest.mark.parametrize("mutant", mutation_test.MUTANTS, ids=lambda m: m.name)
def test_every_mutant_still_applies_to_the_rtl(mutant):
    source = mutation_test.RTL.read_text()
    assert mutation_test.mutate(source, mutant) != source
