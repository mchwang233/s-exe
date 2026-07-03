# =============================================================================
# cases/long_run.cmd - runs my_long_test (500ns) + config overrides
#
# Run with `make run CASE=long_run`, expected trace:
#   [MY_LONG_TEST] running 500ns; NUM_AGENTS=4 ENV=long_env
# =============================================================================

# Pick the test class (direct simv: +UVM_TESTNAME=)
simv: +UVM_TESTNAME=my_long_test

# Runtime cfg overrides
ssv_cfg: NUM_AGENTS       = 4
ssv_cfg: ENV_NAME         = "long_env"
ssv_cfg: agent_a.NAME     = "long_agent"
ssv_cfg: agent_b.IS_ACTIVE = 1'b1