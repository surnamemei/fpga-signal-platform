// fir_stream: 5-tap streaming FIR, bit-exact with fpga_signal.fir.fir_fixed (contract v1,
// docs/fir_contract.md). Board-independent: clocks, I/O, UART and I2S belong elsewhere.
//
// Arithmetic
//   acc = C0*x[n] + C1*x[n-1] + C2*x[n-2] + C3*x[n-3] + C4*x[n-4]   exact, ACC_W-bit signed
//   y   = saturate_SAMPLE_W( round_half_away_from_zero(acc / 2**COEF_FRAC) )
//
// Timing (LATENCY = 1)
//   * A sample is accepted on a rising clk edge with rst == 0 and in_valid == 1.
//   * Its result is registered on that same edge, so out_valid == 1 and sample_out == y
//     during the following clock cycle.
//   * An edge with in_valid == 0 leaves the delay line unchanged, gives out_valid == 0
//     for the following cycle and holds sample_out.
//   * rst is synchronous, active high and has priority over in_valid: it clears the
//     delay line, out_valid and sample_out, and a sample presented with rst == 1 is dropped.
`timescale 1ns / 1ps

module fir_stream #(
    parameter int SAMPLE_W = 16,
    parameter int COEF_W = 16,
    parameter int COEF_FRAC = 14,
    parameter int ACC_W = 40,
    parameter signed [COEF_W-1:0] C0 = 16'sd1024,
    parameter signed [COEF_W-1:0] C1 = 16'sd4096,
    parameter signed [COEF_W-1:0] C2 = 16'sd6144,
    parameter signed [COEF_W-1:0] C3 = 16'sd4096,
    parameter signed [COEF_W-1:0] C4 = 16'sd1024
) (
    input  logic clk,
    input  logic rst,
    input  logic in_valid,
    input  logic signed [SAMPLE_W-1:0] sample_in,
    output logic out_valid,
    output logic signed [SAMPLE_W-1:0] sample_out
);
    localparam int NTAPS = 5;
    /* verilator lint_off UNUSEDPARAM */
    localparam int LATENCY = 1;  // read by the testbench and checked against the golden model
    /* verilator lint_on UNUSEDPARAM */

    // Constants are ACC_W bits wide so no expression below is evaluated in 32-bit integer context.
    localparam signed [ACC_W-1:0] ONE = 1;
    localparam signed [ACC_W-1:0] HALF_LSB = ONE <<< (COEF_FRAC - 1);
    localparam signed [ACC_W-1:0] MAX_OUT = (ONE <<< (SAMPLE_W - 1)) - ONE;
    localparam signed [ACC_W-1:0] MIN_OUT = -(ONE <<< (SAMPLE_W - 1));

    // x[n-1] .. x[n-4]; x[n] is sample_in itself.
    logic signed [SAMPLE_W-1:0] d0, d1, d2, d3;
    logic signed [ACC_W-1:0] acc;
    logic signed [ACC_W-1:0] shifted;
    logic signed [ACC_W-1:0] abs_acc;

    always_comb begin
        // All operands are signed and the context is ACC_W bits, so every product is
        // sign-extended and computed exactly; ACC_W >= SAMPLE_W + COEF_W + clog2(NTAPS).
        acc = $signed(sample_in) * $signed(C0)
            + $signed(d0) * $signed(C1)
            + $signed(d1) * $signed(C2)
            + $signed(d2) * $signed(C3)
            + $signed(d3) * $signed(C4);
        // Round half away from zero, symmetric for negative values (fixed.round_shift).
        if (acc >= 0) begin
            abs_acc = acc;
            shifted = (abs_acc + HALF_LSB) >>> COEF_FRAC;
        end else begin
            abs_acc = -acc;
            shifted = -((abs_acc + HALF_LSB) >>> COEF_FRAC);
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            d0 <= '0; d1 <= '0; d2 <= '0; d3 <= '0;
            sample_out <= '0;
            out_valid <= 1'b0;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                d3 <= d2; d2 <= d1; d1 <= d0; d0 <= sample_in;
                if (shifted > MAX_OUT)
                    sample_out <= MAX_OUT[SAMPLE_W-1:0];
                else if (shifted < MIN_OUT)
                    sample_out <= MIN_OUT[SAMPLE_W-1:0];
                else
                    sample_out <= shifted[SAMPLE_W-1:0];
            end
        end
    end

    // Parameter contract. An initial block rather than an elaboration-time generate
    // $error, because Icarus Verilog 12 silently ignores the latter.
    initial begin
        if (ACC_W < SAMPLE_W + COEF_W + $clog2(NTAPS))
            $fatal(1, "fir_stream: ACC_W=%0d is below the guaranteed-safe width SAMPLE_W+COEF_W+clog2(NTAPS)=%0d",
                   ACC_W, SAMPLE_W + COEF_W + $clog2(NTAPS));
        if (COEF_FRAC < 1 || COEF_FRAC > ACC_W - 2)
            $fatal(1, "fir_stream: COEF_FRAC=%0d outside [1, ACC_W-2]", COEF_FRAC);
    end
endmodule
