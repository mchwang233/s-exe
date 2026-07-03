# cases/_helpers/common.cmd - shared simv args + default UVM verbosity
# Multiple case cmd files can inc: this one to reuse them
simv: +UVM_TESTNAME=my_test
ssv_cfg: ENV_NAME = "from_helpers_inc"