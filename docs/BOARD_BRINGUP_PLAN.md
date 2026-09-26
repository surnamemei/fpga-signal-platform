# Board bring-up plan (Gate 1)

This plan takes the Gate 0 design to its first physical FPGA board. It is a plan only: no
board-specific file exists in the repository yet, and nothing here changes simulation behaviour.

**Entry condition.** Gate 0 is closed: the `verify` workflow is green on `main` and the run URL is
recorded in [hardware_purchase_gate.md](hardware_purchase_gate.md), which then reads GATE OPEN.

**Exit condition.** Stage 6 passes. The board's output equals the Python golden model sample by sample
for the 10,000 Gate 0 vectors and the directed patterns, and the run's provenance is recorded.

## Ground rules for every stage

1. **The verified FIR does not change.** `rtl/fir_stream.sv` stays byte-identical to its Gate 0
   version (commit `9c523b6`). If a stage seems to need a change to it, stop and revise the contract
   first ([fir_contract.md](fir_contract.md) v2, with matching model tests, as AGENTS.md requires).
   Pipelining to meet timing counts as such a change, because it changes `LATENCY`.
2. **Existing checks keep passing, unchanged.** `make ci` runs 101 pytest tests, 36 of 36 cocotb tests
   over three coefficient builds, Verilator lint and the `ACC_W` guard, 6 of 6 cross-simulator runs, 34
   of 34 mutants and Yosys synthesis. Hardware tests are separate `make` targets that never run in CI,
   because CI has no board.
3. **Board-specific code lives only in the integration layer** (AGENTS.md). Proposed layout, not
   created yet:

   | Path | Contents | Board-specific |
   |---|---|---|
   | `rtl/` | `fir_stream.sv`, unchanged | no |
   | `integration/rtl/` | reset synchronizer, heartbeat, UART, frame receiver and transmitter, buffers, status; parameterized by `CLK_HZ` and `BAUD` and simulated with cocotb like the FIR | no |
   | `boards/<board>/` | top-level wrapper, XDC constraints, Vivado batch build script | yes |
   | `fpga_signal/link.py` | frame format and CRCs in pure Python, used both by the host and as the cocotb reference model | no |
   | `host/` | PC tools using pyserial (new optional extra `board`) | no |

4. **Simulate before building a bitstream.** In every stage the host program first talks to the
   simulated board-independent design through its UART pins in cocotb, then to the board.
5. **Record provenance for every hardware run**: git commit, bitstream SHA-256, board and revision,
   clock, baud rate, tool and host versions, date. Each run writes a new timestamped directory, so
   nothing is overwritten.
6. **Development host.** WSL2 does not see USB devices by default. Either run the Vivado Hardware
   Manager and the host scripts on Windows, attach the board to WSL with usbipd-win, or run
   `hw_server` on Windows and connect Vivado in WSL to it. Both boards use one FTDI USB chip for JTAG
   and UART; on Linux the UART is usually the higher-numbered `/dev/ttyUSB*`.

## Proposed datapath at the end of Stage 5

```text
PC: host/stream.py + fpga_signal.link
        |  one USB cable: JTAG and UART
        v
FPGA:   uart_rx -> frame_rx -+-> echo path ------------+-> frame_tx -> uart_tx -> PC
                             +-> fir_stream (as is) ---+
        status frame: samples in, samples out, CRC-32 of the outputs
        button -> reset_sync -> reset;  host "pipeline reset" command -> fir_stream.rst
        one clock domain: the board oscillator (an MMCM only if timing needs a slower clock)
```

## Stage 1: clock, reset and LED heartbeat

**Objective.** Prove the path from source to a configured FPGA, and that the clock constraint
matches the real oscillator.

**Required hardware.** The board and its micro-USB cable; a PC with Vivado ML Standard, the free
edition, which covers the board's `xc7a35tcpg236-1`.

**RTL changes.** Nothing in `rtl/`.
- `integration/rtl/reset_sync.sv` synchronizes and debounces the push button into the synchronous,
  active-high reset that `fir_stream` expects.
- `integration/rtl/heartbeat.sv` is a counter parameterized by `CLK_HZ` that toggles an LED every 0.5 s.
- `boards/<board>/` holds the top level and the XDC. The XDC sets the clock pin and `create_clock`
  period (83.33 ns on the Cmod A7, 10.00 ns on the Basys 3), the LED and button pins, and
  `CFGBVS VCCO` and `CONFIG_VOLTAGE 3.3`. It also holds a non-project Vivado build script that writes
  the timing and DRC reports next to the bitstream.

**Host-side changes.** None; the bitstream is loaded with the Vivado Hardware Manager.

**Success criterion.**
- The LED blinks 60 times in 60 ± 0.5 s by stopwatch. The wrong clock period makes it 8.3 times too
  fast or too slow, which a stopwatch shows immediately.
- Holding the reset button stops the blinking; releasing it restarts it.
- Vivado reports a clean DRC, no critical warnings, timing met, and no unconstrained clock in
  `check_timing`.

**Likely failure modes.**
- Wrong clock pin or `create_clock` period.
- Wrong part selected. The Cmod A7-15T (`xc7a15t`) looks the same as the 35T.
- A DRC warning about configuration voltage. Digilent's Cmod A7 master XDC omits `CFGBVS` and
  `CONFIG_VOLTAGE`; the Basys 3 master XDC includes them.
- Reset polarity inverted: the design sits in reset and the LED stays dark.
- The Hardware Manager cannot see the board because cable drivers are missing, or because WSL2 has no
  USB passthrough.

**Tests that must still pass.** `make ci`, unchanged. New cocotb tests: the heartbeat period in clock
cycles for both `CLK_HZ` values, and a reset synchronizer that ignores glitches shorter than the
debounce time and releases reset synchronously.

## Stage 2: UART loopback and host communication

**Objective.** A reliable byte link over the board's USB-UART in both directions, at the rate the
later stages use.

**Required hardware.** Same. The UART shares the programming cable on both boards.

**RTL changes.**
- `integration/rtl/uart_rx.sv` and `uart_tx.sv`, parameterized by `CLK_HZ` and `BAUD`. The receiver
  has a two-flip-flop input synchronizer, checks the start bit at mid-bit and flags framing errors.
  Like `fir_stream`'s `ACC_W` check, a parameter guard refuses a baud-divisor error above 2%.
- The board top connects receiver, a small FIFO and transmitter in a loop. An LED lights on a
  framing error.
- Divisors: 1 Mbaud is exactly 12 clocks per bit at 12 MHz and 100 at 100 MHz. For 115,200 baud the
  divisors are 104.17 (0.16% error) and 868.06 (0.006%).

**Host-side changes.** A new optional dependency, `board = ["pyserial"]`. `host/loopback.py --port
--baud --bytes --seed` sends seeded random bytes, compares the echo, prints throughput and error
count, and exits non-zero on any error.

**Success criterion.** 1,000,000 seeded random bytes come back with 0 errors at 115,200 baud and at
1,000,000 baud, three runs in a row. After a reset press in the middle of a transfer, the next run
passes.

**Likely failure modes.**
- TX and RX swapped. The Basys 3 names its UART pins from the FPGA's side (`RsRx` input, `RsTx`
  output); the Cmod A7 names them from the host's side (`uart_txd_in` input, `uart_rxd_out` output).
- The host opens the JTAG channel of the FTDI chip instead of the UART channel.
- A baud divisor computed for the other board's clock.
- A missing input synchronizer, which corrupts bytes only rarely and shows up only in long runs.
- No hardware flow control on either board: both master XDCs expose only TX and RX. The host must
  never have more bytes in flight than the FPGA can buffer.
- Another program, such as a terminal or the Hardware Manager, holding the port.

**Tests that must still pass.** All previous, plus cocotb tests for the UART at the exact
`CLK_HZ`/`BAUD` pairs in use: bit timing, back-to-back bytes, ±2% sender baud error, a bad stop bit,
and a glitch on the start bit. The loopback also runs in simulation, with `host/loopback.py`'s code
driving the receive pin.

## Stage 3: stream known samples from the PC to the FPGA

**Objective.** Move the Gate 0 input vectors to the FPGA as signed 16-bit samples with integrity
checks, and prove the transport is lossless before any arithmetic is involved.

**Required hardware.** Same.

**RTL changes.**
- A frame format defined once, in `fpga_signal/link.py`. Draft: `A5 5A | type | seq (u16) | n (u16,
  1..256) | n x int16 little-endian | CRC-16/CCITT over type..payload`. The protocol is stop-and-wait:
  the FPGA answers each frame with a frame carrying the same `seq` before the host sends the next one.
  That way no buffer can overflow even without flow control.
- `integration/rtl/frame_rx.sv` searches for the sync bytes, checks header and CRC, and emits one
  `valid` pulse per sample. `frame_tx.sv` builds the reply frames.
- A one-frame buffer: 256 x 16 bits fits in one 18 Kb block RAM.
- Commands: mode (echo or FIR), pipeline reset, and status request.
- In this stage the board runs in echo mode.

**Host-side changes.** `fpga_signal/link.py` (pure Python, no pyserial) and `host/stream.py`, which
sends the inputs from `verification/vectors.csv` in frames and checks what comes back.

**Success criterion.**
- All 10,000 Gate 0 inputs come back bit-identical and in order, ten runs in a row. The SHA-256 of
  the returned inputs equals `102c1270...` (`INPUTS_SHA256` in `tests/test_vectors.py`), sequence
  numbers are contiguous, and there are 0 CRC errors.
- Frames the host deliberately corrupts (bad CRC, truncated, garbage between frames) are rejected and
  counted in the status frame, and the link resynchronizes.

**Likely failure modes.**
- Byte order.
- Negative samples: -1 must travel as `FF FF` and come back as -1, not 65535.
- A CRC variant mismatch between host and RTL (initial value, bit reflection).
- A length field off by one.
- Lost synchronization after a corrupted byte.
- Host read timeouts and partial reads.

**Tests that must still pass.** All previous, plus:
- pytest for `link.py`: a published CRC check value, round trip, and corruption detection.
- cocotb tests for `frame_rx` and `frame_tx`, fed with `link.py` frames including corrupted,
  truncated and back-to-back ones.
- The echo path simulated end to end through the UART pins.

## Stage 4: run the existing FIR RTL on streamed samples

**Objective.** The unchanged `fir_stream` processes the streamed samples on the board, with evidence
that its outputs are correct before the full return path exists.

**Required hardware.** Same. Optionally, a second bitstream built with the `stress` taps, because the
production taps can never saturate.

**RTL changes.**
- In FIR mode, the board top places `rtl/fir_stream.sv` between `frame_rx` and `frame_tx`, with the
  default parameters: the production taps, exactly as in CI's `default` build.
- `in_valid` pulses once per received sample.
- `rst` is the board reset OR the host's pipeline-reset command, so every run starts from the model's
  zero history.
- A status frame reports samples accepted, outputs produced, and a CRC-32 of the output samples.
- UART, framing and FIR share one clock domain.
- Clock choice:
  - On the Cmod A7, the native 12 MHz gives the single-cycle FIR an 83.3 ns period.
  - On the Basys 3, if the unpipelined FIR misses 100 MHz, the design runs from a slower
    MMCM-derived clock.
- The stress bitstream uses `synth_design -generic` with the values printed by
  `python -m fpga_signal.rtl_configs`.

**Host-side changes.** `host/stream.py --mode fir` streams the vectors, requests the status frame,
and compares the count and CRC-32 with those of `fir_fixed(inputs)`.

**Success criterion.** Timing is met at the chosen clock with `fir_stream.sv` unmodified. The status
frame reports 10,000 samples accepted, 10,000 outputs produced, and the golden model's CRC-32. The
result is the same after a pipeline reset and a rerun.

**Likely failure modes.**
- Timing failure of the single-cycle multiply-accumulate at 100 MHz (Basys 3).
- History carried across runs because the pipeline reset is missing.
- `in_valid` held for more than one clock per sample (duplicates), or samples lost when switching
  modes.
- `fir_stream` has no ready signal, so the output side must always accept.
- Differences between synthesis and simulation, for example in how Vivado treats the parameter
  guard's `initial` block (it must not fire).

**Tests that must still pass.** All previous, plus a system-level cocotb test of the whole
board-independent design (UART pins -> `frame_rx` -> `fir_stream` -> `frame_tx` -> UART pins). It is
driven by `host/stream.py`'s framing code with the 10,000 vectors and compared against `fir_fixed`, so
the hardware experiment is first run in simulation. `git diff --exit-code 9c523b6 --
rtl/fir_stream.sv` must show no change.

## Stage 5: return processed samples to the PC

**Objective.** Every FIR output reaches the host, in order and traceable to its input.

**Required hardware.** Same.

**RTL changes.** In FIR mode, the reply to request `seq k` carries the outputs for the inputs of frame
`k`. With latency 1, each output is registered one clock after its input, so a frame's outputs are
complete one clock after its last input. The reply buffer holds a full frame.

**Host-side changes.** `host/stream.py` stores inputs, board outputs and the provenance record in a
new timestamped results directory. A retry after a timeout resets the pipeline and restarts, so a
lost reply can never make an input count twice.

**Success criterion.** All 10,000 outputs come back with contiguous sequence numbers and 0 CRC errors.
The CRC-32 of the returned outputs equals the on-board status CRC from Stage 4, and three runs are
byte-identical.

**Likely failure modes.** Outputs assigned to the wrong inputs after a timeout and retry; reply buffer
overflow; echo-mode and FIR-mode frames mixed; partial reads.

**Tests that must still pass.** All previous, plus the system-level simulation extended with a dropped
reply and a retry.

## Stage 6: compare board output with the Python golden model

**Objective.** The board's output equals `fir_fixed` sample by sample: the hardware counterpart of the
Gate 0 regression.

**Required hardware.** Same, plus the stress-taps bitstream if it was built.

**RTL changes.** None. The bitstream is frozen and its SHA-256 recorded.

**Host-side changes.** `host/compare.py` recomputes `fir_fixed` on the recorded inputs, compares
sample by sample, and exits non-zero on any mismatch. Its report matches the cocotb bench's: sample
index, input, expected value, board value, error, neighbouring samples, and tie and saturation
counts. Directed runs mirror the RTL regression: impulses, zeros, full scale, alternating signs, and
±0.5 LSB ties.

**Success criterion.**
- 0 mismatches over the 10,000 Gate 0 vectors. The board's (input, output) pairs reproduce the pinned
  fingerprint `7b8508e6...` (`VECTORS_SHA256` in `tests/test_vectors.py`).
- 0 mismatches on the directed runs, over three runs and after a power cycle.
- If the stress bitstream was built: 0 mismatches, including saturation at both rails.

**Likely failure modes.**
- Transport errors mistaken for arithmetic errors. Rerun the Stage 3 echo to separate the two.
- A mismatch between synthesis and simulation. Localize it with Vivado's functional netlist
  (`write_verilog -mode funcsim`) run under the existing cocotb tests.
- Timing violations.
- Comparing against the wrong taps or stale vectors. Check the provenance record and the vector hash.

**Tests that must still pass.** All previous, plus pytest for `compare.py`. It is fed synthetic board
results containing value errors, dropped samples and duplicated samples, and must fail on each, the
same way `check_results.py` is tested today.

## Board comparison for this repository: Cmod A7-35T or Basys 3

Both boards carry the same FPGA, `xc7a35tcpg236-1`, according to Digilent's Vivado board files for
each. Logic resources, speed grade, package and Vivado device support are therefore identical. The
comparison comes down to what each board adds around the FPGA, measured against what this repository
needs.

### What this repository needs

| Need | Stage | FPGA pins |
|---|---|---|
| System clock | 1 | 1 |
| Reset button | 1 | 1 |
| Status LEDs (heartbeat, errors) | 1-5 | 2-3 |
| USB-UART to the PC: samples, status, later coefficient and configuration control | 2-6 | 2 |
| Pmod I2S2: one 12-pin Pmod with 8 signals. Pins 1-4 carry the DAC's MCLK, LRCK, SCLK and data; pins 7-10 carry the ADC's. | Gate 2 | 8 |

That is about 15 pins, all at 3.3 V. Nothing in the plan uses switches, a numeric display, VGA or
USB HID.

**Resources.** Yosys's `synth_xilinx` mapping of `fir_stream` onto 7-series primitives gives:

| Build | LUT | Inverter | CARRY4 | DSP48E1 | Flip-flop |
|---|---|---|---|---|---|
| production taps | 118 | 34 | 28 | 1 | 81 |
| `stress` taps | 152 | 78 | 43 | 1 | 81 |

Vivado folds the separate inverters into LUTs, and its numbers will differ somewhat. The UART,
framing, buffers and status logic are estimated at a few hundred LUTs and one to four block RAMs. The
XC7A35T has 20,800 LUTs, 90 DSP48E1 slices and 50 block RAMs of 36 Kb (AMD DS180), so the whole design
needs a few percent of the device, and a Vivado ILA for debugging still fits easily. Resources do not
separate the two boards.

### Side by side

| For this repository | Cmod A7-35T | Basys 3 | Better fit |
|---|---|---|---|
| FPGA | `xc7a35tcpg236-1` | `xc7a35tcpg236-1` | equal |
| Board clock | 12 MHz (83.33 ns). The unchanged single-cycle FIR gets 8.3 times the Basys 3's period without any clock generation. | 100 MHz (10 ns). The unpipelined FIR may need a slower MMCM-derived clock; timing has not been run yet. | Cmod A7 |
| I/O requirements | 2 LEDs and 1 RGB LED, 2 buttons, 1 Pmod, UART, 44 DIP I/O pins, 2 analog inputs. Covers every pin above. | 16 LEDs, 16 switches, 5 buttons, 4-digit display, VGA, USB HID, 4 Pmods (JA, JB, JC, JXADC), UART. Covers them with a large surplus the plan does not use. | equal |
| UART | On the programming USB cable; TX and RX only, no RTS/CTS. 1 Mbaud = 12 clocks per bit, exact. | On the programming USB cable; TX and RX only. 1 Mbaud = 100 clocks per bit, exact. | equal: the plan's stop-and-wait framing needs no flow control |
| Future Pmod I2S2 | Takes the only Pmod; anything else, such as logic-analyzer taps, goes through the DIP pins. | Takes one of four Pmods; the rest stay free for probes. | Basys 3 |
| I2S master clock (Gate 2) | 24.576 and 12.288 MHz exactly from one MMCM (768 MHz VCO) | 12.288 MHz exactly; 24.576 MHz within 6.7 ppm | equal: both errors are far below oscillator tolerance |
| Debugging | 3 LEDs and 2 buttons; debugging relies on UART status frames and the Vivado ILA. | LEDs, switches and the display can show counters and select modes without a PC; the ILA works too. | Basys 3 |
| Vivado support | Free edition; Digilent board files and master XDC. The master XDC lacks `CFGBVS` and `CONFIG_VOLTAGE` (two lines to add). | Free edition; board files and a master XDC that includes them. | equal |
| Physical form factor | A 48-pin DIP module that needs a breadboard or socket for mechanical support; compact next to other bench circuits. | A self-contained desktop trainer board; nothing else needed, and sturdier to handle. | equal: the plan needs neither |
| Resource needs | about 1% for the FIR, a few percent in total | the same | equal |
| Cost | the cheaper board (below) | pays for trainer I/O that no stage uses | Cmod A7 |

The master-clock row comes from an exhaustive search over one MMCM's settings, within the -1 speed
grade limits in AMD DS181: input at least 10 MHz, VCO 600-1200 MHz, phase-detector frequency 10-450
MHz, and multiply and CLKOUT0 divide in steps of 1/8. Digilent's Pmod I2S2 demo uses LRCK = MCLK/512
and SCLK = MCLK/8, so 48 kHz audio needs MCLK = 24.576 MHz.

**Cost.** Current prices could not be read automatically, because Digilent's shop and the
distributors refuse automated access. Two snapshots from web search, not verified on the vendor pages:
RS Components Hong Kong listed the Cmod A7-35T at HK$906.30 (about US$116), and Amazon's Basys 3
listing showed a third-party price of US$220 on 29 August 2026. Check the Digilent shop, including
academic pricing, before ordering.

## Recommendation

**The Cmod A7-35T matches this repository's current architecture better.**

- It carries the same FPGA as the Basys 3, so resources and tool support are the same.
- Its clock, LEDs, button, USB-UART and single Pmod cover every pin the plan and the Gate 2 Pmod I2S2
  need. None of the Basys 3's extra I/O is used by any stage.
- Its 12 MHz clock lets Stage 4 run `fir_stream.sv` exactly as verified (latency 1, unpipelined) on
  the native clock. On the Basys 3 the same may need an MMCM-derived clock. On either board, the first
  Vivado timing report decides.
- It costs less, and the README's Gate 1 calls for an inexpensive Artix-7 board.

The trade-offs that come with it:
- Minimal on-board debug I/O; the plan's status frames and the ILA take the place of switches and a
  display.
- A single Pmod: the I2S2 takes it, and probes go on DIP pins.
- A DIP module that needs a breadboard or socket.
- Two lines to add to its XDC.

The Basys 3 is the better choice if any of these apply:
- Standalone debugging without a PC matters more than cost.
- The I2S2 and other Pmods must be connected at the same time.
- The board is shared with a course that uses it.

No board-specific file is added to the repository until a board is chosen and in hand.

## Sources

- Digilent master constraint files, Cmod A7 rev. B and Basys 3 rev. B: clocks, UART pins, LEDs,
  buttons, switches, Pmods, configuration properties. <https://github.com/Digilent/digilent-xdc>
- Digilent Vivado board files `cmod_a7-35t` (B.0) and `basys3` (C.0): part `xc7a35tcpg236-1` for both.
  <https://github.com/Digilent/vivado-boards>
- Digilent Pmod I2S2 demo, including its 12 MHz Cmod S7 variant: pinout, LRCK = MCLK/512, SCLK =
  MCLK/8. <https://github.com/Digilent/Pmod-I2S2>
- AMD DS180 v2.6.1, *7 Series FPGAs Data Sheet: Overview*, Table 4: XC7A35T resources.
- AMD DS181 v1.27.1, *Artix-7 FPGAs Data Sheet: DC and AC Switching Characteristics*: MMCM limits.
- Price snapshots: [RS Components HK](https://hkcn.rs-online.com/web/p/fpga-development-tools/1346483),
  [camelcamelcamel, Basys 3](https://camelcamelcamel.com/product/B00NUE1WOG).
- FIR resource figures: `yowasp-yosys` 0.69 `synth_xilinx -family xc7` on `rtl/fir_stream.sv`,
  26 September 2026.
