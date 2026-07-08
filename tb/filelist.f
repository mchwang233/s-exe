// =============================================================================
// filelist.f - vlogan / vcs file list
//
// All paths are absolute (via $UVM_HOME / $PROJ_ROOT) so the file works
// regardless of vcs's cwd -- run_case.py invokes `vcs` with cwd =
// sim/<variant>/ (so the variant cmd's `vcs: -l vcs.log` lands next to
// the simv binary), and vcs resolves +incdir+/source-file entries
// relative to its cwd. Pre-expanding the env vars in the filelist
// avoids that problem.
// =============================================================================

// ---- 1. UVM ----
+incdir+$UVM_HOME/src
$UVM_HOME/src/uvm_pkg.sv

// ---- 2. ssv core (handwritten; the minimal copyable ssv package) ----
+incdir+$PROJ_ROOT/tb/utiles/ssv
$PROJ_ROOT/tb/utiles/ssv/ssv_pkg.sv

// ---- 3. auto-generated cfg object package (depends on ssv_object first) ----
// the pkg lives under cfg/ (paired with .cfg/.sv). +incdir+cfg lets
// `include "lib/X.sv" find child-class sv files in subdirectories.
+incdir+$PROJ_ROOT/cfg
$PROJ_ROOT/cfg/ssv_cfg_pkg.sv

// ---- 4. user env / tests
// Note: multiple test classes (my_test / my_long_test / my_min_test) are
// compiled into the same simv. At runtime, +UVM_TESTNAME=<x> (passed by
// run_case.py) selects which one to run ----
+incdir+$PROJ_ROOT/tb/env
+incdir+$PROJ_ROOT/tb/tests
$PROJ_ROOT/tb/env/my_env_pkg.sv
$PROJ_ROOT/tb/tests/my_test.sv
$PROJ_ROOT/tb/tests/my_long_test.sv
$PROJ_ROOT/tb/tests/my_min_test.sv

// ---- 5. tb top ----
$PROJ_ROOT/tb/tb_top.sv