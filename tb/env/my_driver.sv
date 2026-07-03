// =============================================================================
// my_driver.sv - user example driver (extends uvm_driver directly)
// =============================================================================
`ifndef MY_DRIVER_SV
`define MY_DRIVER_SV

class my_driver extends uvm_driver #(uvm_sequence_item);
  `uvm_component_utils(my_driver)
  function new(string name = "my_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction
endclass

`endif // MY_DRIVER_SV