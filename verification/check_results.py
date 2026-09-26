"""Strict check of cocotb JUnit results files. Exit status 0 only if every expected test passed.

cocotb's built-in `make` check is weaker: it passes when zero tests ran, ignores skipped
tests, and uses the failure count as the exit status (so 256 failures would exit 0). Here
every @cocotb.test in tb/test_fir_cocotb.py must appear exactly once in each results file,
with no failure, error or skip.

    python verification/check_results.py sim_build/icarus-default/results.xml [...]
"""
from __future__ import annotations

import argparse
import ast
import os
import platform
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
TEST_MODULE = ROOT / "tb" / "test_fir_cocotb.py"


def expected_tests(path: Path = TEST_MODULE) -> list[str]:
    """Names of the functions decorated with @cocotb.test in ``path``."""
    names = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if ast.unparse(dec.func if isinstance(dec, ast.Call) else dec) == "cocotb.test":
                    names.append(node.name)
    return names


def check_file(path: Path, expected: list[str]) -> tuple[list[str], dict]:
    """Return (problems, summary) for one results file."""
    summary = {"build": path.parent.name, "tests": 0, "passed": 0, "sim_ns": 0.0, "real_s": 0.0}
    if not path.is_file():
        return [f"{path}: missing; the simulation did not run or crashed before writing results"], summary
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        return [f"{path}: unreadable JUnit XML ({exc})"], summary
    problems = []
    seen: dict[str, int] = {}
    for case in root.iter("testcase"):
        name = case.get("name", "?")
        seen[name] = seen.get(name, 0) + 1
        summary["tests"] += 1
        props = {prop.get("name"): prop.get("value") for prop in case.iter("property")}
        if props.get("sim_time_unit") == "ns":
            summary["sim_ns"] += float(props.get("sim_time_duration") or 0)
        summary["real_s"] += float(case.get("time", 0) or 0)
        bad = [el for el in case if el.tag in ("failure", "error", "skipped")]
        if bad:
            message = (bad[0].get("message") or bad[0].text or "").strip().splitlines()
            problems.append(f"{summary['build']}: {name}: {bad[0].tag.upper()}"
                            + (f": {message[0][:300]}" if message else ""))
        else:
            summary["passed"] += 1
    for name in expected:
        if name not in seen:
            problems.append(f"{summary['build']}: {name}: did not run")
    for name, count in seen.items():
        if count > 1:
            problems.append(f"{summary['build']}: {name}: ran {count} times")
        if name not in expected:
            problems.append(f"{summary['build']}: {name}: not a @cocotb.test in {TEST_MODULE.name}")
    return problems, summary


def provenance() -> list[str]:
    """What produced these results: source revision, tools and the vector set."""
    def first_line(cmd):
        try:
            out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
            return (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 else "unknown"
        except (OSError, IndexError, subprocess.SubprocessError):
            return "unknown"

    commit = first_line(["git", "rev-parse", "--short=12", "HEAD"])
    dirty = first_line(["git", "status", "--porcelain", "--untracked-files=no"]) not in ("unknown", "")
    try:
        from importlib.metadata import version
        packages = f"cocotb {version('cocotb')}, numpy {version('numpy')}"
    except Exception:  # noqa: BLE001 - provenance must never hide the verdict
        packages = "unknown"
    try:
        from fpga_signal.vectors import fingerprint, read_vectors
        vectors = f"sha256 {fingerprint(read_vectors())[:16]}..."
    except Exception:  # noqa: BLE001
        vectors = "unreadable"
    return [f"source {commit}{' (uncommitted changes)' if dirty else ''}",
            f"simulator {first_line(['iverilog', '-V'])}",
            f"python {platform.python_version()}, {packages}",
            f"vectors {vectors}"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", nargs="+", type=Path, help="cocotb results.xml files, one per build")
    args = parser.parse_args(argv)

    expected = expected_tests()
    if not expected:
        print(f"error: no @cocotb.test functions found in {TEST_MODULE}", file=sys.stderr)
        return 1
    problems, rows = [], []
    for path in args.results:
        p, s = check_file(path, expected)
        problems += p
        rows.append(s)

    verdict = "PASS" if not problems else "FAIL"
    lines = [f"RTL regression: {verdict} ({len(expected)} tests expected per build)",
             f"  {'build':<24}{'tests':>6}{'passed':>8}{'sim time':>14}{'wall':>9}"]
    lines += [f"  {r['build']:<24}{r['tests']:>6}{r['passed']:>8}{r['sim_ns'] / 1e3:>12.1f}us{r['real_s']:>8.1f}s"
              for r in rows]
    lines += [f"  FAIL {p}" for p in problems]
    origin = provenance()
    lines += [f"  {item}" for item in origin]
    print("\n".join(lines))

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        md = [f"### RTL regression: {verdict}", "", "| build | tests | passed |", "|---|---:|---:|"]
        md += [f"| {r['build']} | {r['tests']} | {r['passed']} |" for r in rows]
        md += [""] + [f"- :x: `{p}`" for p in problems] + [""] + [f"- {item}" for item in origin]
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
