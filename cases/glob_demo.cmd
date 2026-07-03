# =============================================================================
# cases/glob_demo.cmd - uses glob in ssv_cfg: paths with * / ? / [...] for expansion
#   ssv_cfg: agent_*.NAME    = "x"   agent_a.NAME / agent_b.NAME
#   ssv_cfg: *.ADDR_WIDTH    = 9999  agent_a.ADDR_WIDTH / agent_b.ADDR_WIDTH
#   ssv_cfg: agent_a.IS_ACTIVE = 0    exact path (agent_a.IS_ACTIVE)
# =============================================================================

simv: +UVM_TESTNAME=my_test

ssv_cfg: agent_*.NAME      = "glob_overridden"
ssv_cfg: *.ADDR_WIDTH      = 9999
ssv_cfg: agent_a.IS_ACTIVE = 0