# =============================================================================
# cases/hooks_fail_demo.cmd - verifies abort behavior on hook failure
#   - presim uses `false` to make it fail
#   - Expected: simv is never invoked (no sim.log produced)
# =============================================================================

simv: +UVM_TESTNAME=my_test

presim: echo "[presim] about to fail..."; false