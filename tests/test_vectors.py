import hashlib

import pytest

from fpga_signal.fir import fir_fixed
from fpga_signal.vectors import (HEADER, INPUT_LIMIT, N_VECTORS, SEED, fingerprint, read_vectors,
                                 regression_inputs, regression_vectors, write_vectors)

# Frozen Gate 0 vector set (seed 5305). If numpy's PCG64 stream, the generator or the golden
# model changes, these fail; regenerate and re-pin only as an explicit, versioned decision.
INPUTS_SHA256 = "102c127095ad3828fe1073cf5a4b50d7e5e779e78ec6da649fa22d2940bc2ccc"
VECTORS_SHA256 = "7b8508e697e4f4e800f506659b0452b5c93f572763e6faddf9def9719e896023"


def test_vector_set_is_frozen():
    rows = regression_vectors()
    assert (SEED, N_VECTORS, len(rows)) == (5305, 10_000, 10_000)
    assert hashlib.sha256("".join(f"{x}\n" for x, _ in rows).encode()).hexdigest() == INPUTS_SHA256
    assert fingerprint(rows) == VECTORS_SHA256


def test_inputs_in_declared_range_and_outputs_from_model():
    x = regression_inputs()
    assert min(x) >= -INPUT_LIMIT and max(x) <= INPUT_LIMIT
    assert [y for _, y in regression_vectors()] == fir_fixed(x)


def test_round_trip(tmp_path):
    rows = regression_vectors(n=50)
    path = write_vectors(rows, tmp_path / "v.csv")
    assert path.read_bytes().startswith(b"sample_in,expected_out\r\n")  # unchanged since v0.1
    assert read_vectors(path) == rows


@pytest.mark.parametrize("content, message", [
    ("", "header"),
    ("sample_in\r\n1\r\n", "header"),
    ("expected_out,sample_in\r\n1,2\r\n", "header"),
    ("sample_in,expected_out,extra\r\n1,2,3\r\n", "header"),
    ("sample_in,expected_out\r\n1\r\n", "expected 2 fields"),
    ("sample_in,expected_out\r\n1,2,3\r\n", "expected 2 fields"),
    ("sample_in,expected_out\r\nnan,2\r\n", "bad.csv:2: non-integer"),
    ("sample_in,expected_out\r\n1.5,2\r\n", "non-integer"),
    ("sample_in,expected_out\r\ninf,2\r\n", "non-integer"),
    ("sample_in,expected_out\r\n,\r\n", "non-integer"),
    ("sample_in,expected_out\r\n40000,2\r\n", "outside the signed 16-bit range"),
])
def test_malformed_vector_files_are_rejected(tmp_path, content, message):
    path = tmp_path / "bad.csv"
    path.write_text(content, newline="")
    with pytest.raises(ValueError, match=message):
        read_vectors(path)


def test_missing_vector_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_vectors(tmp_path / "absent.csv")


def test_header_constant():
    assert HEADER == ["sample_in", "expected_out"]
