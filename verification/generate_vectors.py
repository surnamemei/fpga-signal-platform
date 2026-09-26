from pathlib import Path
import csv
import numpy as np
from fpga_signal.fir import fir_fixed

rng = np.random.default_rng(5305)
N = 10000
x = rng.integers(-20000, 20001, size=N, dtype=np.int64).tolist()
y = fir_fixed(x)
out = Path("verification/vectors.csv")
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["sample_in", "expected_out"])
    w.writerows(zip(x, y))
print(f"wrote {N} vectors to {out}")
