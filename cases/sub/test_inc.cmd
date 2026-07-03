# cases/sub/test_inc.cmd - tests the inc: directive
# Shared simv args come from cases/_helpers/common.cmd
# This cmd only contributes ssv_cfg overrides
inc: cases/_helpers/common.cmd

ssv_cfg: NUM_AGENTS = 5
ssv_cfg: agent_a.NAME = "agent_via_inc"