"""Deterministic Gate 0 regression vectors.

The vector set is frozen: seed 5305, 10,000 inputs drawn uniformly from
[-20000, 20000] with numpy's PCG64 ``default_rng``, and outputs from the golden
model with the default taps. ``tests/test_vectors.py`` pins a SHA-256
fingerprint of the set, so a change in numpy's stream, the generator or the
model shows up as a test failure instead of a silently different regression.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np

from .fir import DEFAULT_COEFS_Q14, SAMPLE_W, fir_fixed
from .fixed import signed_range

SEED = 5305
N_VECTORS = 10_000
INPUT_LIMIT = 20_000
HEADER = ["sample_in", "expected_out"]
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "verification" / "vectors.csv"


def regression_inputs(seed=SEED, n=N_VECTORS, limit=INPUT_LIMIT) -> list[int]:
    rng = np.random.default_rng(seed)
    return rng.integers(-limit, limit + 1, size=n, dtype=np.int64).tolist()


def regression_vectors(seed=SEED, n=N_VECTORS, coefs=DEFAULT_COEFS_Q14) -> list[tuple[int, int]]:
    x = regression_inputs(seed, n)
    return list(zip(x, fir_fixed(x, coefs)))


def fingerprint(rows) -> str:
    """SHA-256 of the vector values (independent of CSV line endings)."""
    return hashlib.sha256("".join(f"{x},{y}\n" for x, y in rows).encode()).hexdigest()


def write_vectors(rows, path=DEFAULT_PATH) -> Path:
    path = Path(path)
    _check_rows(rows, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return path


def read_vectors(path=DEFAULT_PATH) -> list[tuple[int, int]]:
    """Read and validate a vectors CSV: exact header, integer fields, 16-bit range."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != HEADER:
            raise ValueError(f"{path}: header {header!r}, expected {HEADER!r}")
        rows = []
        for line_no, fields in enumerate(reader, start=2):
            if len(fields) != 2:
                raise ValueError(f"{path}:{line_no}: expected 2 fields, got {fields!r}")
            try:
                rows.append((int(fields[0]), int(fields[1])))
            except ValueError:
                raise ValueError(f"{path}:{line_no}: non-integer field in {fields!r}") from None
    _check_rows(rows, path)
    return rows


def _check_rows(rows, path) -> None:
    lo, hi = signed_range(SAMPLE_W)
    for i, (x, y) in enumerate(rows):
        if not (lo <= x <= hi and lo <= y <= hi):
            raise ValueError(f"{path}: row {i} ({x}, {y}) outside the signed {SAMPLE_W}-bit range")
