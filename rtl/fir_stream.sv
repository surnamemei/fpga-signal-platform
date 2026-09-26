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
    logic signed [SAMPLE_W-1:0] d0, d1, d2, d3, d4;
    logic signed [ACC_W-1:0] acc;
    logic signed [ACC_W-1:0] shifted;
    logic signed [ACC_W-1:0] abs_acc;
    localparam signed [ACC_W-1:0] MAX_OUT = (1 <<< (SAMPLE_W-1)) - 1;
    localparam signed [ACC_W-1:0] MIN_OUT = -(1 <<< (SAMPLE_W-1));

    always_comb begin
        acc = $signed(sample_in) * $signed(C0)
            + $signed(d0) * $signed(C1)
            + $signed(d1) * $signed(C2)
            + $signed(d2) * $signed(C3)
            + $signed(d3) * $signed(C4);
        if (acc >= 0) begin
            abs_acc = acc;
            shifted = (abs_acc + (1 <<< (COEF_FRAC-1))) >>> COEF_FRAC;
        end else begin
            abs_acc = -acc;
            shifted = -((abs_acc + (1 <<< (COEF_FRAC-1))) >>> COEF_FRAC);
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            d0 <= '0; d1 <= '0; d2 <= '0; d3 <= '0; d4 <= '0;
            sample_out <= '0;
            out_valid <= 1'b0;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                d4 <= d3; d3 <= d2; d2 <= d1; d1 <= d0; d0 <= sample_in;
                if (shifted > MAX_OUT)
                    sample_out <= MAX_OUT[SAMPLE_W-1:0];
                else if (shifted < MIN_OUT)
                    sample_out <= MIN_OUT[SAMPLE_W-1:0];
                else
                    sample_out <= shifted[SAMPLE_W-1:0];
            end
        end
    end
endmodule
