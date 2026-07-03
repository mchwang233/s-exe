// =============================================================================
// tb_top.sv - testbench top module
//
// - clock / reset placeholders
// - users instantiate their own virtual interface in an initial block and
//   attach it to env via uvm_config_db
// - run_test() selects the test via +UVM_TESTNAME
// =============================================================================
`ifndef TB_TOP_SV
`define TB_TOP_SV

import uvm_pkg::*;
`include "uvm_macros.svh"

module tb_top;

  // clock and reset: placeholders
  logic clk = 0;
  logic rst_n = 1;

  always #5ns clk = ~clk;

  initial begin
    rst_n = 0;
    #20ns;
    rst_n = 1;
  end

  // ============================================================
  // Instantiate your own virtual interface here (no longer provided by ssv):
  //
  //   my_iface vif ();
  //   initial uvm_config_db#(virtual my_iface)::set(
  //       null, "uvm_test_top.env.*", "vif", vif);
  // ============================================================

  initial begin
    `uvm_info("TB_TOP", "starting UVM test via run_test()", UVM_LOW)
  end

  initial begin
    run_test();
  end

endmodule

`endif // TB_TOP_SV