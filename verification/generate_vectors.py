"""Write the deterministic Gate 0 vectors (seed 5305, 10,000 samples) as CSV.

The file is fully determined by the seed and the golden model, so rewriting it is
always safe: every run produces identical bytes (fingerprint pinned in tests/test_vectors.py).
"""
import argparse
from pathlib import Path

from fpga_signal.fir import DEFAULT_COEFS_Q14, fir_fixed_steps
from fpga_signal.vectors import DEFAULT_PATH, N_VECTORS, SEED, fingerprint, regression_inputs, write_vectors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_PATH,
                        help="CSV to write (default: verification/vectors.csv)")
    args = parser.parse_args(argv)

    x = regression_inputs()
    steps = fir_fixed_steps(x, DEFAULT_COEFS_Q14)
    rows = list(zip(x, (s.out for s in steps)))
    out = write_vectors(rows, args.output)

    ties_pos = sum(1 for s in steps if s.acc > 0 and s.acc % (1 << 14) == 1 << 13)
    ties_neg = sum(1 for s in steps if s.acc < 0 and (-s.acc) % (1 << 14) == 1 << 13)
    saturated = sum(1 for s in steps if s.saturated)
    print(f"wrote {N_VECTORS} vectors to {out} (seed {SEED})")
    print(f"  inputs  [{min(x)}, {max(x)}]  outputs [{min(r[1] for r in rows)}, {max(r[1] for r in rows)}]")
    print(f"  exact +0.5 LSB ties {ties_pos}, exact -0.5 LSB ties {ties_neg}, saturated outputs {saturated}")
    print(f"  sha256 {fingerprint(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
