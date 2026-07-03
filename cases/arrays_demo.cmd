# =============================================================================
# cases/arrays_demo.cmd - demonstrates .cmd override syntax for dynamic arrays / queues
#
# Dynamic array FIELD.size = N changes length (old values are NOT copied)
# Dynamic array FIELD[N]   = val writes the Nth element (auto-grows if N+1 is exceeded)
# Queue        QUEUE       = val each line does one push_back (appended to defaults)
# =============================================================================

simv: +UVM_TESTNAME=my_test

# ---- Dynamic array: set .size first, then write each element ----
ssv_cfg: MY_DYN_ARR.size = 4
ssv_cfg: MY_DYN_ARR[0]   = 10
ssv_cfg: MY_DYN_ARR[1]   = 20
ssv_cfg: MY_DYN_ARR[2]   = 30
ssv_cfg: MY_DYN_ARR[3]   = 40

# ---- Queue: each line pushes once (empty default → push 3 entries) ----
ssv_cfg: MY_QUEUE = 100
ssv_cfg: MY_QUEUE = 200
ssv_cfg: MY_QUEUE = 300

# ---- string dynamic array ----
ssv_cfg: NAMES.size   = 2
ssv_cfg: NAMES[0]     = "alice"
ssv_cfg: NAMES[1]     = "bob"

# ---- string queue ----
ssv_cfg: NAMES_Q      = "carol"
ssv_cfg: NAMES_Q      = "dave"

# COUNTERS is not overridden, should keep the .cfg default value '{1, 2, 3}