# =============================================================================
# cases/debug_kdb.cmd - Example: use kdb/simv (first `make build BUILD=kdb`) + break
#
# Debug workflow:
#   1. Build the debug simv (once):
#        cd sim && make build BUILD=kdb
#      → sim/kdb/simv (kdb.cmd in sim/build/kdb.cmd controls the compile flags)
#   2. Run (simv halts at kdb_stop=0):
#        make run CASE=debug_kdb BUILD=kdb
#        or cd sim && make run CASE=debug_kdb BUILD=kdb
#   3. In another terminal:
#        verdi -kdb sim/kdb/simv.daidir/kdb.elab++ &
#        Set breakpoints in Verdi, then send run
#
# Current .cmd control surface:
#   binary: <path>   → picks the simv binary path
#   simv:   <args>   → appended to the simv command line (here: +UVM_TESTNAME= and +kdb_stop)
#   break:  <time>   → debug stop point (auto-converted to +kdb_stop=<time>)
#   seed:   <int>    → UVM_SEED (optional; omit for random — fix when reproducing a bug)
# =============================================================================

binary: kdb/simv

# Pick the test class (direct simv: line)
simv: +UVM_TESTNAME=my_test

# Halt simv at t=0
break: start

# Fixed seed for debug (handy when reproducing bugs); omit = random each run
seed: 42