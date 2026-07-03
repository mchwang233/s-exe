# =============================================================================
# cases/override_demo.cmd - 6 ssv_cfg: overrides (exact paths)
#
# Run with `make run CASE=override_demo`.
# Expected: my_test runs with NUM_AGENTS=2 / ENV_NAME=override_demo_env / agent_* field overrides
# =============================================================================

simv: +UVM_TESTNAME=my_test

ssv_cfg: ENV_NAME           = "override_demo_env"
ssv_cfg: agent_a.ADDR_WIDTH  = 64
ssv_cfg: agent_a.NAME        = "agent_a_overridden"
ssv_cfg: agent_b.ADDR_WIDTH  = 128
ssv_cfg: agent_b.DATA_WIDTH  = 256
ssv_cfg: agent_b.NAME        = "agent_b_overridden"