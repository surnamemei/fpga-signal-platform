// Self-checking SystemVerilog testbench for fir_stream: a second harness, independent of
// cocotb, used to cross-check the RTL on Icarus Verilog and Verilator (make xsim).
//
// +vectors=<file> holds one line per clock cycle, written by verification/xsim.py:
//     rst in_valid sample_in expected_out_valid expected_sample_out
// Inputs are applied half a period before the rising edge that samples them; outputs are
// compared half a period after it, every cycle, including idle and reset cycles.
`timescale 1ns / 1ps

module fir_stream_tb #(
    parameter bit OVERRIDE = 1'b0,  // 0: use the defaults written in fir_stream.sv
    parameter signed [15:0] C0 = 16'sd0,
    parameter signed [15:0] C1 = 16'sd0,
    parameter signed [15:0] C2 = 16'sd0,
    parameter signed [15:0] C3 = 16'sd0,
    parameter signed [15:0] C4 = 16'sd0
);
    logic clk = 1'b0;
    logic rst = 1'b1;
    logic in_valid = 1'b0;
    logic signed [15:0] sample_in = '0;
    logic out_valid;
    logic signed [15:0] sample_out;

    if (OVERRIDE) begin : g_override
        fir_stream #(.C0(C0), .C1(C1), .C2(C2), .C3(C3), .C4(C4)) dut (.*);
    end else begin : g_source_defaults
        fir_stream dut (.*);
    end

    initial forever #5 clk = ~clk;

    initial begin
        string path;
        int fd, cycles, errors, outputs;
        int r, v, x, ev, ex;
        if (!$value$plusargs("vectors=%s", path)) $fatal(1, "usage: +vectors=<file>");
        fd = $fopen(path, "r");
        if (fd == 0) $fatal(1, "cannot open %s", path);
        cycles = 0;
        errors = 0;
        outputs = 0;
        while ($fscanf(fd, "%d %d %d %d %d\n", r, v, x, ev, ex) == 5) begin
            rst = r[0];
            in_valid = v[0];
            sample_in = x[15:0];
            @(posedge clk);
            @(negedge clk);
            cycles++;
            outputs += int'(out_valid === 1'b1);
            if (out_valid !== ev[0] || sample_out !== ex[15:0]) begin
                errors++;
                if (errors <= 10)
                    $display("MISMATCH cycle %0d: in rst=%0d valid=%0d sample=%0d | expected out_valid=%0d sample_out=%0d | rtl out_valid=%b sample_out=%0d",
                             cycles, r, v, x, ev, ex, out_valid, sample_out);
            end
        end
        $fclose(fd);
        if (cycles == 0) $fatal(1, "no vectors read from %s", path);
        if (errors != 0) $fatal(1, "FAIL: %0d of %0d cycles mismatched", errors, cycles);
        $display("PASS: %0d cycles, %0d outputs, 0 mismatches", cycles, outputs);
        $finish;
    end
endmodule
