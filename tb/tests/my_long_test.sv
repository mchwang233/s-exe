// =============================================================================
// my_long_test.sv - a longer-running smoke: 500ns instead of 100ns.
//
// Shares the cfg entry point with my_test: in build_phase it calls
// ssv_object::apply_overrides_in_cwd(root_cfg), which opens the relative
// path "cfg.info" (relies on cwd = case run dir).
// =============================================================================
`ifndef MY_LONG_TEST_SV
`define MY_LONG_TEST_SV

package my_long_test_pkg;

  `include "uvm_macros.svh"
  import uvm_pkg::*;
  import ssv_pkg::*;
  import ssv_cfg_pkg::*;

  class my_long_test extends uvm_test;

    `uvm_component_utils(my_long_test)

    ssv_object    root_cfg;
    ssv_root_cfg  my_root;

    function new(string name = "my_long_test", uvm_component parent = null);
      super.new(name, parent);
    endfunction

    virtual function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      root_cfg = ssv_root_cfg::type_id::create("ssv_root_cfg");
      void'($cast(my_root, root_cfg));

      ssv_object::apply_overrides_in_cwd(root_cfg);

      uvm_config_db#(ssv_object)::set(null, "uvm_test_top.env", "cfg", root_cfg);
    endfunction

    virtual task main_phase(uvm_phase phase);
      phase.raise_objection(this);
      `uvm_info("MY_LONG_TEST",
        $sformatf("running 500ns; NUM_AGENTS=%0d ENV=%s",
                  my_root.NUM_AGENTS, my_root.ENV_NAME), UVM_LOW)
      #500ns;
      phase.drop_objection(this);
    endtask

  endclass

endpackage

`endif // MY_LONG_TEST_SV