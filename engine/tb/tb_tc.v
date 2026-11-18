// tb_tc: self-checking testbench for tc_engine.
// Replays stream.hex (from mk_tests.py) and compares every checkpoint and
// every class score with the golden model. Ends with PASS/FAIL and a
// non-zero exit code on any failure.
`timescale 1ns/1ps
module tb_tc;
  `include "tb_params.vh"

  reg        clk;
  reg        rst_n;
  reg        cs_n;
  reg        mode;
  reg  [7:0] din;
  wire       busy;
  wire [3:0] result;
  wire [9:0] score;
  wire       score_tgl;

  reg [11:0] words  [0:N_WORDS-1];
  reg  [7:0] exp_r  [0:N_RES-1];
  reg  [9:0] exp_s  [0:N_SCORE-1];

  integer pc;
  integer nres;
  integer nscore;
  integer checks;
  integer fails;
  reg     prev_tgl;
  reg     done;

  tc_engine dut (
    .clk       (clk),
    .rst_n     (rst_n),
    .cs_n      (cs_n),
    .mode      (mode),
    .din       (din),
    .busy      (busy),
    .result    (result),
    .score     (score),
    .score_tgl (score_tgl)
  );

  // 5 MHz clock that the stream can stop and restart (ops 5 and 6), like an
  // ESP32 LCD peripheral that only clocks while it sends bytes
  reg clk_en;
  initial begin clk = 1'b0; clk_en = (POWERUP_NOCLK == 0); end
  always begin
    #100;
    if (clk_en) clk = ~clk;
  end

  // score monitor: every toggle must match the next expected score
  always @(posedge clk) begin
    #1;
    if (rst_n && score_tgl !== prev_tgl) begin
      prev_tgl = score_tgl;
      checks = checks + 1;
      if (nscore >= N_SCORE) begin
        fails = fails + 1;
        $display("FAIL extra score %0d", score);
      end else if (score !== exp_s[nscore]) begin
        fails = fails + 1;
        if (fails < 20)
          $display("FAIL score #%0d got %0d exp %0d", nscore, score,
                   exp_s[nscore]);
      end
      nscore = nscore + 1;
    end
  end

  initial begin
    $readmemh("stream.hex", words);
    $readmemh("exp_res.hex", exp_r);
    $readmemh("exp_score.hex", exp_s);
    pc = 0; nres = 0; nscore = 0; checks = 0; fails = 0; done = 1'b0;
    rst_n = 1'b0; cs_n = 1'b1; mode = 1'b0; din = 8'b0; prev_tgl = 1'b0;
    if (POWERUP_NOCLK != 0) begin
      // power-up reset with NO clock (real host: clock runs only while bytes are
      // sent). The stream must then begin with op 9, which starts the clock.
      #1500; rst_n = 1'b1; #1500;
    end else begin
      repeat (3) @(negedge clk);
      rst_n = 1'b1;
    end
    while (!done) begin
      case (words[pc][11:8])
        4'h0: begin
          @(negedge clk); din = words[pc][7:0]; cs_n = 1'b0;
        end
        4'h1: begin
          @(negedge clk); din = words[pc][7:0]; cs_n = 1'b1;
        end
        4'h2: mode = words[pc][0];
        4'h3: begin
          @(negedge clk); din = 8'b0; cs_n = 1'b0;
          checks = checks + 1;
          if ({3'b0, busy, result} !== exp_r[nres]) begin
            fails = fails + 1;
            if (fails < 20)
              $display("FAIL checkpoint #%0d got busy=%0d result=%0d exp %h",
                       nres, busy, result, exp_r[nres]);
          end
          nres = nres + 1;
        end
        4'h4: begin
          @(negedge clk); rst_n = 1'b0; din = 8'b0; cs_n = 1'b0;
          @(negedge clk); rst_n = 1'b1; prev_tgl = score_tgl;
        end
        4'h5: begin
          // stop after the next falling edge; the first edge after a restart
          // carries an idle byte (a no-op in the golden model)
          @(negedge clk); clk_en = 1'b0; din = 8'b0; cs_n = 1'b0;
        end
        4'h6: clk_en = 1'b1;
        4'h7: begin
          #1000;
          checks = checks + 1;
          if ({3'b0, busy, result} !== exp_r[nres]) begin
            fails = fails + 1;
            if (fails < 20)
              $display("FAIL stopped-clock checkpoint #%0d got busy=%0d result=%0d exp %h",
                       nres, busy, result, exp_r[nres]);
          end
          nres = nres + 1;
        end
        4'h8: begin
          // reset pulse while the clock is stopped; the clock stays stopped
          // (op 9 restarts it). If the clock is running, stop it first.
          if (clk_en) begin @(negedge clk); clk_en = 1'b0; end
          din = 8'b0; cs_n = 1'b0;
          #700; rst_n = 1'b0; #330; rst_n = 1'b1; #900; prev_tgl = score_tgl;
        end
        4'h9: begin
          // real-host restart: byte is on din before the clock starts, so the
          // FIRST clock edge samples this byte (no phantom idle edge as in op 6)
          din = words[pc][7:0]; cs_n = 1'b0; clk_en = 1'b1;
        end
        4'hf: done = 1'b1;
        default: begin
          fails = fails + 1;
          $display("FAIL bad stream word %h at %0d", words[pc], pc);
          done = 1'b1;
        end
      endcase
      pc = pc + 1;
    end
    @(negedge clk);
    checks = checks + 1;
    if (nscore !== N_SCORE || nres !== N_RES) begin
      fails = fails + 1;
      $display("FAIL counts: scores %0d/%0d checkpoints %0d/%0d",
               nscore, N_SCORE, nres, N_RES);
    end
    $display("SUMMARY checks=%0d failures=%0d (scores=%0d checkpoints=%0d)",
             checks, fails, nscore, nres);
    if (fails == 0) $display("PASS");
    else $fatal(1, "FAIL");
    $finish;
  end

endmodule
