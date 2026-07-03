// =============================================================================
// my_env.sv - user example env
// =============================================================================
`ifndef MY_ENV_SV
`define MY_ENV_SV

class my_env extends uvm_env;

  `uvm_component_utils(my_env)

  ssv_object  root_cfg;
  ssv_root_cfg my_root;
  my_agent     agents[];

  function new(string name = "my_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);

    if (!uvm_config_db#(ssv_object)::get(null, get_full_name(), "cfg", root_cfg))
      `uvm_warning("MY_ENV", $sformatf("%s: no root_cfg", get_name()))
    if (!$cast(my_root, root_cfg)) begin
      `uvm_warning("MY_ENV", "root_cfg is not ssv_root_cfg; using bare ssv_object")
      return;
    end

    `uvm_info("MY_ENV",
      $sformatf("build: NUM_AGENTS=%0d ENV_NAME=%s CLK_PERIOD_NS=%0f",
                my_root.NUM_AGENTS, my_root.ENV_NAME, my_root.CLK_PERIOD_NS),
      UVM_LOW)

    agents = new[my_root.NUM_AGENTS];
    foreach (agents[i]) begin
      string n;
      n = $sformatf("agent_%0d", i);
      agents[i] = my_agent::type_id::create(n, this);
      case (i)
        0: uvm_config_db#(sub_agent_cfg)::set(null, agents[i].get_full_name(), "cfg", my_root.agent_a);
        1: uvm_config_db#(sub_agent_cfg)::set(null, agents[i].get_full_name(), "cfg", my_root.agent_b);
        default: `uvm_warning("MY_ENV", $sformatf("no pre-defined cfg for agent[%0d]", i))
      endcase
    end
  endfunction

endclass

`endif // MY_ENV_SV