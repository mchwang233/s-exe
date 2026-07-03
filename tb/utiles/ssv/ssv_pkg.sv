// =============================================================================
// ssv_pkg.sv - Bundles ssv_object into ssv_pkg; users do `import ssv_pkg::*`
// =============================================================================
`ifndef SSV_PKG_SV
`define SSV_PKG_SV

package ssv_pkg;

  `include "uvm_macros.svh"
  import uvm_pkg::*;

  `include "ssv_object.sv"

endpackage

`endif // SSV_PKG_SV
