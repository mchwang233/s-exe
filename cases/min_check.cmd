# =============================================================================
# cases/min_check.cmd - runs my_min_test, verifies the ssv dispatcher writes
# the hierarchy overrides from cases/<x>.cmd into root_cfg.
#
# Run with `make run CASE=min_check`, expected trace:
#   [MY_MIN_TEST] cfg dump: NUM_AGENTS=3 ENV=min agent_a.NAME=min_a ...
# =============================================================================

# Pick the test class (direct simv: +UVM_TESTNAME=)
simv: +UVM_TESTNAME=my_min_test

ssv_cfg: NUM_AGENTS   = 3
ssv_cfg: ENV_NAME     = "min"
ssv_cfg: agent_a.NAME = "min_a"