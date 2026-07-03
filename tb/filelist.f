// =============================================================================
// filelist.f - vlogan / vcs file list
// =============================================================================

// ---- 1. UVM ----
+incdir+$UVM_HOME/src
$UVM_HOME/src/uvm_pkg.sv

// ---- 2. ssv core (handwritten; the minimal copyable ssv package) ----
+incdir+tb/utiles/ssv
tb/utiles/ssv/ssv_pkg.sv

// ---- 3. auto-generated cfg object package (depends on ssv_object first) ----
// the pkg lives under cfg/ (paired with .cfg/.sv). +incdir+cfg lets
// `include "lib/X.sv" find child-class sv files in subdirectories.
+incdir+cfg
cfg/ssv_cfg_pkg.sv

// ---- 4. user env / tests
// Note: multiple test classes (my_test / my_long_test / my_min_test) are
// compiled into the same simv. At runtime, +UVM_TESTNAME=<x> (passed by
// run_case.py) selects which one to run ----
+incdir+tb/env
+incdir+tb/tests
tb/env/my_env_pkg.sv
tb/tests/my_test.sv
tb/tests/my_long_test.sv
tb/tests/my_min_test.sv

// ---- 5. tb top ----
tb/tb_top.sv