# =============================================================================
# sim/build/kdb.cmd - kdb/Verdi debug build (same as baseline, separate file for future divergence)
#
# Invoked via `sexe build kdb`, output: sim/output/kdb/simv
# When running a case, add `binary: kdb/simv` (or `sexe run CASE=... kdb`)
#
# Content is identical to baseline.cmd — the file is separate only so the BUILD name differs
# (to make it easy later to add more aggressive debug flags to kdb, e.g. -debug_region, etc.)
#
# Note: do NOT add -debug_access+all — that triggers VCS's cbug stack annotator deadlock.
# See the comment at the top of baseline.cmd.
# =============================================================================

vlogan: -full64 -sverilog +v2k
vlogan: -f $PROJ_ROOT/tb/filelist.f

vcs: -uvm +vcs+lic+wait
vcs: -kdb
vcs: -CFLAGS -DVCS
vcs: -CFLAGS -I$UVM_HOME/dpi
vcs: $UVM_HOME/dpi/uvm_dpi.cc

# Pre-compile: generate gen/*.sv + all.cmd from cfg/*.cfg
precomp: python3 tools/cfg2sv.py