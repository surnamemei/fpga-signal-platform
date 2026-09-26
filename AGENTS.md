# FPGA Signal Platform agent rules

## Product goal
Build a verified real-time signal-processing path that progresses from a bit-accurate Python golden model to RTL simulation and eventually real FPGA/audio hardware.

## Verification rules
- Python fixed-point behavior is the numerical specification unless explicitly versioned.
- Every RTL arithmetic change must add or update a matching reference-model test.
- Never accept waveform inspection alone as verification; compare sample-by-sample.
- Preserve deterministic seeded vectors.
- Report saturation, rounding and latency explicitly.

## Hardware gate
Do not assume a particular board until Gate 1. Keep the DSP RTL board-independent. Board constraints, clocks, UART and I2S belong in separate integration layers.

## Gate 0 definition
- 10,000 deterministic Python vectors generated.
- Python fixed-point tests pass.
- Cocotb RTL regression harness exists.
- Gate 0 is not fully closed until a supported simulator executes the RTL regression with zero mismatches.
