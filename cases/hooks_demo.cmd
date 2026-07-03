# =============================================================================
# cases/hooks_demo.cmd - demonstrates the three hooks: precomp: / presim: / postsim:
#
# Run with `make run CASE=hooks_demo`. Expected:
#   1. precomp hook runs before compile (cwd=proj_root), writes echo to /tmp
#   2. presim hook runs before simv starts (cwd=case run dir), writes a marker in case_run_dir
#   3. postsim hook runs after simv exits (cwd=case run dir), checks the marker exists
#
# Delete /tmp/hooks_demo.log before running to clearly see whether the hook actually fired.
# =============================================================================

simv: +UVM_TESTNAME=my_test

# Pre-compile hook (cwd=proj_root): use for generating extra sources / running lint / backing up old artifacts
precomp: echo "[precomp] $(date +%H:%M:%S) cwd=$(pwd) variant=baseline" > /tmp/hooks_demo_precomp.log

# Pre-sim hook (cwd=case run dir): write a marker file for postsim to verify
presim:  echo "[presim] $(date +%H:%M:%S) cfg.info_in_cwd=$([ -f cfg.info ] && echo yes || echo no)"

# Post-sim hook (cwd=case run dir): check sim.log exists + any UVM_FATAL
postsim: echo "[postsim] $(date +%H:%M:%S) sim.log=$([ -f sim.log ] && echo yes || echo no) | fatal=$(grep -c UVM_FATAL sim.log 2>/dev/null || echo 0)"
postsim: cat /tmp/hooks_demo_precomp.log 2>/dev/null && rm -f /tmp/hooks_demo_precomp.log