// =============================================================================
// my_monitor.sv - user example monitor (extends uvm_monitor directly)
// =============================================================================
`ifndef MY_MONITOR_SV
`define MY_MONITOR_SV

class my_monitor extends uvm_monitor;
  `uvm_component_utils(my_monitor)
  function new(string name = "my_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction
endclass

`endif // MY_MONITOR_SV