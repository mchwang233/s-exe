// =============================================================================
// my_env_pkg.sv - user example env package
//
// Demonstrates:
//   - importing ssv_pkg + ssv_cfg_pkg (auto-generated cfg objects)
//   - subclassing ssv_agent to get direct field access to the concrete cfg type
//   - subclassing ssv_env to inject root_cfg sub-objects into agents
//
// One class per file inside the package (monitor/driver/agent/env), stitched
// together with `include. The filelist does NOT list these individually —
// see "Don't double-list packaged .sv files" in MEMORY.
// =============================================================================
`ifndef MY_ENV_PKG_SV
`define MY_ENV_PKG_SV

package my_env_pkg;

  `include "uvm_macros.svh"
  import uvm_pkg::*;
  import ssv_pkg::*;
  import ssv_cfg_pkg::*;

  `include "my_monitor.sv"
  `include "my_driver.sv"
  `include "my_agent.sv"
  `include "my_env.sv"

endpackage

`endif // MY_ENV_PKG_SV