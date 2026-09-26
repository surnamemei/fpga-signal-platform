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
The purchase gate is open for the first FPGA development board only (docs/hardware_purchase_gate.md). Instruments, Pmods, custom PCBs and larger boards each need their own gate decision.

## Frozen contract
FIR contract v1 (docs/fir_contract.md) is frozen at Gate 0 (commit 9c523b6). Do not modify `rtl/fir_stream.sv` unless the change introduces a new contract version with matching reference-model tests.

## Gate 0 definition
- 10,000 deterministic Python vectors generated.
- Python fixed-point tests pass.
- Cocotb RTL regression harness exists.
- Gate 0 is not fully closed until a supported simulator executes the RTL regression with zero mismatches.
