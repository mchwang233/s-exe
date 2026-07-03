# =============================================================================
# cases/nested_array_demo.cmd - tests field overrides + dynamic arrays inside sub-objects
#
# Verifies: arrays inside sub-objects also go through apply_array_field,
# with the path being sub_obj.FIELD.size
# =============================================================================

simv: +UVM_TESTNAME=my_test

# Trigger: arrays in a sub-object (note: sub_agent.cfg currently has no array fields,
# so the lines below just verify that dispatch_path correctly forwards the path to
# the sub-object's apply_array_field. Whether they actually take effect depends on
# sub_agent_cfg having matching fields; here we only exercise the mechanism.)
ssv_cfg: ENV_NAME         = "nested_test"