# =============================================================================
# cases/override_long.cmd - equivalent to override_demo but uses full hierarchy in paths
# =============================================================================

simv: +UVM_TESTNAME=my_test

ssv_cfg: ssv_root_cfg.ENV_NAME              = "override_demo_env"
ssv_cfg: ssv_root_cfg.agent_a.ADDR_WIDTH    = 64
ssv_cfg: ssv_root_cfg.agent_a.NAME          = "agent_a_overridden"
ssv_cfg: ssv_root_cfg.agent_b.ADDR_WIDTH    = 128
ssv_cfg: ssv_root_cfg.agent_b.DATA_WIDTH    = 256
ssv_cfg: ssv_root_cfg.agent_b.NAME          = "agent_b_overridden"