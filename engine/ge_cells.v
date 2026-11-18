// ge_cells: Verilog models of the generic NAND2-equivalent library (ge.lib),
// so the exact netlist that synth_tc.sh measures can be simulated.
// Functions match ge.lib; DFFR clears when R is low.
module BUF   (input A, output Y);                 assign Y = A;              endmodule
module INV   (input A, output Y);                 assign Y = ~A;             endmodule
module NAND2 (input A, input B, output Y);        assign Y = ~(A & B);       endmodule
module NOR2  (input A, input B, output Y);        assign Y = ~(A | B);       endmodule
module AOI21 (input A, input B, input C, output Y); assign Y = ~((A & B) | C); endmodule
module OAI21 (input A, input B, input C, output Y); assign Y = ~((A | B) & C); endmodule
module XOR2  (input A, input B, output Y);        assign Y = A ^ B;          endmodule
module XNOR2 (input A, input B, output Y);        assign Y = ~(A ^ B);       endmodule
module MUX2  (input A, input B, input S, output Y); assign Y = S ? B : A;    endmodule
module DFF   (input C, input D, output reg Q);
  always @(posedge C) Q <= D;
endmodule
module DFFR  (input C, input D, input R, output reg Q);
  always @(posedge C or negedge R)
    if (!R) Q <= 1'b0;
    else    Q <= D;
endmodule
