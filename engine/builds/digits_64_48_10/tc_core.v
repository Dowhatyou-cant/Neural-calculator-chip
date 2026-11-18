// tc_core: v2 ternary engine (stream + recompute + hybrid weights)
// Byte protocol, formats and arithmetic: see tc_model.py (golden model).
// One din byte per clock; din is registered once, then decoded.
// Assumes rst_n is already synchronised (tc_rsync) and mode_s is
// synchronised (tc_dsync). din and cs_n are driven synchronously to clk.
module tc_core #(
  parameter NI_LAST = 6'd63,         // hardwired inputs - 1
  parameter H_LAST  = 6'd47,         // hardwired hidden - 1
  parameter C_LAST  = 4'd13          // hardwired classes - 1
) (
  input            clk,              // engine clock (from ESP32)
  input            rst_n,            // synchronised active-low reset
  input            cs_n,             // chip select, active low
  input            mode_s,           // synchronised mode pin
  input      [7:0] din,              // byte bus
  input      [1:0] hw_w1,            // hardwired layer-1 weight (j,i)
  input      [1:0] hw_w2,            // hardwired layer-2 weight (c,j)
  input     [29:0] hw_th,            // hardwired thresholds of j
  input      [9:0] hw_bias,          // hardwired bias of class bc
  output     [5:0] idx_i,            // input index for tc_wrom
  output     [5:0] idx_j,            // hidden index for tc_wrom
  output     [3:0] idx_c,            // class index for tc_wrom
  output     [3:0] idx_bc,           // class index for the bias lookup
  output reg       busy,             // run in progress
  output reg [3:0] result,           // argmax class
  output reg [9:0] score,            // score of last finished class
  output reg       score_tgl         // toggles on each score update
);

  // ---------------------------------------------------------------- state
  reg  [7:0] in_q;                   // registered input byte
  reg        mode_r;                 // mode latched at START
  reg  [5:0] i;
  reg  [5:0] j;
  reg  [3:0] c;
  reg  [9:0] acc1;                   // layer-1 sum (signed)
  reg  [9:0] acc2;                   // layer-2 sum (signed)
  reg  [9:0] best;                   // best score so far (signed)
  reg [29:0] th_sr;                  // streamed thresholds
  reg [15:0] cfg_sr;                 // streamed sizes
  reg  [9:0] bias_sr;                // streamed bias

  // ---------------------------------------------------------------- decode
  wire [1:0] typ       = in_q[7:6];
  wire       is_step   = (typ[1:0] == 2'b01);
  wire       is_thr    = (typ[1:0] == 2'b10);
  wire       is_cmd    = (typ[1:0] == 2'b11);
  wire       is_ctl    = is_cmd & (in_q[5:4] == 2'b00);
  wire       is_cfg    = is_cmd & (in_q[5:4] == 2'b01);
  wire       is_bias   = is_cmd & (in_q[5:4] == 2'b10);
  wire       do_start  = is_ctl & (in_q[3:0] == 4'b0001) & ~busy;
  wire       do_abort  = is_ctl & (in_q[3:0] == 4'b0010);
  wire       do_step   = is_step & busy;

  // ---------------------------------------------------------------- sizes
  wire [5:0] ni_last = mode_r ? cfg_sr[15:10] : NI_LAST;
  wire [5:0] h_last  = mode_r ? cfg_sr[9:4]   : H_LAST;
  wire [3:0] c_last  = mode_r ? cfg_sr[3:0]   : C_LAST;
  wire       i_end   = (i[5:0] == ni_last[5:0]);
  wire       j_end   = (j[5:0] == h_last[5:0]);
  wire       c_end   = (c[3:0] == c_last[3:0]);

  // ---------------------------------------------------------------- weights
  wire [1:0]  w1 = mode_r ? in_q[3:2]   : hw_w1[1:0];
  wire [1:0]  w2 = mode_r ? in_q[5:4]   : hw_w2[1:0];
  wire [29:0] th = mode_r ? th_sr[29:0] : hw_th[29:0];

  // bias for the class whose sum starts next: class 0 at START, else c+1
  wire       bmode = do_start ? mode_s : mode_r;
  wire [9:0] bias  = bmode ? bias_sr[9:0] : hw_bias[9:0];

  assign idx_i[5:0]  = i[5:0];
  assign idx_j[5:0]  = j[5:0];
  assign idx_c[3:0]  = c[3:0];
  assign idx_bc[3:0] = do_start ? 4'd0 : c[3:0] + 4'd1;

  // ---------------------------------------------------------------- datapath
  wire [9:0] px = {8'b0, in_q[1:0]};
  wire [9:0] n1 = (w1[1:0] == 2'b01) ? acc1[9:0] + px[9:0] :
                  (w1[1:0] == 2'b11) ? acc1[9:0] - px[9:0] : acc1[9:0];

  wire ge0 = ($signed(n1[9:0]) >= $signed(th[29:20]));
  wire ge1 = ($signed(n1[9:0]) >= $signed(th[19:10]));
  wire ge2 = ($signed(n1[9:0]) >= $signed(th[9:0]));
  wire [1:0] act = {1'b0, ge0} + {1'b0, ge1} + {1'b0, ge2};

  wire [9:0] av = {8'b0, act[1:0]};
  wire [9:0] n2 = (w2[1:0] == 2'b01) ? acc2[9:0] + av[9:0] :
                  (w2[1:0] == 2'b11) ? acc2[9:0] - av[9:0] : acc2[9:0];

  wire better = (c[3:0] == 4'd0) | ($signed(n2[9:0]) > $signed(best[9:0]));

  // ---------------------------------------------------------------- input
  always @(posedge clk or negedge rst_n)
    if (!rst_n)
      in_q[7:0] <= 8'b0;
    else
      in_q[7:0] <= cs_n ? 8'b0 : din[7:0];

  // ---------------------------------------------------------------- loaders
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin
      th_sr[29:0]   <= 30'b0;
      cfg_sr[15:0]  <= 16'b0;
      bias_sr[9:0]  <= 10'b0;
    end else begin
      if (is_thr)  th_sr[29:0]   <= {th_sr[23:0], in_q[5:0]};
      if (is_cfg)  cfg_sr[15:0]  <= {cfg_sr[11:0], in_q[3:0]};
      if (is_bias) bias_sr[9:0]   <= {bias_sr[5:0], in_q[3:0]};
    end

  // ---------------------------------------------------------------- control
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin
      busy        <= 1'b0;
      mode_r      <= 1'b0;
      i[5:0]      <= 6'b0;
      j[5:0]      <= 6'b0;
      c[3:0]      <= 4'b0;
      acc1[9:0]   <= 10'b0;
      acc2[9:0]   <= 10'b0;
      best[9:0]   <= 10'b0;
      result[3:0] <= 4'b0;
      score[9:0]  <= 10'b0;
      score_tgl   <= 1'b0;
    end else if (do_start) begin
      busy        <= 1'b1;
      mode_r      <= mode_s;
      i[5:0]      <= 6'b0;
      j[5:0]      <= 6'b0;
      c[3:0]      <= 4'b0;
      acc1[9:0]   <= 10'b0;
      acc2[9:0]   <= bias[9:0];
      best[9:0]   <= 10'b0;
      result[3:0] <= 4'b0;
    end else if (do_abort) begin
      busy        <= 1'b0;
    end else if (do_step) begin
      if (!i_end) begin
        acc1[9:0] <= n1[9:0];
        i[5:0]    <= i[5:0] + 6'd1;
      end else begin
        acc1[9:0] <= 10'b0;
        i[5:0]    <= 6'b0;
        if (!j_end) begin
          acc2[9:0] <= n2[9:0];
          j[5:0]    <= j[5:0] + 6'd1;
        end else begin
          j[5:0]     <= 6'b0;
          score[9:0] <= n2[9:0];
          score_tgl  <= ~score_tgl;
          if (better) begin
            best[9:0]   <= n2[9:0];
            result[3:0] <= c[3:0];
          end
          if (c_end) begin
            busy      <= 1'b0;
            acc2[9:0] <= 10'b0;
          end else begin
            c[3:0]    <= c[3:0] + 4'd1;
            acc2[9:0] <= bias[9:0];
          end
        end
      end
    end

endmodule
