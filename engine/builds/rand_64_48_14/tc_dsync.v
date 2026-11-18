// tc_dsync: two-flop synchroniser for a slow single-bit input.
// Same behaviour as oh_dsync; swap to oh_dsync when merged into the repo.
module tc_dsync (
  input  clk,                        // clock
  input  nrst,                       // synchronised active-low reset
  input  din,                        // asynchronous input
  output dout                        // synchronised output
);

  reg [1:0] sync;

  always @(posedge clk or negedge nrst)
    if (!nrst)
      sync[1:0] <= 2'b00;
    else
      sync[1:0] <= {sync[0], din};

  assign dout = sync[1];

endmodule
