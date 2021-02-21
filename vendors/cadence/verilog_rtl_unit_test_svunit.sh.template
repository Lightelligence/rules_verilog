#!/usr/bin/bash
# This is a template for the bazel verilog_rtl_unit_test rule in order to run a SVUnit testbench
# See http://agilesoc.com/open-source-projects/svunit/
# It is not intended to be run stand-alone
# Execute by doing:
#   bazel run <path>:<target>
{SIMULATOR_COMMAND} \
    runSVUnit \
    -s xcelium \
    --no_abs_path_flist \
    --no_feedback \
    {PRE_FLIST_ARGS} \
    -o . \
    -c "-define\ TBV" \
    -c "-libext\ .sv" \
    -c "-libext\ .svh" \
    -c "-libext\ .v" \
    -c "-libext\ .vams" \
    -c "-disable_sem2009" \
    -c "-enable_single_yvlib" \
    -c "-timescale\ 100fs/100fs" \
    -c "-vtimescale\ 100fs/100fs" \
    -c "-define\ TIMESCALE_STEP_FS=100" \
    -c "-define\ TIMESCALE_PREC_FS=100" \
    {FLISTS} \
    {POST_FLIST_ARGS} \
    $@
grep -q "\[testrunner\]: PASSED" run.log
