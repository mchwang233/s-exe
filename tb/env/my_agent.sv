// =============================================================================
// my_agent.sv - user example agent (extends uvm_agent directly)
//
// typedef my_sequencer lives right next to my_agent — typedef is not a class,
// so it stays in the same file as the class that uses it.
// =============================================================================
`ifndef MY_AGENT_SV
`define MY_AGENT_SV

typedef uvm_sequencer #(uvm_sequence_item) my_sequencer;

class my_agent extends uvm_agent;

  `uvm_component_utils(my_agent)

  sub_agent_cfg cfg;
  my_monitor    mon;
  my_sequencer  sqr;
  my_driver     drv;

  function new(string name = "my_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(sub_agent_cfg)::get(null, get_full_name(), "cfg", cfg))
      `uvm_info("MY_AGENT", $sformatf("%s: no sub_agent_cfg in cfg_db", get_name()), UVM_LOW)

    mon = my_monitor::type_id::create("mon", this);
    if (cfg != null && cfg.IS_ACTIVE) begin
      sqr = my_sequencer::type_id::create("sqr", this);
      drv = my_driver   ::type_id::create("drv", this);
    end

    if (cfg != null)
      `uvm_info("MY_AGENT",
        $sformatf("%s: AGENT_ID=%0d ADDR_WIDTH=%0d IS_ACTIVE=%0d NAME=%s",
                  get_name(), cfg.AGENT_ID, cfg.ADDR_WIDTH, cfg.IS_ACTIVE, cfg.NAME),
        UVM_LOW)
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (sqr != null && drv != null)
      drv.seq_item_port.connect(sqr.seq_item_export);
  endfunction

endclass

`endif // MY_AGENT_SV