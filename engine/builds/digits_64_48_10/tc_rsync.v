// tc_rsync: reset synchroniser, async assert, sync release (two flops).
// Same behaviour as oh_rsync; swap to oh_rsync when merged into the repo.
module tc_rsync (
  input  clk,                        // clock
  input  nrst_in,                    // async active-low reset
  output nrst_out                    // synchronised active-low reset
);

  reg [1:0] sync;

  always @(posedge clk or negedge nrst_in)
    if (!nrst_in)
      sync[1:0] <= 2'b00;
    else
      sync[1:0] <= {sync[0], 1'b1};

  assign nrst_out = sync[1];

endmodule
