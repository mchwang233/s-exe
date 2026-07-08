# =============================================================================
# sim/build/baseline.cmd - baseline compile flags (default build variant)
#
# Invoked via `sexe build` or `sexe build baseline`, output: sim/output/baseline/simv
#
# All compile flags live here (except the output path, which is computed by Python from --out / BUILD=):
#   vlogan:  -full64/-sverilog/+v2k mode + -f <filelist>
#   vcs:     -uvm + -kdb + -CFLAGS / uvm_dpi.cc path
#
# Supported env vars (injected by run_case.py / Makefile, expanded by Python via expandvars):
#   $PROJ_ROOT    = project root (parent of tools/)
#   $UVM_HOME     = UVM source path
#   $VCS_HOME     = VCS install path
#
# Syntax: each line must start with vlogan: / vcs:. **No indented continuation** — write long content across multiple lines, each with its own prefix.
#
# Supported hooks (list shell commands at precomp / presim / postsim; the cwd context differs):
#   precomp:  runs before compile (cwd=proj_root). Use this to run cfg2sv.py to compile .cfg into .sv
#   presim:   runs before simulation (cwd=case run dir)
#   postsim:  runs after simulation (cwd=case run dir; failure only logs, does not change rc)
#
# To add a new build variant: drop a .cmd in this directory, filename = variant name, with its own
# vlogan / vcs lines. No need to touch the Makefile or Python.
#
# Note: do NOT add -debug_access+all — that triggers VCS W-2024's cbug stack annotator
# (which calls cbug-gdb-64/bin/gdb); in our environment gdb returns status=127, which stalls simv.
# Using -kdb alone is enough to prevent UVM 1.2's pre_reset hang, and also supports +kdb_stop=<time>.
# =============================================================================

vlogan: -full64 -sverilog +v2k
vlogan: -f $PROJ_ROOT/tb/filelist.f

vcs: +vcs+lic+wait
vcs: -kdb
vcs: -CFLAGS -DVCS
vcs: -CFLAGS -I$UVM_HOME/dpi
vcs: $UVM_HOME/dpi/uvm_dpi.cc

simv: -l simv.log

vcs: -l vcs.log

# Pre-compile: generate gen/*.sv + all.cmd from cfg/*.cfg
# (cwd=proj_root; cfg2sv.py uses paths relative to its own location, no args needed)
precomp: python3 tools/cfg2sv.py

