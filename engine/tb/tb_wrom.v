// tb_wrom: exhaustive table check of the hardwired-weight block (tc_wrom).
// Reads every w1, w2, threshold and bias entry for all index values
// (including those beyond the model size, which must read as 0) and compares
// them with wrom_exp.hex from wrom_check.py. Ends with PASS/FAIL and a
// non-zero exit code on any mismatch.
`timescale 1ns/1ps
module tb_wrom;
  localparam N = 64 * 64 + 16 * 64 + 64 + 16;

  reg  [5:0]  i;
  reg  [5:0]  j;
  reg  [3:0]  c;
  reg  [3:0]  bc;
  wire [1:0]  w1;
  wire [1:0]  w2;
  wire [29:0] th;
  wire [9:0]  bias;
  reg  [29:0] exp_v [0:N-1];
  integer n;
  integer a;
  integer b;
  integer fails;

  tc_wrom dut (
    .i    (i),
    .j    (j),
    .c    (c),
    .bc   (bc),
    .w1   (w1),
    .w2   (w2),
    .th   (th),
    .bias (bias)
  );

  task chk(input [29:0] got, input [255:0] what);
    begin
      if (got !== exp_v[n]) begin
        fails = fails + 1;
        if (fails < 20)
          $display("FAIL %0s entry %0d got %h exp %h", what, n, got, exp_v[n]);
      end
      n = n + 1;
    end
  endtask

  initial begin
    $readmemh("wrom_exp.hex", exp_v);
    n = 0; fails = 0; i = 0; j = 0; c = 0; bc = 0;
    for (a = 0; a < 64; a = a + 1)
      for (b = 0; b < 64; b = b + 1) begin
        j = a; i = b; #1; chk({28'b0, w1}, "w1");
      end
    for (a = 0; a < 16; a = a + 1)
      for (b = 0; b < 64; b = b + 1) begin
        c = a; j = b; #1; chk({28'b0, w2}, "w2");
      end
    for (a = 0; a < 64; a = a + 1) begin
      j = a; #1; chk(th, "th");
    end
    for (a = 0; a < 16; a = a + 1) begin
      bc = a; #1; chk({20'b0, bias}, "bias");
    end
    $display("SUMMARY checks=%0d failures=%0d", n, fails);
    if (fails == 0) $display("PASS");
    else $fatal(1, "FAIL");
    $finish;
  end

endmodule
